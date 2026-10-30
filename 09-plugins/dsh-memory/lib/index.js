import {
  readFileSync,
  writeFileSync,
  mkdirSync,
  renameSync,
  unlinkSync,
  readdirSync,
  openSync,
  closeSync,
  statSync,
  appendFileSync,
} from "node:fs";
import { join, dirname } from "node:path";
import { homedir } from "node:os";

export const name = "dsh-memory";
export const inject = ["tools"];

const DSH_HOME = process.env.DSH_HOME || join(homedir(), ".dsh");
const STORE = join(DSH_HOME, "memory", "memories.json");
// 编程知识库：记忆库放长期规则，知识库放踩坑细节；memory_search 搜不中时回退查这里（2026-10-28 新增）
const KNOWLEDGE_DIR = join("D:\work", "学习计划", "01-编程", "知识库");
const SKILLS_DIR = join(DSH_HOME, "skills");

// ── 并发写保护（2026-10-29）────────────────────────────────────────────────
// 每个写操作都是 loadDb() → 改 → saveDb() 的 read-modify-write，窗口只有毫秒级；
// 但如果两个进程（两个 DSH 进程 / 官方版 + 备份版）同时改，后写的会把先写的整条覆盖掉，
// 而且**不会报错**——记忆就这么静默消失。两层防护：
//   ① 跨进程建议锁（.lock，带过期清理，进程崩了不会永久锁死）
//   ② 写前比对文件签名，发现被别人改过就重读 + 按 id 合并（updatedAt 新者胜）
// 单进程正常路径零成本：签名没变就不做任何合并。
const STORE_LOCK = STORE + ".lock";
const LOCK_WAIT_MS = 2000;
const LOCK_STALE_MS = 10_000;
let loadedSig = null; // 上次 loadDb 读到的 "mtimeMs:size"
const pendingDeletes = new Set(); // 本进程明确删掉的 id，合并时不要复活

function fileSig() {
  try {
    const st = statSync(STORE);
    return `${st.mtimeMs}:${st.size}`;
  } catch {
    return null;
  }
}

function sleepSync(ms) {
  Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, ms);
}

/** 抢锁；抢不到也在超时后放行（宁可写，也不要因为一个坏锁彻底写不进去）。 */
function acquireStoreLock() {
  const deadline = Date.now() + LOCK_WAIT_MS;
  for (;;) {
    try {
      const fd = openSync(STORE_LOCK, "wx");
      writeFileSync(fd, `${process.pid} ${new Date().toISOString()}\n`);
      closeSync(fd);
      return true;
    } catch {
      try {
        const st = statSync(STORE_LOCK);
        if (Date.now() - st.mtimeMs > LOCK_STALE_MS) unlinkSync(STORE_LOCK); // 崩溃残留
      } catch { /* 锁刚被释放，直接重试 */ }
      if (Date.now() > deadline) return false;
      sleepSync(15);
    }
  }
}

function releaseStoreLock() {
  try {
    unlinkSync(STORE_LOCK);
  } catch { /* ignore */ }
}

function logConflict(info) {
  try {
    const line = `${new Date().toISOString()} pid=${process.pid} added=${info.added} kept=${info.kept}\n`;
    appendFileSync(join(dirname(STORE), "conflicts.log"), line, "utf8");
  } catch { /* 日志失败不影响主流程 */ }
}

/** 以磁盘版本为底，叠上本进程的改动；同 id 取 updatedAt 较新的一份。 */
function mergeDbs(disk, mine) {
  const byId = new Map();
  for (const m of disk?.memories ?? []) if (m?.id) byId.set(m.id, m);
  const out = [];
  let added = 0;
  for (const m of mine.memories ?? []) {
    if (!m?.id || pendingDeletes.has(m.id)) continue;
    const other = byId.get(m.id);
    if (!other) {
      added++;
      out.push(m);
      byId.delete(m.id);
      continue;
    }
    const t1 = Date.parse(m.updatedAt ?? 0) || 0;
    const t2 = Date.parse(other.updatedAt ?? 0) || 0;
    out.push(t1 >= t2 ? m : other);
    byId.delete(m.id);
  }
  let kept = 0; // 盘上有、本次没提到：另一个进程刚加的，别丢
  for (const m of byId.values()) {
    if (pendingDeletes.has(m.id)) continue;
    out.push(m);
    kept++;
  }
  return { memories: out, added, kept, changed: added > 0 || kept > 0 };
}

