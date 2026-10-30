#!/usr/bin/env node
/**
 * test-store-lock.mjs —— 记忆库并发写保护（v0.4.9）
 *
 * 背景：每个写操作都是 loadDb() → 改 → saveDb()。两个进程同时改时，
 * 后写的会把先写的整条覆盖掉，而且不报错（记忆静默消失）。
 *
 * 本测试用真实子进程制造竞争，验证三件事：
 *   A 并发新增不丢：4 个进程 × 5 条 = 20 条，最后必须 20 条都在
 *   B 主动删除不复活：删掉之后别的进程写入，不会把删掉的条目从盘上捞回来
 *   C 跨进程可见：别人写的，我下一次 save 之后仍然在
 */
import { mkdtempSync, writeFileSync, readFileSync, existsSync } from "node:fs";
import { spawn } from "node:child_process";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";

const LIB = "D:\work\\dsh-memory\\lib\\index.js";
const home = mkdtempSync(join(tmpdir(), "memlock-"));
process.env.DSH_HOME = home;

let pass = 0;
let fail = 0;
function ok(cond, label) {
  if (cond) { pass++; console.log(`ok - ${label}`); }
  else { fail++; console.log(`NOT OK - ${label}`); }
}

const mod = await import(pathToFileURL(LIB).href);
const tools = new Map();
mod.apply({
  get: (n) => (n === "systemPrompt" ? { section() {} } : undefined),
  tools: { register(d) { tools.set(d.name, d); } },
});
const save = tools.get("memory_save");
const forget = tools.get("memory_forget");

const STORE = join(home, "memory", "memories.json");
function readDb() {
  return JSON.parse(readFileSync(STORE, "utf8"));
}
function countTag(tag) {
  return readDb().memories.filter((m) => (m.tags ?? []).includes(tag)).length;
}

// ── 子进程脚本：往同一个库里写 N 条 ────────────────────────────────────────
const WORKER = join(home, "worker.mjs");
writeFileSync(
  WORKER,
  `import { pathToFileURL } from "node:url";
const [lib, n, tag] = process.argv.slice(2);
const mod = await import(pathToFileURL(lib).href);
const tools = new Map();
mod.apply({ get: () => undefined, tools: { register(d) { tools.set(d.name, d); } } });
const save = tools.get("memory_save");
for (let i = 0; i < Number(n); i++) {
  await save.execute({ content: \`并发写入 \${tag} 第 \${i} 条 \${Math.random().toString(36).slice(2)}\`, importance: 3, tags: [tag] });
}
`,
  "utf8",
);

function runWorker(n, tag) {
  return new Promise((resolve, reject) => {
    const p = spawn(process.execPath, [WORKER, LIB, String(n), tag], {
      env: { ...process.env, DSH_HOME: home },
      stdio: ["ignore", "pipe", "pipe"],
    });
    let err = "";
    p.stderr.on("data", (d) => { err += d.toString(); });
    p.on("exit", (code) => (code === 0 ? resolve() : reject(new Error(`worker ${tag} 退出 ${code}: ${err.slice(0, 300)}`))));
  });
}

// ── A 并发新增不丢 ─────────────────────────────────────────────────────────
const TAGS = ["ca", "cb", "cc", "cd"];
const results = await Promise.allSettled(TAGS.map((t) => runWorker(5, t)));
const failedWorkers = results.filter((r) => r.status === "rejected");
ok(failedWorkers.length === 0, `A0 四个写入进程都正常退出${failedWorkers.length ? "：" + failedWorkers[0].reason.message : ""}`);

const total = TAGS.reduce((s, t) => s + countTag(t), 0);
ok(total === 20, `A1 并发 4×5 条全部落库（实际 ${total}/20，丢 ${20 - total} 条）`);
ok(existsSync(join(home, "memory", "conflicts.log")) || total === 20, "A2 冲突要么被合并、要么压根没发生");

// ── B 主动删除不复活 ───────────────────────────────────────────────────────
await save.execute({ content: "这条等下要被删掉 del-target-7f3a", importance: 3, tags: ["delme"] });
ok(countTag("delme") === 1, "B1 先写一条待删的");
const targetId = readDb().memories.find((m) => (m.tags ?? []).includes("delme")).id;
await forget.execute({ id: targetId });
ok(countTag("delme") === 0, "B2 删除成功");

await runWorker(1, "other"); // 另一个进程在我们删完之后写
await save.execute({ content: "删除后再写一条 keep-after-delete-91c2", importance: 3, tags: ["after"] });
const afterDb = readDb();
ok(!afterDb.memories.some((m) => m.id === targetId), "B3 被删的那条没有被合并逻辑复活");
ok(countTag("other") === 1, "B4 别的进程写的条目还在");
ok(countTag("after") === 1, "B5 我随后写的条目也在");

// ── C 跨进程可见 + 总数自洽 ────────────────────────────────────────────────
const dbNow = readDb();
ok(Array.isArray(dbNow.memories) && dbNow.memories.length === total + 2, `C1 总数自洽（${dbNow.memories.length} = 20 + 2）`);
ok(dbNow.version === 1 || dbNow.version === undefined, "C2 库结构和版本字段没被破坏");
ok(!existsSync(join(home, "memory", "memories.json.lock")), "C3 锁文件已释放（没留下死锁）");

console.log(`\n${fail === 0 ? "ALL PASS" : "FAILED"} (${pass} passed, ${fail} failed)`);
process.exit(fail === 0 ? 0 : 1);
