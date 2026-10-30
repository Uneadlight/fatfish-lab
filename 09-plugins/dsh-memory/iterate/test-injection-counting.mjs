/** v0.4.8 回归：注入"仪表盘"必须与"物理状态"完全一致。
 *
 * 背景（2026-10-29 真实缺陷）：注入显示 `32,966/60,000（55%）`，尾行却说"另有 20 条整条缺席"。
 * 根因两条，都在 renderInjection 的计数里：
 *  ① `hidden = ordered.slice(shown.length)` 把 **3/5 及以下**（按设计本来就不注入）也算成"缺席"；
 *  ② memory_save 的百分比用 `注入字符 / CHAR_BUDGET`，而真正的准入上限是
 *     `max(CHAR_BUDGET, 5/5 占用 + 4/5 保底)` —— 5/5 涨上去后上限跟着涨，旧口径会算出 >100% 却一条没丢。
 *
 * 这个测试锁三件事：
 *  A. 尾行把"4/5 因预算缺席"与"3/5 按设计不注入"分开报，数字与真实一致；
 *  B. memory_save 报的字符数 == 真正注入 prompt 的文本长度（不是估算）；
 *  C. memory_save 的百分比 == round(字符数 / 实际准入上限)，且永不 >100%。
 */
import { mkdtempSync, mkdirSync, writeFileSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";

const root = mkdtempSync(join(tmpdir(), "dsh-memory-count-"));
const memDir = join(root, "memory");
mkdirSync(memDir, { recursive: true });
const store = join(memDir, "memories.json");

const now = new Date().toISOString();
const mem = (id, content, importance) => ({
  id,
  content,
  tags: ["t"],
  importance,
  createdAt: now,
  updatedAt: now,
});

writeFileSync(
  store,
  JSON.stringify(
    {
      version: 1,
      memories: [
        mem("m5_a", "FIVE_A", 5),
        mem("m5_b", "FIVE_B", 5),
        mem("m4_a", "FOUR_A", 4),
        mem("m4_b", "FOUR_B", 4),
        mem("m4_c", "FOUR_C", 4),
        mem("m3_a", "THREE_A", 3),
        mem("m3_b", "THREE_B", 3),
        mem("m3_c", "THREE_C", 3),
        mem("m3_d", "THREE_D", 3),
      ],
    },
    null,
    2,
  ) + "\n",
  "utf8",
);

process.env.DSH_HOME = root;
const mod = await import(pathToFileURL("D:\work\\dsh-memory\\lib\\index.js").href);

let sectionText = null;
const tools = new Map();
const ctx = {
  get(name) {
    if (name === "systemPrompt") return { section(def) { sectionText = def.text; } };
    return undefined;
  },
  tools: { register(def) { tools.set(def.name, def); } },
};

let pass = 0;
function ok(cond, msg) {
  if (!cond) throw new Error("FAIL: " + msg);
  pass++;
  console.log("ok - " + msg);
}
const text = () => sectionText();

/** 从 memory_save 的回复里抽出仪表盘：物理长度 / 正文占用 / 准入上限 / 百分比 */
function parseGauge(out) {
  const m = String(out).match(/当前注入 (\d+) 字符；正文 (\d+)\/(\d+)，(\d+)%/);
  if (!m) throw new Error("回复里找不到仪表盘字段：" + String(out).slice(-200));
  return { chars: Number(m[1]), body: Number(m[2]), limit: Number(m[3]), pct: Number(m[4]) };
}
/** 从尾行抽「4/5 注入 a/b 条」与「另有 N 条 4/5 … 缺席」「另有 M 条 3/5 及以下按设计不注入」 */
function parseTail(t) {
  const fours = t.match(/4\/5 注入 (\d+)\/(\d+) 条/);
  const hidden = t.match(/另有 (\d+) 条 4\/5 因超准入上限（(\d+) 字符）整条缺席/);
  const below = t.match(/另有 (\d+) 条 3\/5 及以下按设计不注入/);
  return {
    foursShown: fours ? Number(fours[1]) : null,
    foursTotal: fours ? Number(fours[2]) : null,
    hidden: hidden ? Number(hidden[1]) : 0,
    hiddenLimit: hidden ? Number(hidden[2]) : null,
    below: below ? Number(below[1]) : 0,
  };
}

mod.apply(ctx);
const save = tools.get("memory_save"); // 必须在 apply 之后取，apply 时才注册工具

// ---------- 阶段 A：干净基线，三类条数各归各位 ----------
{
  const t = text();
  const tail = parseTail(t);
  ok(tail.foursTotal === 3, `A1 尾行报到 4/5 共 3 条（实际 ${tail.foursTotal}）`);
  ok(tail.foursShown === 3, "A2 三条 4/5 全部装得下 → 注入 3/3");
  ok(tail.hidden === 0, "A3 没有因预算缺席的 4/5");
  ok(tail.below === 4, `A4 四条 3/5 报成"按设计不注入"（实际 ${tail.below}）`);
  ok(!t.includes("整条缺席"), "A5 关键回归：尾行不再把 3/5 说成'整条缺席'（旧版就是这个 bug）");
  ok(!t.includes("THREE_A"), "A6 3/5 确实没进 prompt");
  for (const s of ["FIVE_A", "FIVE_B", "FOUR_A", "FOUR_B", "FOUR_C"]) ok(t.includes(s), `A7 ${s} 已注入`);

  const out = await save.execute({ content: "GAUGE_PROBE_A", tags: ["t"], importance: 3 });
  const g = parseGauge(out);
  ok(g.chars === text().length, `A8 仪表盘字符数 == 真实注入长度（${g.chars} vs ${text().length}）`);
  ok(g.limit === 60000, `A9 准入上限取 max(60000, 5/5 占用+20000) = ${g.limit}`);
  ok(g.pct === Math.round((g.body / g.limit) * 100), "A10 百分比 == round(正文占用/准入上限)");
  ok(g.pct <= 100, `A11 百分比不越界（${g.pct}%）`);
  ok(String(out).includes("按设计不注入"), "A12 memory_save 也说清 3/5 是按设计不注入");
}

// ---------- 阶段 B：5/5 撑大 → 准入上限必须跟着涨（旧口径会算出 >100%） ----------
{
  const big1 = "BIG5_1 " + "b".repeat(30000);
  const big2 = "BIG5_2 " + "b".repeat(32000);
  await save.execute({ content: big1, tags: ["t"], importance: 5 });
  await save.execute({ content: big2, tags: ["t"], importance: 5 });
  const out = await save.execute({ content: "GAUGE_PROBE_B", tags: ["t"], importance: 3 });
  const g = parseGauge(out);
  const t = text();
  ok(g.chars === t.length, `B1 仪表盘字符数 == 真实注入长度（${g.chars}）`);
  ok(g.chars > 60000, `B2 注入已超过裸预算 60,000（实际 ${g.chars}），但一条 5/5 都没丢`);
  ok(g.limit > 60000, `B3 准入上限跟着 5/5 涨到 ${g.limit}（= 5/5 占用 + 20000）`);
  ok(g.pct === Math.round((g.body / g.limit) * 100), "B4 百分比 == round(正文占用/准入上限)");
  ok(g.pct <= 100, `B5 关键回归：超裸预算也不报 >100%（${g.pct}%）`);
  ok(t.includes(big1) && t.includes(big2), "B6 超长 5/5 全文注入未截断");
}

// ---------- 阶段 C：4/5 塞不下 → 只报真正因预算缺席的那几条 ----------
{
  const markers = [];
  for (let i = 0; i < 3; i++) {
    const marker = `BIG4_${i} `;
    markers.push(marker);
    await save.execute({ content: marker + "c".repeat(20000), tags: ["t"], importance: 4 });
  }
  const out = await save.execute({ content: "GAUGE_PROBE_C", tags: ["t"], importance: 3 });
  const g = parseGauge(out);
  const t = text();
  const tail = parseTail(t);
  ok(g.chars === t.length, `C1 仪表盘字符数 == 真实注入长度（${g.chars}）`);
  ok(tail.foursTotal === 6, `C2 4/5 总数报到 6（实际 ${tail.foursTotal}）`);
  ok(tail.foursShown < tail.foursTotal, `C3 有 4/5 装不下（${tail.foursShown}/${tail.foursTotal}）`);
  ok(tail.hidden === tail.foursTotal - tail.foursShown, "C4 缺席数 == 总数 - 注入数（不再错位）");
  ok(tail.hiddenLimit === g.limit, `C5 尾行报的上限与仪表盘一致（${tail.hiddenLimit} vs ${g.limit}）`);
  const appeared = markers.filter((mk) => t.includes(mk)).length;
  ok(appeared === tail.foursShown, `C6 真实出现的 4/5 条数 == 尾行报的注入数（${appeared} vs ${tail.foursShown}）`);
  ok(g.pct === Math.round((g.body / g.limit) * 100) && g.pct <= 100, `C7 百分比自洽且不越界（${g.pct}%）`);
  ok(tail.below === 7, `C8 3/5 及以下累计 7 条按设计不注入（4 条基线 + 3 条探测，实际 ${tail.below}）`);
  ok(!/另有 \d+ 条整条缺席（不是截断）/.test(t), "C9 旧文案'另有 N 条整条缺席（不是截断）'已彻底消失");
}

console.log(`ALL PASS (${pass})`);
const finalStore = JSON.parse(readFileSync(store, "utf8"));
ok(finalStore.memories.length >= 13, `store 可解析，共 ${finalStore.memories.length} 条`);
rmSync(root, { recursive: true, force: true });