const MAX_INJECT = 12; // 基础注入条数；5/5 关键记忆不受此限（见 renderInjection）
// 注入字符预算：默认 60000；短会话模式（DSH_MEMORY_SHORT_SESSION=1）降到 6000，
// 也可用 DSH_MEMORY_CHAR_BUDGET 直接指定（下限 2000 防止被误设成 0 把关键记忆也挤掉）。
// 2026-10-27 用户拍板：9000 → 14000。2026-10-28：14000 → 18000。
// 2026-10-29 第三次：18000 → 30000（加 4/5 保底）。
// 2026-10-29 第四次（用户："直接扩到6万翻倍"）：30000 → 60000。
// 同时注入语义改为"整条完整、绝不截断"：装不下就整条缺席并在尾行报 id，不允许出现半条。
// 实测当时全库正文 33,800 字符（5/5 14,023 + 其他 19,777），60K 下全部完整注入仍有 26K 余量。
const CHAR_BUDGET = (() => {
  const env = Number(process.env.DSH_MEMORY_CHAR_BUDGET || 0);
  if (Number.isFinite(env) && env >= 2000) return env;
  const short = String(process.env.DSH_MEMORY_SHORT_SESSION || "").toLowerCase();
  return ["1", "true", "yes", "on"].includes(short) ? 6000 : 60000;
})();
// 4/5 的保底追加空间：5/5 再膨胀也要给 4/5 留这么多，否则"5/5 全量"会静默把 4/5 挤成 0（2026-10-29 实测踩到）。
// 2026-10-29 随预算翻倍从 12000 提到 20000。
const FOURS_MIN_ALLOWANCE = (() => {
  const env = Number(process.env.DSH_MEMORY_FOURS_MIN || 0);
  // 注意：这里必须是 > 0，不能是 >= 0。v0.4.6 写成 >= 0 时，未设环境变量 → Number("")=0 → 命中 0，
  // 默认 20000 永远取不到，5/5 一旦超过预算，4/5 会被静默饿成 0（2026-10-29 复现）。
  return Number.isFinite(env) && env > 0 ? env : 20000;
})();

function emptyDb() {
  return { version: 1, memories: [] };
}

function loadDb() {
  let raw;
  try {
    raw = readFileSync(STORE, "utf8");
  } catch {
    // 文件不存在（首次使用）或不可读：返回空库。不可读时后续写入会失败，不会静默覆盖。
    return emptyDb();
  }
  try {
    const db = JSON.parse(raw);
    if (db && Array.isArray(db.memories)) {
      loadedSig = fileSig(); // 记住"我们读的是哪一版"，写的时候用来判断有没有被别人改过
      return db;
    }
    throw new Error("memory store shape is invalid");
  } catch {
    // 解析失败时先另存一份原始内容，避免下一次 memory_save 把损坏数据直接覆盖掉。
    if (raw.trim()) {
      try {
        writeFileSync(STORE + ".corrupt-" + Date.now(), raw, "utf8");
      } catch { /* ignore */ }
    }
    return emptyDb();
  }
}

/** 原子写：先写临时文件再改名，避免并发/崩溃留下半截 JSON。 */
function writeStore(db) {
  const text = JSON.stringify(db, null, 2) + "\n";
  const tmp = STORE + ".tmp-" + process.pid + "-" + Date.now();
  writeFileSync(tmp, text, "utf8");
  try {
    renameSync(tmp, STORE);
  } catch {
    // 某些环境下 rename 覆盖失败：退化为直接写 + 清理临时文件
    writeFileSync(STORE, text, "utf8");
    try { unlinkSync(tmp); } catch { /* ignore */ }
  }
  loadedSig = fileSig();
}

/**
 * 存库：先抢跨进程锁，再检查盘上那份是不是我们读的那份。
 * 不是（说明另一个进程刚写过）→ 重读并合并，避免把对方新增的记忆覆盖掉。
 */
function saveDb(db) {
  mkdirSync(dirname(STORE), { recursive: true });
  acquireStoreLock();
  try {
    let final = db;
    const sigNow = fileSig();
    if (loadedSig && sigNow && sigNow !== loadedSig) {
      const disk = loadDb();
      if (disk && Array.isArray(disk.memories)) {
        const merged = mergeDbs(disk, db);
        if (merged.changed) {
          final = { ...db, memories: merged.memories };
          logConflict(merged);
        }
      }
    }
    writeStore(final);
  } finally {
    pendingDeletes.clear();
    releaseStoreLock();
  }
}

function genId() {
  return "mem_" + Date.now().toString(36) + "_" + Math.random().toString(36).slice(2, 8);
}

function nowIso() {
  return new Date().toISOString();
}

function clampImportance(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) return 3;
  return Math.min(5, Math.max(1, Math.round(n)));
}

/** 去重用的归一化：小写、去掉空白与标点。只用于比较，不改变存储内容。 */
function normalizeForDedupe(text) {
  return String(text || "").toLowerCase().replace(/[\s\p{P}]+/gu, "");
}

/** 找重复/疑似重复记忆：完全相同 → 归一化后相同 → 一条完整包含另一条（短者 ≥20 字）。 */
function findDuplicate(memories, content) {
  const target = String(content || "").trim();
  const identical = memories.find((m) => String(m.content || "").trim() === target);
  if (identical) return { memory: identical, kind: "identical" };
  const normalized = normalizeForDedupe(target);
  if (!normalized) return null;
  for (const m of memories) {
    const existing = normalizeForDedupe(m.content);
    if (!existing) continue;
    if (existing === normalized) return { memory: m, kind: "similar" };
    const shorter = existing.length <= normalized.length ? existing : normalized;
    const longer = existing.length <= normalized.length ? normalized : existing;
    if (shorter.length >= 20 && longer.includes(shorter)) return { memory: m, kind: "similar" };
  }
  return null;
}

function fmtOne(m) {
  const tags = (m.tags || []).join(",") || "未分类";
  const imp = m.importance ?? 3;
  const used = m.lastUsedAt ? `，上次用 ${String(m.lastUsedAt).slice(0, 10)}` : "";
  const dead = m.deprecated ? `，已废弃→${m.supersededBy || "?"}` : "";
  return `- [${tags}][${imp}/5] ${m.content} (${m.id}${used}${dead})`;
}

