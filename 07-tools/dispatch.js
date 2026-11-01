// 任务分派箱 CLI（零依赖）
// node dispatch.js list|peek|add|take|stage|done|replay|audit
//
// 设计（2026-11-02 改，吸收 dsh-superagent 的 two things）：
//
// 1. 先落盘再执行。每次变更先往 box.log.jsonl 追加一条事件并 fsync，然后才
//    重放事件生成 box.json 快照。中间崩了，box.json 可能旧，但 log 是完整的
//    —— replay 能把状态补回来。这就是"先记录决定，再去做"。
//
// 2. 工单定义自己的状态，不跟会话走。以前状态只写在 box.json 里，两个进程
//    同时改，后写的直接盖掉前一个（文件无锁）。现在写入要拿目录锁，追加是
//    原子的，重放是幂等的。
//
// 阶段表（第一个匹配胜出，person 开头 = 没有人类输入就动不了）：
//   person:delivery  投递失败，需要重试
//   person:answer    有一个等用户回答的问题
//   person:review    做完了，等验收
//   person:blocked   卡住，或失败后无人处理
//   working:queued   排着队，还没开始
//   idle             取了但还没动
//   working          正在做
//   done             终态

const fs = require('fs');
const path = require('path');

const DIR = path.resolve(__dirname);
const BOX = path.join(DIR, 'box.json');
const LOG = path.join(DIR, 'box.log.jsonl');
const LOCK = path.join(DIR, 'box.lock');
const LOCK_TIMEOUT_MS = 5000;
const LOCK_STALE_MS = 60000;

const STAGES = [
  'person:delivery',
  'person:answer',
  'person:review',
  'person:blocked',
  'working:queued',
  'idle',
  'working',
  'done',
];

// ---------------------------------------------------------------- helpers

function now() {
  const d = new Date();
  const p = n => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
}

function newId() {
  const d = new Date();
  const p = n => String(n).padStart(2, '0');
  return `T${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}-${p(d.getHours())}${p(d.getMinutes())}${p(d.getSeconds())}`;
}

function arg(name) {
  const i = process.argv.indexOf('--' + name);
  return i > -1 ? process.argv[i + 1] || '' : '';
}

function sleepMs(ms) {
  Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, ms);
}

// 目录锁：mkdirSync 在 Windows/POSIX 上都是原子的（已存在就抛 EEXIST）。
function withLock(fn) {
  const deadline = Date.now() + LOCK_TIMEOUT_MS;
  for (;;) {
    try {
      fs.mkdirSync(LOCK);
      break;
    } catch (e) {
      if (e.code !== 'EEXIST') throw e;
      // 陈旧锁：进程可能崩在持锁期间。超过 60 秒就当它死了。
      try {
        const st = fs.statSync(LOCK);
        if (Date.now() - st.mtimeMs > LOCK_STALE_MS) {
          fs.rmdirSync(LOCK);
          continue;
        }
      } catch {
        continue; // 锁刚被释放，直接重试
      }
      if (Date.now() > deadline) {
        throw new Error(`等锁超时（${LOCK_TIMEOUT_MS}ms）：${LOCK}`);
      }
      sleepMs(50);
    }
  }
  try {
    return fn();
  } finally {
    try {
      fs.rmdirSync(LOCK);
    } catch {
      /* 锁已经没了，不影响 */
    }
  }
}

// ---------------------------------------------------------------- event log

function readLog() {
  if (!fs.existsSync(LOG)) return [];
  const rows = [];
  for (const line of fs.readFileSync(LOG, 'utf8').split('\n')) {
    const s = line.trim();
    if (!s) continue;
    try {
      rows.push(JSON.parse(s));
    } catch {
      // 半行（上次写到一半崩了）跳过——它没写完，不算发生过
    }
  }
  return rows;
}

function appendEvent(ev) {
  const row = { seq: readLog().length + 1, at: now(), ...ev };
  const fd = fs.openSync(LOG, 'a');
  try {
    fs.writeSync(fd, JSON.stringify(row) + '\n');
    fs.fsyncSync(fd); // 提交点：这一行落盘了，才算"决定生效"
  } finally {
    fs.closeSync(fd);
  }
  return row;
}