function sortMemories(memories) {
  return [...memories].sort((a, b) => {
    const d = (b.importance ?? 3) - (a.importance ?? 3);
    if (d !== 0) return d;
    const ua = String(a.lastUsedAt || a.updatedAt || "");
    const ub = String(b.lastUsedAt || b.updatedAt || "");
    return ub.localeCompare(ua);
  });
}

/** 免疫衰减的类型：身份 / 偏好 / 规则 / 授权 / 安全 / 红线——永不降级、永不截断。 */
const IMMUNE_TAGS = ["identity", "preference", "rule", "rules", "authorization", "user", "safety", "red-line"];
const DECAY_AFTER_DAYS = 180;
// 4/5 摘要长度：260 → 480（2026-10-29）。2026-10-29 晚用户定下"注入的每一条记忆都必须完整"：
// 该常量不再参与截断，注入一律整条全文；装不下就整条缺席并在尾行报 id（见 renderInjection）。
const SNIPPET_CHARS = 480; // 仅保留给旧逻辑/测试引用，fmtInjected 已不截断

function hasImmuneTag(m) {
  return (m.tags || []).some((t) => IMMUNE_TAGS.includes(String(t).toLowerCase()));
}

/** 中文 2-gram + ASCII 词元：给"整句自然语言"查询用的兜底召回（不做 embedding）。 */
function queryGrams(s) {
  const out = new Set();
  const low = String(s || "").toLowerCase();
  for (const a of low.match(/[a-z0-9_.@\/-]{2,}/g) || []) out.add(a);
  const cjk = low.replace(/[^\u4e00-\u9fa5]/g, " ");
  for (const seg of cjk.split(/\s+/)) {
    for (let i = 0; i < seg.length - 1; i++) out.add(seg.slice(i, i + 2));
  }
  return out;
}

/** 2-gram 打分召回：命中 ≥2 个词元才算候选，按命中数排序（只在关键词检索零命中时用）。 */
function ngramRecall(memories, query) {
  const qg = queryGrams(query);
  if (qg.size === 0) return [];
  return memories
    .map((m) => {
      const tg = queryGrams(`${m.content} ${(m.tags || []).join(" ")}`);
      let hit = 0;
      for (const g of qg) if (tg.has(g)) hit += 1;
      return { m, hit };
    })
    .filter((x) => x.hit >= 2)
    .sort((a, b) => b.hit - a.hit)
    .map((x) => x.m);
}

/** 记忆库搜不中时的第四级兜底：按 2-gram 查编程知识库（D:\work\学习计划\01-编程\知识库）。
 *  记忆库放"长期规则/结论"，知识库放"踩坑细节/课程笔记"；两边都用 queryGrams 打分，取命中 ≥2 的文件。 */
function searchKnowledge(query, limit = 5) {
  const qg = queryGrams(query);
  if (qg.size === 0) return [];
  let files;
  try {
    files = readdirSync(KNOWLEDGE_DIR).filter((f) => f.toLowerCase().endsWith(".md") && f !== "INDEX.md");
  } catch {
    return [];
  }
  const out = [];
  for (const f of files) {
    let text;
    try {
      text = readFileSync(join(KNOWLEDGE_DIR, f), "utf8");
    } catch {
      continue;
    }
    const tg = queryGrams(text);
    let hit = 0;
    for (const g of qg) if (tg.has(g)) hit += 1;
    if (hit < 2) continue;
    // 取最相关的一行当片段（标题行优先：含词元最多的行）
    let best = "";
    let bestHit = 0;
    for (const line of text.split(/\r?\n/)) {
      const t = line.trim();
      if (!t) continue;
      const lg = queryGrams(t.toLowerCase());
      let h = 0;
      for (const g of qg) if (lg.has(g)) h += 1;
      if (h > bestHit) {
        bestHit = h;
        best = t;
      }
    }
    out.push({ file: f, hit, snippet: (best || "").slice(0, 140) });
  }
  return out.sort((a, b) => b.hit - a.hit).slice(0, limit);
}

/** 遗忘/衰减：非免疫 + 5/5 但 180 天未使用 → 降为 4/5（只降级、不删除，可升回）。 */
function applyDecay(db) {
  const now = Date.now();
  let changed = 0;
  for (const m of db.memories) {
    if (m.deprecated) continue;
    if ((m.importance ?? 3) < 5) continue;
    if (hasImmuneTag(m)) continue;
    const stamp = String(m.lastUsedAt || m.updatedAt || m.createdAt || "");
    const t = Date.parse(stamp);
    if (!Number.isFinite(t)) continue;
    if (now - t > DECAY_AFTER_DAYS * 86400000) {
      m.importance = 4;
      m.decayedAt = new Date(now).toISOString();
      changed += 1;
    }
  }
  if (changed) saveDb(db);
  return changed;
}

/** 注入用一行：一律整条全文，绝不截断（2026-10-29 用户要求"每一条注入的记忆都完整"）。
 *  "半条"的根因是这里的 slice：超 480 字截成摘要，关键参数会被切掉、记忆失真。
 *  现在改成：要么整条注入，要么整条缺席（由 renderInjection 的预算决定并报数）。 */
function fmtInjected(m) {
  return fmtOne(m);
}