// 重放：事件流是真相，box.json 只是它的一个快照。
function replay(events) {
  const tasks = [];
  const index = new Map();
  for (const ev of events) {
    if (ev.op === 'import') {
      if (!index.has(ev.task.id)) {
        tasks.push(ev.task);
        index.set(ev.task.id, ev.task);
      }
      continue;
    }
    let t = index.get(ev.id);
    if (ev.op === 'add') {
      t = {
        id: ev.id,
        title: ev.title,
        target: ev.target || '任意对话',
        mode: ev.mode || 'box',
        spec: ev.spec || '',
        status: 'pending',
        stage: 'working:queued',
        created: ev.at,
        takenBy: '',
        result: '',
      };
      tasks.push(t);
      index.set(t.id, t);
      continue;
    }
    if (!t) continue; // 事件指向不存在的单（log 被手工改过），忽略
    if (ev.op === 'take') {
      t.status = 'taken';
      t.stage = 'working';
      t.takenBy = ev.by || 'unknown';
      t.takenAt = ev.at;
    } else if (ev.op === 'stage') {
      t.stage = ev.to;
      t.stageAt = ev.at;
      if (ev.reason) t.stageReason = ev.reason;
    } else if (ev.op === 'done') {
      t.status = 'done';
      t.stage = 'done';
      t.result = ev.result || '';
      t.doneAt = ev.at;
    } else if (ev.op === 'reopen') {
      t.status = 'pending';
      t.stage = 'working:queued';
      t.result = t.result || '';
      t.reopenedAt = ev.at;
    }
  }
  return { tasks };
}

function writeSnapshot(data) {
  const tmp = BOX + '.tmp';
  const fd = fs.openSync(tmp, 'w');
  try {
    fs.writeSync(fd, JSON.stringify(data, null, 2) + '\n');
    fs.fsyncSync(fd);
  } finally {
    fs.closeSync(fd);
  }
  fs.renameSync(tmp, BOX); // rename 是原子的：读的人要么看到旧的，要么看到新的
}

// 一次变更 = 追加事件 + 重放 + 写快照，全在锁内。
function commit(ev) {
  return withLock(() => {
    const row = appendEvent(ev);
    writeSnapshot(replay(readLog()));
    return row;
  });
}

// ---------------------------------------------------------------- render

function show(t, verbose) {
  const stage = t.stage || (t.status === 'done' ? 'done' : t.status === 'taken' ? 'working' : 'working:queued');
  const flag = stage.startsWith('person:') ? '!' : ' ';
  console.log(`${flag}[${stage}] ${t.id} | -> ${t.target} | ${t.mode} | ${t.title}`);
  if (verbose) {
    if (t.spec) console.log(`     spec: ${t.spec}`);
    if (t.created) console.log(`     created: ${t.created}  taken_by: ${t.takenBy || '-'}`);
    if (t.stageReason) console.log(`     stage_note: ${t.stageReason}`);
    if (t.result) console.log(`     result: ${t.result}`);
  }
}

function loadSnapshot() {
  if (!fs.existsSync(BOX)) {
    const events = readLog();
    if (!events.length) return { tasks: [] };
    return replay(events);
  }
  try {
    return JSON.parse(fs.readFileSync(BOX, 'utf8'));
  } catch {
    return replay(readLog()); // 快照坏了也别慌，事件流能重建
  }
}

// ---------------------------------------------------------------- cli

const cmd = process.argv[2];
const rest = process.argv.slice(3);

if (cmd === 'add') {
  const title = arg('title');
  if (!title) {
    console.log('ERROR: --title 必填');
    process.exit(2);
  }
  const ev = commit({
    op: 'add',
    id: newId(),
    title,
    target: arg('target') || '任意对话',
    mode: arg('mode') || 'box',
    spec: arg('spec') || '',
  });
  console.log('CREATED');
  const t = loadSnapshot().tasks.find(x => x.id === ev.id);
  if (t) show(t, true);
} else if (cmd === 'list' || cmd === 'peek') {
  const d = loadSnapshot();
  const rows = cmd === 'peek' ? d.tasks.filter(t => t.status !== 'done') : d.tasks;
  if (!rows.length) {
    console.log('BOX_EMPTY');
  } else {
    rows.forEach(t => show(t, true));
    const waiting = rows.filter(t => (t.stage || '').startsWith('person:')).length;
    if (waiting) console.log(`\n有 ${waiting} 单在等人（标 ! 的那些）`);
  }
} else if (cmd === 'take') {
  const id = rest[0];
  const d = loadSnapshot();
  const t = d.tasks.find(x => x.id === id);
  if (!t) {
    console.log('ERROR: 无此单');
    process.exit(2);
  }
  commit({ op: 'take', id, by: arg('by') || 'unknown' });
  console.log('TAKEN');
  show(loadSnapshot().tasks.find(x => x.id === id), true);
} else if (cmd === 'stage') {
  const id = rest[0];
  const to = rest[1];
  if (!STAGES.includes(to)) {
    console.log(`ERROR: 阶段必须是 ${STAGES.join(' | ')}`);
    process.exit(2);
  }
  const d = loadSnapshot();
  const t = d.tasks.find(x => x.id === id);
  if (!t) {
    console.log('ERROR: 无此单');
    process.exit(2);
  }
  commit({ op: 'stage', id, from: t.stage || '', to, reason: arg('reason') || '' });
  console.log('STAGED');
  show(loadSnapshot().tasks.find(x => x.id === id), true);
} else if (cmd === 'done') {
  const id = rest[0];
  const d = loadSnapshot();
  if (!d.tasks.find(x => x.id === id)) {
    console.log('ERROR: 无此单');
    process.exit(2);
  }
  commit({ op: 'done', id, result: arg('result') || '' });
  console.log('DONE');
  show(loadSnapshot().tasks.find(x => x.id === id), true);
} else if (cmd === 'reopen') {
  const id = rest[0];
  const d = loadSnapshot();
  if (!d.tasks.find(x => x.id === id)) {
    console.log('ERROR: 无此单');
    process.exit(2);
  }
  commit({ op: 'reopen', id });
  console.log('REOPENED');
  show(loadSnapshot().tasks.find(x => x.id === id), true);
} else if (cmd === 'replay') {
  // 从事件流重建快照。快照坏了、或者怀疑它和 log 不同步时跑这个。
  const events = readLog();
  const data = replay(events);
  writeSnapshot(data);
  console.log(`REPLAYED  ${events.length} events  ->  ${data.tasks.length} tasks`);
  data.tasks.forEach(t => show(t, false));
} else if (cmd === 'audit') {
  // 对账：快照 vs 事件流，以及"有 in-flight 迹象却没落终态"的单
  const events = readLog();
  const fromLog = replay(events);
  const snap = loadSnapshot();
  let bad = 0;
  if (fromLog.tasks.length !== snap.tasks.length) {
    console.log(`[DIFF] 事件流 ${fromLog.tasks.length} 单 / 快照 ${snap.tasks.length} 单 —— 跑 replay 修`);
    bad++;
  }
  for (const t of fromLog.tasks) {
    const s = snap.tasks.find(x => x.id === t.id);
    if (!s) {
      console.log(`[DIFF] 快照里缺 ${t.id}`);
      bad++;
    } else if ((s.stage || '') !== (t.stage || '')) {
      console.log(`[DIFF] ${t.id} 阶段不一致：快照=${s.stage} 事件流=${t.stage}`);
      bad++;
    }
  }
  const waiting = fromLog.tasks.filter(t => t.status !== 'done' && (t.stage || '').startsWith('person:'));
  if (waiting.length) {
    console.log(`[WAITING] ${waiting.length} 单在等人：`);
    waiting.forEach(t => console.log(`  ${t.id} [${t.stage}] ${t.title}`));
  }
  const stuck = fromLog.tasks.filter(t => t.status === 'taken' && t.stage === 'working');
  if (stuck.length) {
    console.log(`[IN-FLIGHT] ${stuck.length} 单正在做：`);
    stuck.forEach(t => console.log(`  ${t.id}  by ${t.takenBy || '-'}  since ${t.takenAt || '-'}`));
  }
  console.log(bad ? `\n[FAIL] ${bad} 处不一致` : '\n[OK] 快照与事件流一致');
  process.exit(bad ? 1 : 0);
} else if (cmd === 'import') {
  // 一次性：把老的 box.json 里的单灌进事件流（每条一个 import 事件）。
  const old = JSON.parse(fs.readFileSync(BOX, 'utf8'));
  const existing = new Set(readLog().map(e => e.task && e.task.id));
  let n = 0;
  for (const t of old.tasks || []) {
    if (existing.has(t.id)) continue;
    const task = { ...t, stage: t.stage || (t.status === 'done' ? 'done' : t.status === 'taken' ? 'working' : 'working:queued') };
    commit({ op: 'import', task });
    n++;
  }
  console.log(`IMPORTED  ${n} tasks  (log now ${readLog().length} events)`);
} else {
  console.log('用法:');
  console.log('  node dispatch.js add --title "..." --target "..." [--spec "..."] [--mode box|headless]');
  console.log('  node dispatch.js list | peek');
  console.log('  node dispatch.js take <id> --by "..."');
  console.log('  node dispatch.js stage <id> <阶段> [--reason "..."]');
  console.log(`     阶段: ${STAGES.join(' | ')}`);
  console.log('  node dispatch.js done <id> --result "..."');
  console.log('  node dispatch.js reopen <id>');
  console.log('  node dispatch.js replay        # 从事件流重建 box.json');
  console.log('  node dispatch.js audit         # 快照 vs 事件流对账 + 等人/在做的单');
}