/** 注入文本的内容指纹：只含内容/标签/重要度/创建时间，不含 lastUsedAt。
 *  memory_search 更新使用时间时不改变系统提示，避免整段前缀缓存失效。 */
function injectionSignature(memories) {
  return JSON.stringify(
    memories.map((m) => [m.id, m.content, m.tags || [], m.importance ?? 3, m.createdAt || "", m.deprecated === true]),
  );
}

let injectionCache = null; // { signature, text }

/** 注入准入计算：**唯一口径**。
 *  renderInjection 的尾行、memory_save 的百分比都从这里取，避免"仪表盘"和"真实注入"两套算法打架。
 *
 *  三类条数必须分开算（v0.4.8 修的就是这个）：
 *   - 5/5：全部注入，不受预算限制
 *   - 4/5：在「准入上限」内尽量注入；装不下的才叫「因预算缺席」
 *   - 3/5 及以下：**按设计就不注入**，不算缺席（旧版把它们也算进"缺席"，于是 55% 却报 20 条缺席）
 *  准入上限 = max(CHAR_BUDGET, 5/5 占用 + FOURS_MIN_ALLOWANCE)：5/5 涨了上限跟着涨，不会把 4/5 饿死。 */
function computeInjection(ordered) {
  const fives = ordered.filter((m) => (m.importance ?? 3) >= 5);
  const fours = ordered.filter((m) => (m.importance ?? 3) === 4);
  const belowThreshold = ordered.length - fives.length - fours.length;
  const fivesChars = fives.reduce((n, m) => n + fmtInjected(m).length, 0);
  const limit = Math.max(CHAR_BUDGET, fivesChars + FOURS_MIN_ALLOWANCE);
  const shownFours = [];
  const hiddenByBudget = [];
  let usedChars = fivesChars;
  for (const m of fours) {
    if (hiddenByBudget.length > 0) {
      hiddenByBudget.push(m); // 已经装不下就整条缺席，保持"按优先级连续取"的确定性
      continue;
    }
    const t = fmtInjected(m).length;
    if (usedChars + t > limit) {
      hiddenByBudget.push(m);
      continue;
    }
    shownFours.push(m);
    usedChars += t;
  }
  return {
    shown: [...fives, ...shownFours],
    report: {
      chars: 0, // 由 renderInjection 在拼完表头/尾行后回填（这才是真正进 prompt 的字符数）
      bodyChars: usedChars, // 被预算约束的"正文"字符数（不含表头/尾行固定开销）
      usedChars,
      limit,
      budget: CHAR_BUDGET,
      fives: { count: fives.length, chars: fivesChars },
      fours: {
        count: fours.length,
        shown: shownFours.length,
        chars: usedChars - fivesChars,
        hidden: hiddenByBudget.length,
      },
      belowThreshold,
      hiddenIds: hiddenByBudget.map((m) => m.id),
    },
  };
}

/** 注入统计（供 memory_save 等"仪表盘"调用）：字符数/准入上限/各类条数，一次算清。 */
function injectionReport() {
  renderInjection(); // 确保缓存是最新的
  return (
    injectionCache?.report ?? {
      chars: 0,
      bodyChars: 0,
      usedChars: 0,
      limit: CHAR_BUDGET,
      budget: CHAR_BUDGET,
      fives: { count: 0, chars: 0 },
      fours: { count: 0, shown: 0, chars: 0, hidden: 0 },
      belowThreshold: 0,
      hiddenIds: [],
    }
  );
}

function renderInjection() {
  const db = loadDb();
  applyDecay(db);
  if (db.memories.length === 0) {
    injectionCache = null;
    return "## 长期记忆（跨会话）\n（记忆库为空：可以用 memory_save 记录值得跨会话保留的信息）";
  }
  const signature = injectionSignature(db.memories);
  if (injectionCache && injectionCache.signature === signature) return injectionCache.text;
  // 已废弃（被新结论取代）的记忆不再注入，避免"旧方案和新方案并存"导致自相矛盾
  const active = db.memories.filter((m) => !m.deprecated);
  const ordered = sortMemories(active);
  const { shown, report } = computeInjection(ordered);
  const lines = ["## 长期记忆（跨会话，来自记忆库）", ""];
  for (const m of shown) lines.push(fmtInjected(m));
  const notes = [
    `5/5 ${report.fives.count} 条全部注入`,
    `4/5 注入 ${report.fours.shown}/${report.fours.count} 条`,
  ];
  if (report.fours.hidden > 0) {
    notes.push(
      `另有 ${report.fours.hidden} 条 4/5 因超准入上限（${report.limit} 字符）整条缺席：${report.hiddenIds.slice(0, 10).join(", ")}${report.hiddenIds.length > 10 ? " …" : ""}`,
    );
  }
  if (report.belowThreshold > 0) {
    notes.push(`另有 ${report.belowThreshold} 条 3/5 及以下按设计不注入`);
  }
  lines.push("", `（以上记忆会在每次会话自动加载：${notes.join("；")}；需要时用 memory_search 检索全文）`);
  const text = lines.join("\n");
  report.chars = text.length; // 从 "## 长期记忆" 到最后一个字符，就是真正注入 prompt 的长度
  injectionCache = { signature, text, report };
  return text;
}

function textOutput() {
  return {
    schema: { type: "string" },
    render: (_args, value) => [{ type: "text", text: String(value) }],
  };
}

/** 查询词拆分为小写词元。 */
function tokenizeQuery(query) {
  return String(query || "").toLowerCase().split(/\s+/).filter(Boolean);
}

/** 按空格拆词做 AND 匹配（内容 + 标签）。 */
function matchQuery(memory, query) {
  const tokens = tokenizeQuery(query);
  if (tokens.length === 0) return false;
  const content = String(memory.content || "").toLowerCase();
  const tags = (memory.tags || []).map((t) => String(t).toLowerCase());
  return tokens.every((t) => content.includes(t) || tags.some((tag) => tag.includes(t)));
}

/** 相关度打分：内容出现次数（封顶 20 次）+ 标签精确匹配权重更高。
 *  只用于排序，是否命中仍由 matchQuery 决定（保证多关键词 AND 语义不变）。 */
function matchScore(memory, tokens) {
  const content = String(memory.content || "").toLowerCase();
  const tags = (memory.tags || []).map((t) => String(t).toLowerCase());
  let score = 0;
  for (const t of tokens) {
    let count = 0;
    let from = 0;
    while (count < 20) {
      const at = content.indexOf(t, from);
      if (at === -1) break;
      count++;
      from = at + t.length;
    }
    if (count > 0) score += 2 + count;
    if (tags.some((tag) => tag === t)) score += 6;
    else if (tags.some((tag) => tag.includes(t))) score += 2;
  }
  return score;
}

/** 搜索结果排序：相关度优先，其次重要度，最后最近使用/更新。 */
function sortByRelevance(memories, tokens) {
  return [...memories]
    .map((memory) => ({ memory, score: matchScore(memory, tokens) }))
    .sort((a, b) => {
      if (b.score !== a.score) return b.score - a.score;
      const d = (b.memory.importance ?? 3) - (a.memory.importance ?? 3);
      if (d !== 0) return d;
      const ua = String(a.memory.lastUsedAt || a.memory.updatedAt || "");
      const ub = String(b.memory.lastUsedAt || b.memory.updatedAt || "");
      return ub.localeCompare(ua);
    })
    .map((x) => x.memory);
}

/* ------------------------------------------------------------------ */
/* Web 路由：供记忆库页面（浏览器半侧）读取与删除记忆                      */
/* ------------------------------------------------------------------ */

function sendJson(res, code, payload) {
  const body = Buffer.from(JSON.stringify(payload), "utf8");
  res.writeHead(code, {
    "Content-Type": "application/json; charset=utf-8",
    "Cache-Control": "no-store",
    "Content-Length": String(body.length),
  });
  res.end(body);
}

function readBody(req, limit = 64 * 1024) {
  return new Promise((resolve) => {
    let size = 0;
    const chunks = [];
    req.on("data", (chunk) => {
      size += chunk.length;
      if (size > limit) {
        req.destroy();
        resolve("");
        return;
      }
      chunks.push(chunk);
    });
    req.on("end", () => resolve(Buffer.concat(chunks).toString("utf8")));
    req.on("error", () => resolve(""));
  });
}

function resolveWebServer(ctx) {
  try {
    const viaGet = typeof ctx.get === "function" ? ctx.get("webServer") : undefined;
    if (viaGet) return viaGet;
  } catch { /* ignore */ }
  return ctx.webServer;
}

/** 本机页面发起的请求才放行（防任意网页借端口读记忆）。 */
function rejected(ctx, req, res) {
  try {
    const conn = typeof ctx.get === "function" ? ctx.get("connection") : undefined;
    if (!conn || typeof conn.requestRejection !== "function") return false;
    const code = conn.requestRejection(req);
    if (code === undefined || code === null || code === false) return false;
    res.statusCode = typeof code === "number" ? code : 403;
    res.end();
    return true;
  } catch {
    return false;
  }
}

function memorySnapshot() {
  const db = loadDb();
  const memories = sortMemories(db.memories);
  let updatedAt = null;
  for (const m of memories) {
    const t = m.updatedAt || m.createdAt;
    if (t && (!updatedAt || String(t) > updatedAt)) updatedAt = t;
  }
  return { ok: true, memories, total: memories.length, updatedAt };
}

function registerWebRoutes(ctx) {
  const webServer = resolveWebServer(ctx);
  if (!webServer || typeof webServer.register !== "function") return;
  const disposers = [];
  try {
    disposers.push(webServer.register({
      kind: "exact",
      path: "/dsh-memory/list",
      handler: async (req, res) => {
        if (rejected(ctx, req, res)) return;
        try {
          if (String(req.method || "GET").toUpperCase() !== "GET") {
            sendJson(res, 405, { ok: false, error: "method not allowed" });
            return;
          }
          sendJson(res, 200, memorySnapshot());
        } catch (err) {
          sendJson(res, 500, { ok: false, error: String(err) });
        }
      },
    }));
    disposers.push(webServer.register({
      kind: "exact",
      path: "/dsh-memory/delete",
      handler: async (req, res) => {
        if (rejected(ctx, req, res)) return;
        try {
          if (String(req.method || "").toUpperCase() !== "POST") {
            sendJson(res, 405, { ok: false, error: "method not allowed" });
            return;
          }
          const text = await readBody(req);
          let payload = null;
          try {
            payload = text ? JSON.parse(text) : null;
          } catch {
            sendJson(res, 400, { ok: false, error: "invalid json" });
            return;
          }
          const id = String(payload?.id ?? "").trim();
          if (!id) {
            sendJson(res, 400, { ok: false, error: "id is empty" });
            return;
          }
          const db = loadDb();
          const before = db.memories.length;
          db.memories = db.memories.filter((m) => m.id !== id);
          if (db.memories.length === before) {
            sendJson(res, 404, { ok: false, error: "not found" });
            return;
          }
          saveDb(db);
          sendJson(res, 200, { ok: true, removed: id });
        } catch (err) {
          sendJson(res, 500, { ok: false, error: String(err) });
        }
      },
    }));
    ctx.effect(() => () => {
      for (const dispose of disposers) {
        try { dispose(); } catch { /* ignore */ }
      }
    });
  } catch (err) {
    try { ctx.logger?.warn?.(`[dsh-memory] web 路由注册失败：${String(err)}`); } catch { /* ignore */ }
  }
}

/* ------------------------------------------------------------------ */
/* 插件入口                                                            */
/* ------------------------------------------------------------------ */

export function apply(ctx) {
  const systemPrompt = ctx.get("systemPrompt");
  if (systemPrompt !== undefined) {
    systemPrompt.section({
      name: "dsh-memory",
      order: 8,
      text: () => renderInjection(),
    });
  }

  ctx.tools.register({
    name: "memory_save",
    description: "把一条值得跨会话保留的信息保存进长期记忆库（比如用户偏好、重要事实、约定、项目背景、教训）。保存后会出现在后续每个会话的系统提示里，请写简洁、自包含的句子；完全重复或高度相似（仅差空白/标点、或一条包含另一条）的记忆不会重复保存。",
    parameters: {
      type: "object",
      properties: {
        content: { type: "string", description: "记忆内容，一句话或一小段，必须自包含（不依赖当前对话上下文）。" },
        tags: { type: "array", items: { type: "string" }, description: "可选标签，比如 preference / fact / project / lesson。" },
        importance: { type: "number", description: "重要性 1-5，默认 3；越高的记忆越靠前注入。" },
        supersedes: { type: "array", items: { type: "string" }, description: "可选：这条新记忆取代的旧记忆 id 列表。旧条目会被标记 deprecated（不再注入、不再算冲突），并指向新条目。" },
      },
      required: ["content"],
    },
    output: textOutput(),
    execute(args) {
      const content = String(args?.content ?? "").trim();
      if (!content) throw new Error("memory content is empty");
      const db = loadDb();
      // 去重：完全相同、去掉空白/标点后相同、或一条被另一条完整包含时都不重复保存，
      // 返回已有 id 并提示用 memory_update，避免同一事实反复追加（库越小注入越省 token）。
      const dup = findDuplicate(db.memories, content);
      if (dup) {
        const stored = String(dup.memory.content || "");
        const preview = stored.length > 160 ? stored.slice(0, 160) + "…" : stored;
        return `已存在${dup.kind === "identical" ? "相同" : "相似"}记忆 ${dup.memory.id}，未重复保存。要改内容请用 memory_update：${preview}`;
      }
      // 冲突提示：找关键词重叠较高、但内容不同的旧记忆，提醒用 supersedes 处理
      const tokens = new Set(content.toLowerCase().split(/[\s，。；、,.;:!?！？]+/).filter((t) => t.length >= 3));
      const overlaps = db.memories
        .filter((m) => !m.deprecated)
        .map((m) => {
          const mt = String(m.content).toLowerCase().split(/[\s，。；、,.;:!?！？]+/).filter((t) => t.length >= 3);
          const hit = mt.filter((t) => tokens.has(t)).length;
          return { m, hit };
        })
        .filter((x) => x.hit >= 4)
        .sort((a, b) => b.hit - a.hit)
        .slice(0, 3);
      const memory = {
        id: genId(),
        content,
        tags: Array.isArray(args?.tags) ? args.tags.map((t) => String(t).trim()).filter(Boolean) : [],
        importance: clampImportance(args?.importance),
        createdAt: nowIso(),
        updatedAt: nowIso(),
        lastVerifiedAt: nowIso(),
      };
      const superseded = [];
      const wanted = Array.isArray(args?.supersedes) ? args.supersedes.map(String) : [];
      for (const id of wanted) {
        const old = db.memories.find((m) => m.id === id);
        if (!old || old.deprecated) continue;
        old.deprecated = true;
        old.supersededBy = memory.id;
        old.deprecatedAt = nowIso();
        superseded.push(id);
      }
      if (superseded.length > 0) memory.supersedes = superseded;
      db.memories.push(memory);
      saveDb(db);
      const tail =
        superseded.length > 0
          ? `\n已标记 ${superseded.length} 条旧记忆为废弃（不再注入）：${superseded.join(", ")}`
          : overlaps.length > 0
            ? `\n⚠ 可能与下列旧记忆冲突（若新结论取代它们，请重存并带 supersedes）：${overlaps.map((x) => `${x.m.id}「${String(x.m.content).slice(0, 40)}…」`).join("；")}`
            : "";
      const rep = injectionReport();
      // 百分比一律用「正文占用 / 准入上限」：正文才是被预算约束的量，
      // 表头/尾行那些固定开销不该算进分子（否则 62,189 字符对 62,080 上限会算出 >100%）。
      const pct = rep.limit > 0 ? Math.round((rep.bodyChars / rep.limit) * 100) : 0;
      const level = pct >= 80 ? `；⚠ 已达 80% 报警线（${pct}%），建议做一次记忆体检/压缩` : "";
      const detail =
        `准入上限 ${rep.limit} = max(预算 ${rep.budget}, 5/5 占用 ${rep.fives.chars} + 4/5 保底 ${FOURS_MIN_ALLOWANCE})；` +
        `4/5 注入 ${rep.fours.shown}/${rep.fours.count} 条` +
        (rep.fours.hidden > 0 ? `（${rep.fours.hidden} 条超上限缺席）` : "") +
        (rep.belowThreshold > 0 ? `；3/5 及以下 ${rep.belowThreshold} 条按设计不注入` : "");
      return `已保存记忆 ${memory.id}：${content}${tail}\n（当前注入 ${rep.chars} 字符；正文 ${rep.bodyChars}/${rep.limit}，${pct}%；${detail}${level}）`;
    },
  });

  ctx.tools.register({
    name: "memory_search",
    description: "在长期记忆库中按关键词搜索记忆（空格分隔多个关键词 = 全部匹配；匹配内容与标签；结果按相关度排序，同分再按重要度/最近使用）。",
    parameters: {
      type: "object",
      properties: {
        query: { type: "string", description: "搜索关键词，多个用空格分隔。" },
        includeDeprecated: { type: "boolean", description: "可选：true 时也搜索已废弃（被新结论取代）的记忆，默认排除。" },
      },
      required: ["query"],
    },
    output: textOutput(),
    execute(args) {
      const query = String(args?.query ?? "").trim().toLowerCase();
      if (!query) throw new Error("query is empty");
      const db = loadDb();
      const includeDeprecated = args?.includeDeprecated === true;
      const pool = db.memories.filter((m) => includeDeprecated || !m.deprecated);
      let hits = pool.filter((m) => matchQuery(m, query));
      if (hits.length === 0) {
        // AND 无结果时退化 OR（中文无分词，多词 AND 常零命中），命中任一关键词即算
        const tokens = tokenizeQuery(query);
        hits = pool.filter((m) => {
          const text = String(m.content + " " + (m.tags || []).join(" ")).toLowerCase();
          return tokens.some((t) => text.includes(t));
        });
      }
      if (hits.length === 0) {
        // 第三级兜底：整句自然语言 → 中文 2-gram 打分召回（实测自然语言问法从 0% 提到 60%）
        hits = ngramRecall(pool, query);
      }
      if (hits.length === 0) {
        // 第四级兜底：记忆库放长期规则，知识库放踩坑细节；两边都查，别让知识只活在一处
        const kb = searchKnowledge(query);
        if (kb.length > 0) {
          return `记忆库里没有与「${query}」相关的记录，但编程知识库（${KNOWLEDGE_DIR}）里有 ${kb.length} 条相关：\n` +
            kb.map((x) => `- ${x.file}：${x.snippet}`).join("\n");
        }
        return `没有找到与「${query}」相关的记忆`;
      }
      // 先按相关度（词频 + 标签精确匹配）排序，同分再按重要性/最近使用
      const orderedHits = sortByRelevance(hits, tokenizeQuery(query));
      // 命中即记录最近使用时间（用于注入排序）
      const now = nowIso();
      for (const m of hits) m.lastUsedAt = now;
      saveDb(db);
      return `找到 ${hits.length} 条记忆：\n` + orderedHits.map(fmtOne).join("\n");
    },
  });

  ctx.tools.register({
    name: "memory_list",
    description: "列出长期记忆库中的记忆（按重要性从高到低），可选按标签过滤。",
    parameters: {
      type: "object",
      properties: {
        limit: { type: "number", description: "最多列出几条，默认 20。" },
        tag: { type: "string", description: "可选：只看带该标签的记忆。" },
      },
    },
    output: textOutput(),
    execute(args) {
      const db = loadDb();
      let memories = sortMemories(db.memories);
      const tag = String(args?.tag ?? "").trim().toLowerCase();
      if (tag) memories = memories.filter((m) => (m.tags || []).some((t) => String(t).toLowerCase() === tag));
      const limit = Math.max(1, Math.min(100, Number(args?.limit) || 20));
      const shown = memories.slice(0, limit);
      if (shown.length === 0) return "记忆库中没有匹配的记忆";
      return `共 ${memories.length} 条，显示前 ${shown.length} 条：\n` + shown.map(fmtOne).join("\n");
    },
  });

  ctx.tools.register({
    name: "memory_update",
    description: "修改一条已有记忆的内容、标签或重要性（按 id）。",
    parameters: {
      type: "object",
      properties: {
        id: { type: "string", description: "要修改的记忆 id，形如 mem_xxx。" },
        content: { type: "string", description: "新内容（可选）。" },
        tags: { type: "array", items: { type: "string" }, description: "新标签（可选，整体替换）。" },
        importance: { type: "number", description: "新的重要性 1-5（可选）。" },
      },
      required: ["id"],
    },
    output: textOutput(),
    execute(args) {
      const id = String(args?.id ?? "").trim();
      if (!id) throw new Error("id is empty");
      const db = loadDb();
      const memory = db.memories.find((m) => m.id === id);
      if (!memory) return `没有找到记忆 ${id}`;
      if (args?.content !== undefined) {
        const content = String(args.content).trim();
        if (!content) throw new Error("content is empty");
        memory.content = content;
      }
      if (args?.tags !== undefined) {
        memory.tags = Array.isArray(args.tags) ? args.tags.map((t) => String(t).trim()).filter(Boolean) : [];
      }
      if (args?.importance !== undefined) memory.importance = clampImportance(args.importance);
      memory.updatedAt = nowIso();
      saveDb(db);
      return `已更新记忆 ${id}`;
    },
  });

  ctx.tools.register({
    name: "memory_forget",
    description: "从长期记忆库中删除一条记忆（按 id）。",
    parameters: {
      type: "object",
      properties: {
        id: { type: "string", description: "要删除的记忆 id，形如 mem_xxx。" },
      },
      required: ["id"],
    },
    output: textOutput(),
    execute(args) {
      const id = String(args?.id ?? "").trim();
      if (!id) throw new Error("id is empty");
      const db = loadDb();
      const before = db.memories.length;
      db.memories = db.memories.filter((m) => m.id !== id);
      if (db.memories.length === before) return `没有找到记忆 ${id}`;
      pendingDeletes.add(id); // 告诉合并逻辑：这条是我主动删的，别从盘上复活
      saveDb(db);
      return `已删除记忆 ${id}`;
    },
  });

  ctx.tools.register({
    name: "memory_to_skill",
    description:
      "把一条流程性/操作性的长期记忆转成技能文件（SKILL.md）：知识从『备忘录』升级成『说明书』。会在 DSH 技能目录（$DSH_HOME/skills/<slug>/SKILL.md）新建技能，供之后按需加载；原记忆保留并打上 skill:<slug> 标签，不会被删除。适合「每次都要按步骤做」的记忆，不适合一次性事实。",
    parameters: {
      type: "object",
      properties: {
        id: { type: "string", description: "要转换的记忆 id（mem_xxx）。与 query 二选一。" },
        query: { type: "string", description: "按关键词查找记忆（找不到再试 id），命中最相关的一条。" },
        name: { type: "string", description: "技能名（小写英文/短横线）；缺省用记忆 id 派生。" },
      },
      required: [],
    },
    output: textOutput(),
    execute(args) {
      const db = loadDb();
      let target = null;
      const id = String(args?.id ?? "").trim();
      if (id) target = db.memories.find((m) => m.id === id) || null;
      if (!target) {
        const query = String(args?.query ?? "").trim();
        if (!query) throw new Error("需要 id 或 query 指定要转换的记忆");
        const hits = db.memories.filter((m) => matchQuery(m, query));
        if (hits.length > 0) target = sortByRelevance(hits, tokenizeQuery(query))[0];
      }
      if (!target) return `没有找到匹配的记忆（id=${id || "-"}）`;

      const content = String(target.content || "").trim();
      let slug = String(args?.name || "").trim().toLowerCase();
      if (!slug) slug = `skill-${String(target.tags?.[0] || "memory")}-${target.id.replace(/^mem_/, "").slice(0, 8)}`;
      slug = slug.replace(/[^a-z0-9-]+/g, "-").replace(/-+/g, "-").replace(/^-|-$/g, "");
      if (!slug) slug = `skill-${Date.now()}`;

      const title = target.tags?.length ? `${target.tags[0]} / ${slug}` : slug;
      const oneLine = content.replace(/\s+/g, " ").slice(0, 120);
      const skillMd = [
        "---",
        `name: ${slug}`,
        `description: ${JSON.stringify(oneLine)}`,
        "---",
        "",
        `# ${slug}`,
        "",
        "> 由 dsh-memory 从记忆 `" + target.id + "` 转换而来；原记忆仍在记忆库中。",
        "",
        "## 背景 / 适用场景",
        "",
        `- 标签：${(target.tags || []).join("、") || "（无）"}`,
        `- 重要性：${target.importance ?? 3}/5`,
        `- 原始记忆：${target.id}`,
        "",
        "## 步骤 / 要点",
        "",
        content,
        "",
        "## 使用提示",
        "",
        "1. 触发条件满足时加载本技能，按上面的步骤执行。",
        "2. 执行中如果发现步骤过时，用 memory_update 更新原记忆，再重新转换一次。",
      ].join("\n");

      const dir = join(SKILLS_DIR, slug);
      mkdirSync(dir, { recursive: true });
      const file = join(dir, "SKILL.md");
      writeFileSync(file, skillMd + "\n", "utf8");

      const tag = `skill:${slug}`;
      if (!Array.isArray(target.tags)) target.tags = [];
      if (!target.tags.includes(tag)) target.tags.push(tag);
      target.updatedAt = nowIso();
      saveDb(db);
      return `已生成技能 ${slug}：${file}（${skillMd.length} 字符）；原记忆 ${target.id} 已打标签 ${tag}`;
    },
  });

  // 记忆库页面（侧边栏入口）的 Web 接口：等待 webServer 服务就绪再注册。
  // 用 ctx.inject 而非直接注册：headless 等无 webServer 的 profile 里回调不会执行，
  // 插件其余功能（工具、系统提示注入）不受影响。
  if (typeof ctx.inject === "function") {
    ctx.inject(["webServer"], (webCtx) => {
      registerWebRoutes(webCtx);
    });
  } else {
    registerWebRoutes(ctx);
  }
}
