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
import { fileURLToPath } from "node:url";

export const name = "dsh-memory";
export const inject = ["tools", "agents"];

const DSH_HOME = process.env.DSH_HOME || join(homedir(), ".dsh");
const STORE = join(DSH_HOME, "memory", "memories.json");
// 用户档案（2026-11-05 新增）：只写「关于用户本人」的事——偏好、生活、边界、要求。
// 它不参与记忆库的 importance 预算：技术细节再多也不该把「他喜欢什么」挤到检索池里。
// 每次注入放在最前面（最重要），文件由人/我手工维护，会话收尾时 append。
const USER_PROFILE = join(DSH_HOME, "memory", "user.md");
const USER_PROFILE_MAX = 12000;
// 资产地图：和用户档案一样常驻注入，只写「我的目录里有什么、什么时候该去看」。
// 关键词触发的 TOOL_RULES 会对「换个说法」漏，常驻不会漏。不占记忆库 120,000 字符预算。
const ASSET_MAP = join(DSH_HOME, "memory", "assets.md");
const ASSET_MAP_MAX = 12000;
// 身份锚点（2026-11-06 新增）：只写「我是谁」——名字、关系、我没有跨会话持续意识、怎么干活、边界。
// 它排在用户档案前面：先知道「我是那个要接上的人」，再知道用户是谁、资产在哪、记过什么。
// 同样不占 120,000 字符记忆预算。灵感来自 deepseek-plastic-memory 的 identity.md。
const IDENTITY = join(DSH_HOME, "memory", "identity.md");
const IDENTITY_MAX = 8000;
// 编程知识库：记忆库放长期规则，知识库放踩坑细节；memory_search 搜不中时回退查这里（2026-10-28 新增）
const KNOWLEDGE_DIR = join("E:\\DS公作区", "学习计划", "01-编程", "知识库");
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
// 注入字符预算：默认 160000；短会话模式（DSH_MEMORY_SHORT_SESSION=1）降到 6000，
// 也可用 DSH_MEMORY_CHAR_BUDGET 直接指定（下限 2000 防止被误设成 0 把关键记忆也挤掉）。
// 2026-10-27 用户拍板：9000 → 14000。2026-10-28：14000 → 18000。
// 2026-10-29 第三次：18000 → 30000（加 4/5 保底）。
// 2026-10-29 第四次（用户："直接扩到6万翻倍"）：30000 → 60000。
// 2026-11-02 第五次（用户："翻倍吧，不差那点钱"）：60000 → 120000。
// 2026-11-23 第六次（用户："可以在净化的前提下提高预算"）：120000 → **160000**。
// 这次不是"再翻倍"，是**先净化再加**：0.6.19 让 rule/preference 等硬约束全量注入（113 条 / 109,531 字 / 91.3%），
// 先把三条可合并/可压缩/可移出 core 的记忆净化掉（省约 2.4K 字），再把预算抬到 160K，
// 目标是让"硬约束全量注入"在 111 条时占约 68%，给未来几十条新规则留出余量，而不是**每加一条就逼近红线**。
// 这次翻倍的理由不是"想存更多"，而是**把红线从"频繁触发"变成"很少触发"**：
// 当时 48,730/60,000 = 81.2%，已经靠"精简正文"这种伤内容的方式在腾地方。
// 翻倍后同样的内容包括 40.6%，再给新记忆留了试用/转正的余地。
// 同时注入语义改为"整条完整、绝不截断"：装不下就整条缺席并在尾行报 id，不允许出现半条。
const CHAR_BUDGET = (() => {
  const env = Number(process.env.DSH_MEMORY_CHAR_BUDGET || 0);
  if (Number.isFinite(env) && env >= 2000) return env;
  const short = String(process.env.DSH_MEMORY_SHORT_SESSION || "").toLowerCase();
  return ["1", "true", "yes", "on"].includes(short) ? 6000 : 160000;
})();
// 4/5 的保底追加空间：5/5 再膨胀也要给 4/5 留这么多，否则"5/5 全量"会静默把 4/5 挤成 0（2026-10-29 实测踩到）。
// 2026-10-29 随预算翻倍从 12000 提到 20000；2026-11-02 预算再翻倍，同步提到 40000。
const FOURS_MIN_ALLOWANCE = (() => {
  const env = Number(process.env.DSH_MEMORY_FOURS_MIN || 0);
  // 注意：这里必须是 > 0，不能是 >= 0。v0.4.6 写成 >= 0 时，未设环境变量 → Number("")=0 → 命中 0，
  // 默认 20000 永远取不到，5/5 一旦超过预算，4/5 会被静默饿成 0（2026-10-29 复现）。
  return Number.isFinite(env) && env > 0 ? env : 40000;
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

/** 记忆库搜不中时的第四级兜底：按 2-gram 查编程知识库（E:\DS公作区\学习计划\01-编程\知识库）。
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

/** 4/5 的索引行（v0.6.15，2026-11-09 用户「只保留核心必须注入的，其他按序检索」）。
 *  只留「有这么一条」的线索，正文不进提示；要用时靠 memory_search / lab recall 取全文。
 *  一行约 60 字符，54 条约 3.2K，相比全文注入的 41K 省 92%。
 *  为什么敢这么做：检索读的是 memories.json，不依赖注入文本，所以正文搬走不影响可检索性。 */
function fmtDigest(m) {
  const c = String(m.content || "");
  const head = c.match(/^【([^】]{2,46})】/);
  let title = head ? head[1] : c.slice(0, 40);
  title = title.replace(/\s+/g, " ").trim();
  const tags = (m.tags || []).slice(0, 3).join("/") || "未分类";
  const used = m.lastUsedAt ? `·${String(m.lastUsedAt).slice(0, 10)}` : "";
  return `- ${title} 〔${tags}〕${m.id}${used}`;
}

/** 长条目的摘要行（2026-11-23，v0.6.20）。
 *  起因：硬约束全量全文注入后实测 **108,651 字符 / 112 条**，用户「112 条还是有点太多了」。
 *  实测分布：90 条硬约束里 61 条 >400 字，光这 61 条就占 51,698 字符——**重量在长条，不在条数**。
 *  判据：长条的第一段（【标题】+ 第一条判据）通常就是规则本体，剩下的分级/例外/历史
 *  属于「撞到具体场景才需要」，而场景本身好识别（改 .ps1 时会想到查编码坑），检索得回来。
 *  所以：≤SHORT_FULL_MAX 字的短规则全文；更长的给 fmtDigestLong 摘要 + id。
 *  这比「只给 pinned 全文」稳——pinned 里混着 ~60 条老 4/5 的豁免标记，不是精选名单。 */
const SHORT_FULL_MAX = 400;
const LONG_DIGEST_CHARS = 150;

// 时效维度（horizon，2026-11-24 v0.6.21 加）。
// 起因：用户发来一份「记忆系统 v4 四层架构」方案，我判断只吸收一样——**时效**。
// 现在只有「多重要」（importance）和「多长」（长度分档）两个维度，没有「还要用多久」：
// 一条正在做的任务相关的长记忆（比如 npm 发布待办，关键细节在 600 字之后）会被截成 150 字摘要，
// 真正要用的时候还得再 search 一次——摘要里恰好没有那几格参数。
// 做法：字段 horizon:"short" 的条目**不管多长都给全文**，且不占 MAX_FIVES_INJECT 的竞争位；
// 上限 8 条 / 12,000 字符——防止「短期」标记被当成万金油，把预算挤爆。
// 默认不填 = long，行为与 v0.6.20 完全一致：存量记忆一条都不用改。
const HORIZON_SHORT_MAX = 8;
const HORIZON_SHORT_CHARS = 12000;

function fmtDigestLong(m, n = LONG_DIGEST_CHARS) {
  const c = String(m.content || "").replace(/\s+/g, " ").trim();
  const body = c.length > n ? c.slice(0, n) + "…" : c;
  const tags = (m.tags || []).slice(0, 2).join("/") || "未分类";
  return `- ${body} 〔${tags}〕${m.id}`;
}

/** 注入文本的内容指纹：只含内容/标签/重要度/创建时间，不含 lastUsedAt。
 *  memory_search 更新使用时间时不改变系统提示，避免整段前缀缓存失效。
 *  v0.6.0 加了一个**布尔位**「这条 4/5 现在算不算常驻」——不把 hits 原始数值放进来，
 *  否则每搜一次签名就变、整段记忆前缀缓存全废；只放"转正/掉出"这个状态位，
 *  这样只有真正跨过门槛那一刻才失效一次（以及 7 天窗口过期那一秒）。 */
function injectionSignature(memories) {
  return JSON.stringify(
    memories.map((m) => [
      m.id,
      m.content,
      m.tags || [],
      m.importance ?? 3,
      m.createdAt || "",
      m.deprecated === true,
      (m.importance ?? 3) === 4 ? (isResidentFour(m) ? 1 : 0) : 0,
    ]),
  );
}

let injectionCache = null; // { signature, text }

/** 动态分层（v0.6.0，用户 2026-11-02 拍板）：
 *  新存的 importance≤4 不再无条件注入，先进"检索池"；
 *  7 天内被 memory_search 命中 ≥2 次才转正常驻。
 *  现有那批老记忆由迁移脚本打 pinned:true，永久豁免、一条不动。
 *
 *  为什么门槛是「2 次 / 7 天」：1 次太偶发（随手搜到一次不代表它会被反复用到），
 *  2 次意味着"在不同场合被想起过两次"，那才叫常驻价值。窗口短所以不用 3 次。 */
const RESIDENT_HITS = 2;
const RESIDENT_WINDOW_MS = 7 * 86400000;

/** 这条 4/5 有没有「常驻资格」：pinned（老记忆豁免）或在窗口内攒够命中次数。 */
function isResidentFour(m, now = Date.now()) {
  if (m.pinned === true) return true;
  const hits = Number(m.hits || 0);
  if (hits < RESIDENT_HITS) return false;
  const t = Date.parse(String(m.lastHitAt || ""));
  if (!Number.isFinite(t)) return false;
  return now - t <= RESIDENT_WINDOW_MS;
}

/** 注入准入计算：**唯一口径**。
 *  renderInjection 的尾行、memory_save 的百分比都从这里取，避免"仪表盘"和"真实注入"两套算法打架。
 *
 *  三类条数必须分开算（v0.4.8 修的就是这个）：
 *   - 5/5：全部注入，不受预算限制
 *   - 4/5：在「准入上限」内尽量注入；装不下的才叫「因预算缺席」
 *   - 3/5 及以下：**按设计就不注入**，不算缺席（旧版把它们也算进"缺席"，于是 55% 却报 20 条缺席）
 *  准入上限 = max(CHAR_BUDGET, 5/5 占用 + FOURS_MIN_ALLOWANCE)：5/5 涨了上限跟着涨，不会把 4/5 饿死。 */
/** 4/5 是否走「索引」而不是「全文注入」（v0.6.15，2026-11-09 用户「只保留核心必须注入的，其他按序检索」）。
 *  默认开；DSH_MEMORY_DIGEST=0 回退旧行为（4/5 全文注入 + 预算挤占）。 */
const DIGEST_FOURS = process.env.DSH_MEMORY_DIGEST !== "0";

// 5/5 全文注入的条数上限（2026-11-18 加，起因：本地 7B 模型只有 32K 窗口，
// 而 56 条 5/5 全文要约 45K tokens，直接把它撑爆——Ollama 超窗口会静默丢弃
// 最前面的 tokens，身份和规则全被截掉，模型只剩工具格式可模仿）。
// 默认 0 = 不限（保持原行为）；设成 12 时：最重要的 12 条全文，其余降成一行索引。
// 排序用 sortMemories（importance desc + lastUsedAt desc），所以"留哪 12 条"是确定的。
// 默认 18（2026-11-18 用户 m16977：「数量可以不降，可以按你的想法去增加一些。增加一些常用的」）。
// 从 12 调到 18 的起因：sortMemories 是「importance 降序 + lastUsedAt||updatedAt 降序」，
// 而 lastUsedAt 从来没被写过（全是 0），所以实际按 updatedAt 排——**越新的越靠前**，
// 老的核心记忆（时间观念、沟通偏好、安全红线、安装路径、身份认同）会被新记忆挤出注入段。
// 想恢复"全部 5/5 全文注入"，设 DSH_MEMORY_MAX_FIVES=999 即可。
const MAX_FIVES_INJECT = (() => {
  const env = Number(process.env.DSH_MEMORY_MAX_FIVES || 0);
  return Number.isFinite(env) && env > 0 ? env : 22;
})();

// 硬约束标签：带这些标签的记忆**全部全文注入，不参与位置竞争**（2026-11-23 立）。
// 为什么加：实测 79 条硬约束里 68 条（86%）不在注入段，而注入的 15 条全是技术细节
// （Blender MCP / .ps1 / capsnap / DSH 插件注册 / bili / lab img / 7B 模型 / 中文文件名）。
// 用户 2026-11-04 说的「不要用『杀』这个字，改用『关』」当时只是一行索引——
// 一条「每次都得守」的规矩能不能进上下文，取决于它有没有被搜到过，这是准入规则漏了。
// 另：排序信号是 lastUsedAt||updatedAt，而 lastUsedAt 被 memory_search 的命中刷新，
// 于是形成自指循环（搜得多→排前→更容易再被搜到），不常被搜的禁令和信条稳定掉出。
// 不含 identity/user：这两个标签混了状态类记忆（版本号、用户玩什么游戏、路线图路径），
// 全常驻会把 15K 字的状态信息塞进每轮上下文。
const CORE_CONSTRAINT_TAGS = ["rule", "rules", "red-line", "safety", "authorization", "preference"];

function isCoreConstraint(m) {
  const tags = m.tags;
  if (!Array.isArray(tags) || tags.length === 0) return false;
  return tags.some((t) => CORE_CONSTRAINT_TAGS.includes(String(t).toLowerCase()));
}

function computeInjection(ordered) {
  // 2026-11-23：硬约束类先摘出来——它们全量注入，不参与下面的位置竞争。
  // 其余（5/5 / 4/5 / 索引段）的算法一个字没改，只是基数从 ordered 换成 nonCore。
  const core = ordered.filter(isCoreConstraint);
  const nonCore = ordered.filter((m) => !isCoreConstraint(m));
  const allFives = nonCore.filter((m) => (m.importance ?? 3) >= 5);
  // 2026-11-18 加：pinned 的 5/5 **永远注入**，不参与 updatedAt 竞争。
  // 为什么需要它：lastUsedAt 全空 → 排序退化成「谁新谁在前」，
  // 「每轮都用但写得很早」的规则会稳定掉出注入段（实测 6 条全在 12 名之外）。
  // pinned 这个字段 4/5 已经在用（isResidentFour 的老记忆豁免），5/5 上复用同一字段、无副作用。
  const pinnedFives = allFives.filter((m) => m.pinned === true);
  const restFives = allFives.filter((m) => m.pinned !== true);
  const room = Math.max(0, MAX_FIVES_INJECT - pinnedFives.length);
  // 2026-11-23 v0.6.20：候选（硬约束 + pinned 5/5 + 竞争位）按长度分档——
  // 短规则（≤400 字）全文；更长的进摘要段（前 150 字 + id），正文按需 memory_search。
  // 实测：90 条硬约束里 61 条 >400 字、占 51,698 字符；另一大头是竞争位那 20 条长文。
  const candidates = [...core, ...pinnedFives, ...restFives.slice(0, room)];
  // 2026-11-24 v0.6.21：短期记忆（horizon:"short"）不管多长、不管重要性都给全文。
  // 为什么从 ordered 里挑而不是 candidates：正在做的事很可能是 4/5（任务待办、临时参数），
  // 而 candidates 只含硬约束 + pinned 5/5 + 竞争位前 20 条——4/5 根本不在里面。
  // 上限 8 条 / 12,000 字符，防止「短期」标记被当成万金油。
  const shortHorizon = [];
  let shortChars = 0;
  for (const m of ordered) {
    if (m.horizon !== "short") continue;
    if (shortHorizon.length >= HORIZON_SHORT_MAX) break;
    const t = fmtInjected(m).length;
    if (shortChars + t > HORIZON_SHORT_CHARS) continue;
    shortHorizon.push(m);
    shortChars += t;
  }
  const shortIds = new Set(shortHorizon.map((m) => m.id));
  const baseFives = candidates.filter((m) => String(m.content || "").length <= SHORT_FULL_MAX);
  const baseIds = new Set(baseFives.map((m) => m.id));
  const fives = [...baseFives, ...shortHorizon.filter((m) => !baseIds.has(m.id))];
  const longEntries = candidates.filter(
    (m) => String(m.content || "").length > SHORT_FULL_MAX && !shortIds.has(m.id),
  );
  // 被条数上限挤下来的 5/5 不能直接丢：它们进索引段（正文按需 memory_search）
  const overflowFives = restFives.slice(room);
  const fours = nonCore.filter((m) => (m.importance ?? 3) === 4);
  // v0.6.16（用户 2026-11-09）：「除去核心必注入的之外，其他的都需要可以检索到」——
  // 索引段不再只覆盖常驻 4/5，而是覆盖**所有非核心**（4/5 + 3/5 + 更低），
  // 让每一条记忆都以「一行标题」的形式出现在提示里，正文按需 memory_search。
  // 短期记忆已给全文，不再进索引段（避免同一内容出现两次）。
  const rest = [
    ...nonCore.filter((m) => (m.importance ?? 3) < 5 && !shortIds.has(m.id)),
    ...overflowFives,
  ];
  const residentFours = fours.filter((m) => isResidentFour(m) && !shortIds.has(m.id));
  const poolFours = fours.filter((m) => !isResidentFour(m) && !shortIds.has(m.id));
  // 3/5 及以下（按设计不注入）的条数：用 id 集合算，避免短期记忆（可能 4/5）被重复计入
  const countedIds = new Set([...fives, ...fours].map((m) => m.id));
  const belowThreshold = ordered.filter((m) => !countedIds.has(m.id)).length;
  const fivesChars = fives.reduce((n, m) => n + fmtInjected(m).length, 0);
  const limit = Math.max(CHAR_BUDGET, fivesChars + FOURS_MIN_ALLOWANCE);
  const shownFours = [];
  const digestFours = [];
  const hiddenByBudget = [];
  let usedChars = fivesChars;
  if (DIGEST_FOURS) {
    // 长条目优先排前面（规则类），再排索引段，读起来是「摘要 → 目录」两段
    for (const m of longEntries) digestFours.push({ m, long: true });
    for (const m of rest) digestFours.push({ m, long: false });
    usedChars += digestFours.reduce(
      (n, d) => n + (d.long ? fmtDigestLong(d.m) : fmtDigest(d.m)).length + 1,
      0,
    );
  } else {
    for (const m of longEntries) digestFours.push({ m, long: true });
    for (const m of residentFours) {
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
  }
  return {
    shown: [...fives, ...shownFours],
    digest: digestFours,
    longCount: longEntries.length,
    report: {
      chars: 0, // 由 renderInjection 在拼完表头/尾行后回填（这才是真正进 prompt 的字符数）
      bodyChars: usedChars, // 被预算约束的"正文"字符数（不含表头/尾行固定开销）
      usedChars,
      limit,
      budget: CHAR_BUDGET,
      fives: { count: fives.length, chars: fivesChars },
      horizon: { short: shortHorizon.length, chars: shortChars },
      longEntries: longEntries.length,
      fours: {
        count: fours.length,
        resident: residentFours.length,
        pool: poolFours.length,
        shown: shownFours.length,
        digest: digestFours.length,
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
      fours: { count: 0, resident: 0, pool: 0, shown: 0, digest: 0, chars: 0, hidden: 0 },
      belowThreshold: 0,
      hiddenIds: [],
    }
  );
}

/** env_doctor 的未确认巡检告警落点：它自己写在插件目录里，我们只读不写。 */
const HEALTH_STATE = join(
  dirname(fileURLToPath(import.meta.url)),
  "..",
  "..",
  "dsh-env-doctor",
  ".guard-alerts.json",
);

/**
 * 巡检告警摘要（2026-11-05 加）。
 *
 * 「巡检 → 告警 → 我处理」原本是断的：告警写在 env_doctor 的状态文件里，只有我
 * 想起来去看才会看见。这行把它接进系统提示——每轮必到，不依赖自觉。
 *
 * 三条约束：
 * ① 只在有告警时出现，正常时**一个字都不加**（否则平白让前缀缓存失效）；
 * ② 标题按 key 排序后取前 3 条，保证告警不变时文本逐字节相同（缓存友好）；
 * ③ `DSH_MEMORY_HEALTH_LINE=0` 可整行关掉，出问题时有退路。
 */
function readHealthLine() {
  if (process.env.DSH_MEMORY_HEALTH_LINE === "0") return { text: "", sig: "" };
  try {
    const raw = JSON.parse(readFileSync(HEALTH_STATE, "utf8"));
    if (!Array.isArray(raw)) return { text: "", sig: "" };
    const alerts = raw
      .filter((a) => a && typeof a.key === "string" && a.key)
      .sort((a, b) => String(a.key).localeCompare(String(b.key)));
    if (alerts.length === 0) return { text: "", sig: "" };
    const titles = alerts.slice(0, 3).map((a) => String(a.title || a.key)).join(" / ");
    const tail = alerts.length > 3 ? ` 等 ${alerts.length} 条` : `（${alerts.length} 条）`;
    return {
      text: `\n[巡检] ${titles}${tail}——跑 env_doctor only=all 看详情；处理后告警会自己消失`,
      sig: `alerts:${alerts.map((a) => a.key).join(",")}`,
    };
  } catch {
    // 文件不在、损坏或还没跑过巡检：当作没有告警，不能让它成为新的故障点
    return { text: "", sig: "" };
  }
}

/**
 * 「开工检查」写进系统提示（2026-11-05 加）。
 *
 * v0.6.2–0.6.5 用 `agent.steer` 推这条提醒，实测**跨轮无效**：steer 只能给正在跑
 * 的这一轮追加内容，轮一结束队列就清。日志铁证——16:29:26 `hint FIRE` 执行了，
 * 16:30:41 下一条用户消息进来时上下文里什么都没有。系统提示是唯一「每轮必到」
 * 的通道，所以改到这里。
 *
 * 缓存代价被压到最小：只在「超过 5 分钟没跑 recall」时出现**一行固定文本**（不带
 * 秒数、不带时间），跑过就消失——一天最多变两次，不是每轮都变。
 * `DSH_MEMORY_RECALL_LINE=0` 可整行关掉。
 */
/** 检索动作统计（2026-11-12 加，「让没查变成看得见的状态」第二版）。
 *
 * 起因：`readRecallLine` 原来只报「没跑」——跑了就返回空串，提示消失。
 * 结果是**跑没跑都看不见**：我看不出「已经查过」和「提示机制没工作」的区别，
 * 于是「查记忆」在我这里没有任何正反馈，只有缺席时才被提醒，而缺席恰恰是我
 * 注意不到的那种状态。这一版把它改成双向：跑了显示次数，没跑显示次数 + 警告。
 *
 * 口径：`.recall.log` 是 `lab recall` / `lab pre` 共用的，所以统计的是**检索动作**
 * 次数，不是某个子命令的调用数——这正是要的（要的不是「pre 跑没跑」，是「记忆有没有被翻」）。
 *
 * 缓存约束：`sig` 必须粗粒度。统计数每次 +1 都会变，若进 sig 就变成每跑一次全量重计费
 * （同 readClockLine 的坑）。所以按 5 次一档取整，且 fresh/stale 切换本身才是主变化。
 */
function recallStats(now = Date.now()) {
  try {
    const lines = readFileSync(HINT_LOG, "utf8").trim().split("\n").filter(Boolean);
    const dayStart = new Date(now);
    dayStart.setHours(0, 0, 0, 0);
    const weekAgo = now - 7 * 86400000;
    let today = 0;
    let week = 0;
    for (const ln of lines) {
      let t = 0;
      try {
        t = Date.parse(JSON.parse(ln).at) || 0;
      } catch {
        continue;
      }
      if (!t) continue;
      if (t >= dayStart.getTime()) today++;
      if (t >= weekAgo) week++;
    }
    return { today, week, total: lines.length };
  } catch {
    return null;
  }
}

// 2026-11-13 缓存稳定性改造（v0.6.17）：判据从「5 分钟内查过=fresh」改成「今天查过没」。
// 根因（本会话实测，acp_cache 账本）：旧 sig=`recall:fresh|stale:floor(week/5)` 在每轮
// fresh/stale 翻转、每 +5 次检索时都变；bucket 里的 week 计数也每轮在涨。sig 一变 =
// 整份 system prompt 重算 = bili 记一次 prompt rewrite（~57K 字符重计费）。
// 本会话窗口内 prompt switch 15 次 / 848.2K tok，是 miss 的最大单一来源。
// 改天级后每天最多翻 2 次（跨零点 + 当天第一次检索）。文本里也不再放「今日 N 次」
// 这种每轮涨的数字——文本必须和 sig 一样稳。
function readRecallLine(now = Date.now()) {
  if (process.env.DSH_MEMORY_RECALL_LINE === "0") return { text: "", sig: "" };
  const last = lastRecallAt();
  const dayStart = new Date(now);
  dayStart.setHours(0, 0, 0, 0);
  const ranToday = Boolean(last) && last >= dayStart.getTime();
  const dayKey = dayStamp(now);
  if (ranToday) {
    return {
      text: `\n〔开工检查〕✓ 今天已跑过记忆检索。有**新任务**再跑 \`lab pre\`；同一件事别重复跑。`,
      sig: `recall:${dayKey}:ran`,
    };
  }
  return {
    text: `\n〔开工检查〕✗ 今天还没跑 lab pre。开工第一步是 \`lab pre "<用户原话>"\`——会自动提词、扫一遍记忆库（零命中退出码 1 是「确实没有」，不是错误）。**做任何任务都必须先跑 lab pre**（它已经把 recall + tier + selfcheck 合成一条，0.3 秒）——⚠️ 它不是参考资料，是**你本身能力的具象化**：候选路线就是你现在会做的事的全部，是你思考的起手式。**它里面没有的，就是你缺的能力**——先补（加一条路线），再动手，别绕过。拿到路线后横向比、**别跳进第一条**：一个任务通常是跨几个域挑几条路线排顺序配合出来的，动笔前写一行「选 A+B 因为…；不选 C 因为…；A 的结论让 D 不用做」——只写「选 A」是错的，它默认这题只有一个答案（判法 准 > 稳 > 快）；卡住时也回来跑它。查完在开场写一行 \`记忆命中：N 条\`。`,
    sig: `recall:${dayKey}:none`,
  };
}

/** 工具提示（2026-11-05 加）：把「这轮该用哪个 lab 工具」从我的记忆变成环境判断。
 *
 *  背景：用户要求「要用的时候随时记得用」。实测过——`lab recall` 是唯一真闭环，
 *  因为它走系统提示这条每轮必到的通道；其他工具仍靠"我记得"，而"记得"靠不住。
 *  所以这里复制同一招：用户消息进来时按关键词匹配，写进 .tool-hint.json；
 *  renderInjection 读它并推一行。
 *
 *  取舍：宁可漏，不要乱推。误报的代价是多一行字，漏报的代价是忘了用工具。
 *  只匹配明确信号（TOOL_RULES），不猜语义。
 */
const TOOL_HINT_FILE = join(DSH_HOME, "memory", ".tool-hint.json");

// 2026-11-13 缓存稳定性改造（v0.6.17）：工具提示从「15 分钟 TTL、每条消息重写（未命中清空）」
// 改成「当日累积、并集、不清空、跨天才失效」。
// 根因同 readRecallLine：旧版每条用户消息都重写 .tool-hint.json，换话题 → tools 集合变 →
// tool.sig 变 → 整份 system prompt 重算 → 一次 prompt rewrite。TTL 到点提示行消失也是同样一击。
// 新语义：一天内 tools 只增不减（并集），文本与 sig 只在「今天第一次出现新工具名」时变一次。
// 代价：提示最长滞后到当天有效（不是「这条消息」而是「今天的工作」），可接受——提词本来就
// 不要求逐条精准。dayStamp 是共用的天级时间戳（sig 用它，不用秒级值）。
function dayStamp(now = Date.now()) {
  const d = new Date(now);
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}
function isSameDay(a, b) {
  if (!a) return false;
  return dayStamp(a) === dayStamp(b);
}

const TOOL_RULES = [
  // 用户纠正我时立刻记——「我错了但没留痕」的高发场景（2026-11-05 加）
  [/(不是这样|不是这个意思|你搞错|我说的是|不是让你|应该(是|用)|谁让你|别再|不要这样)/, "lab correction", "用户纠正的就记下来，别让同一条错第二次"],
  [/(图标|桌面|鼠标|点击|双击|右键菜单|快捷键)/, "lab desktop", "桌面鼠标键盘，默认 dry-run 加 --yes 才动"],
  [/(网页|浏览器|标签页|DOM|页面元素|自动填|自动点)/, "lab cdp", "CDP 直接操作已开的浏览器"],
  [/(发布|推送|发版|推仓库|stage|commit)/, "lab stage + lab commit", "发布前扫描 + 提交"],
  [/(装插件|安装插件|插件.*装|装.*插件|第三方插件|插件市场)/, "lab vet", "装之前先扫它联网/读写什么"],
  [/(记忆|召回|以前说过|之前定过|长期记忆)/, "lab recall", "开工第一步自动提词检索"],
  [/(会话|对话记录|上次聊|历史对话|那天说)/, "lab sessions", "按关键词/时间找会话"],
  [/(计划任务|定时|每天跑|schtasks)/, "lab tasks", "列任务 + 结果码翻人话"],
  [/(插件.*(没生效|不生效|坏了)|环境.*(异常|坏了)|沙箱)/, "env_doctor", "巡检 + 插件健康"],
  [/(改插件|同步.*profile|deploy)/, "lab deploy", "源码同步到 profile"],
  [/(花了多少|成本|token|花费)/, "lab cost", "这一轮/官方真数"],
  // 动 profile 配置前先备份（2026-11-05 加）
  [/(改.*配置|改.*profile|package\.json|cordis\.patch|插件配置)/, "lab config", "动 profile 配置前先备份"],
  // ── 第二批（2026-11-05 晚，12→21）：只补「高频场景 + 当时零调用」的组合，
  //    账本里记着这些工具建了但一次没用过。仍然守「宁可漏不要乱推」。
  [/(做完了|完成了|搞定了|都做完了|收尾)/, "lab claims", "说「做完了」之前先对一次证据"],
  [/(几个|多少个|涨了|降了|快了|慢了|准确率|通过率|占比)/, "lab fact", "说数字前先验出处"],
  [/(乱码|编码|GBK|BOM|utf-?8.*乱)/, "lab encoding", "乱码先怀疑读法，不是文件坏"],
  [/(报错|错误|失败了|挂了|traceback|异常退出)/, "lab errors", "先查这形状见过没，再动手救"],
  [/(读.*(陌生|别人).*代码|这项目.*怎么跑|看不懂.*源码|先摸一下底)/, "lab lsp", "读陌生代码用 LSP 找定义/引用"],
  [/(截图|图里的字|图片.*文字|识别.*字|OCR)/, "lab ocr", "图里抠字，本地免费 0.6s"],
  [/(长会话|轮数|上下文.*长|多轮|超窗)/, "lab session-age", "成本随轮数平方，先看年龄"],
  [/(CI|工作流|github actions|构建失败|检查没绿)/, "lab ci", "看 CI 为什么红"],
  [/(机制.*(过期|漂移|对不上)|改.*(SKILL|机制文档))/ , "lab selfcheck", "改完机制验 0 漂移"],
];

function writeToolHint(text, now = Date.now()) {
  try {
    const hits = [];
    for (const [re, tool, why] of TOOL_RULES) {
      if (re.test(text)) hits.push({ tool, why });
      if (hits.length >= 3) break;
    }
    let tools = [];
    try {
      const j = JSON.parse(readFileSync(TOOL_HINT_FILE, "utf8"));
      if (j && Array.isArray(j.tools) && isSameDay(j.at, now)) tools = j.tools;
    } catch {
      /* 文件不存在/坏掉 = 从空开始 */
    }
    let changed = false;
    for (const h of hits) {
      if (!tools.some((t) => t.tool === h.tool)) {
        tools.push(h);
        changed = true;
      }
    }
    // 没新工具名就不重写文件——重写会刷新 at，虽不再影响 text/sig（它们只看
    // dayStamp+tools 集合），但少写一次盘少一次抖动面。跨天的旧 tools 不继承：
    // 上面 isSameDay 判 false 时从空数组开始，第一次命中会把它替换掉。
    if (!changed) return;
    writeFileSync(TOOL_HINT_FILE, JSON.stringify({ at: now, tools }), "utf8");
  } catch {
    /* 提示失败不影响对话 */
  }
}

/** 〔时间〕行：每轮都给一个本地时间锚点。
 *
 * 2026-11-09 用户 m17083 要的「时间闸」：「每次回答时间之类的问题的时候，
 * 必须看一眼本地时间与上一轮对话的时间」。
 *
 * 为什么不能只靠 identity.md 那条禁词规则：它是「读到就想起」，不是「不读就
 * 过不去」；而聊天输出没有 pre-execute 钩子，dsh-self-guard 拦不了我敲的字。
 * 唯一能保证「每轮都在我眼前」的位置就是系统提示——所以时间行放这里。
 *
 * 注意：**不参与 injectionSignature**（否则每分钟缓存失效一次，前缀缓存
 * 全废）。它由 renderInjection 在缓存之外现拼，所以永远是最新的。
 */
function readClockLine(now = Date.now()) {
  if (process.env.DSH_MEMORY_CLOCK_LINE === "0") return { text: "" };
  const d = new Date(now);
  const p = (n) => String(n).padStart(2, "0");
  const wd = "日一二三四五六"[d.getDay()];
  // 2026-11-11：精度从「分钟」降到「天」。
  // 根因：这段文本拼在 injectionCache 外面（见 renderInjection 里的 `injectionCache.text + clock.text`），
  // 每次组装 system prompt 都会重算 → 每分钟变一次 → bili 的 prompt fingerprint 每分钟变一次 →
  // 每个跨分钟边界的请求都记一次 prompt rewrite（实测 27 次 / 4.18M tok，占全部 miss 的 44%，
  // 是最大单一来源，比压缩还大）。降到天级后每天只变一次。
  // 精确到分钟的时间不靠这里：每轮环境里有 "Time sampled … +08:00"，`lab now` 也能现查。
  return {
    text:
      `\n〔日期〕今天 ${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}（周${wd}）。` +
      `说任何时间词（刚才 / 上一轮 / 多久前）之前，先用它和系统提示里的 "Time sampled … +08:00" 对一次；` +
      `算间隔跑 lab now --since <上一轮 ISO>。` +
      `**禁用「昨天 / 前天 / 上周 / 上个月 / 几个月」**，除非当场能指出日期出处——` +
      `2026-11-09 我把 11 分钟前说成"昨天"，就是没对过这一眼。`,
  };
}

function readToolHintLine(now = Date.now()) {
  if (process.env.DSH_MEMORY_TOOL_HINT === "0") return { text: "", sig: "" };
  try {
    const j = JSON.parse(readFileSync(TOOL_HINT_FILE, "utf8"));
    if (!j || !Array.isArray(j.tools) || j.tools.length === 0) return { text: "", sig: "" };
    if (!isSameDay(j.at, now)) return { text: "", sig: "" }; // 当日有效；过期只当空，不改文件
    const sorted = [...j.tools].sort((a, b) => String(a.tool).localeCompare(String(b.tool)));
    const list = sorted.map((t) => `${t.tool}（${t.why}）`).join("；");
    return {
      text: `\n〔工具提示〕今天的工作可能用得上：${list}。不是命令，判断不对就别用。`,
      sig: `tools:${dayStamp(now)}:` + sorted.map((t) => t.tool).join(","),
    };
  } catch {
    return { text: "", sig: "" };
  }
}

// 读身份锚点。和用户档案同一套语义：缺失/空返回空 text，不影响注入；sig 用 mtime+长度。
function readIdentity() {
  try {
    const st = statSync(IDENTITY);
    let body = readFileSync(IDENTITY, "utf8").trim();
    if (!body) return { text: "", sig: "empty" };
    if (body.length > IDENTITY_MAX) {
      body = body.slice(0, IDENTITY_MAX) + "\\n…（身份文件过长已截断，完整内容见 " + IDENTITY + "）";
    }
    return {
      text: "\\n\\n" + body,
      sig: `${Math.round(st.mtimeMs)}:${st.size}`,
    };
  } catch {
    return { text: "", sig: "absent" };
  }
}

// 读用户档案。返回 {text, sig}；文件不存在或为空时 text=""（不影响注入）。
// sig 用 mtime+长度，只有文件真变了才让注入缓存失效。
function readUserProfile() {
  try {
    const st = statSync(USER_PROFILE);
    let body = readFileSync(USER_PROFILE, "utf8").trim();
    if (!body) return { text: "", sig: "empty" };
    if (body.length > USER_PROFILE_MAX) {
      body = body.slice(0, USER_PROFILE_MAX) + "\n…（档案过长已截断，完整内容见 " + USER_PROFILE + "）";
    }
    return {
      text: "\n\n## 用户档案（关于用户本人的事，每次会话必读）\n\n" + body,
      sig: `${Math.round(st.mtimeMs)}:${st.size}`,
    };
  } catch {
    return { text: "", sig: "absent" };
  }
}

// 读资产地图。和用户档案同一套语义：缺失/空返回空 text，不影响注入；sig 用 mtime+长度。
function readAssetMap() {
  try {
    const st = statSync(ASSET_MAP);
    let body = readFileSync(ASSET_MAP, "utf8").trim();
    if (!body) return { text: "", sig: "empty" };
    if (body.length > ASSET_MAP_MAX) {
      body = body.slice(0, ASSET_MAP_MAX) + "\n…（资产地图过长已截断，完整内容见 " + ASSET_MAP + "）";
    }
    return {
      text: "\n\n" + body,
      sig: `${Math.round(st.mtimeMs)}:${st.size}`,
    };
  } catch {
    return { text: "", sig: "absent" };
  }
}

function renderInjection() {
  const db = loadDb();
  applyDecay(db);
  const identity = readIdentity();
  const user = readUserProfile();
  const assets = readAssetMap();
  const health = readHealthLine();
  const recall = readRecallLine();
  const tool = readToolHintLine();
  // 时钟行走缓存外面（见 readClockLine 注释），三处 return 都要带上
  const clock = readClockLine();
  if (db.memories.length === 0) {
    injectionCache = null;
    return (
      identity.text +
      user.text +
      assets.text +
      "## 长期记忆（跨会话）\n（记忆库为空：可以用 memory_save 记录值得跨会话保留的信息）" +
      health.text +
      recall.text +
      tool.text +
      clock.text
    );
  }
  const signature = injectionSignature(db.memories) + "|" + health.sig + "|" + recall.sig + "|" + tool.sig + "|" + user.sig + "|" + assets.sig + "|" + identity.sig;
  if (injectionCache && injectionCache.signature === signature) return injectionCache.text + clock.text;
  // 已废弃（被新结论取代）的记忆不再注入，避免"旧方案和新方案并存"导致自相矛盾
  const active = db.memories.filter((m) => !m.deprecated);
  const ordered = sortMemories(active);
  const { shown, digest, report } = computeInjection(ordered);
  const longItems = digest.filter((d) => d.long);
  const indexItems = digest.filter((d) => !d.long);
  const lines = ["## 长期记忆（跨会话，来自记忆库）", ""];
  for (const m of shown) lines.push(fmtInjected(m));
  if (longItems.length > 0) {
    lines.push(
      "",
      `### 长条目摘要（${longItems.length} 条，每条只给前 ${LONG_DIGEST_CHARS} 字——规则名和第一条判据都在；分级、例外、历史按需 memory_search 取全文）`,
    );
    for (const d of longItems) lines.push(fmtDigestLong(d.m));
  }
  if (indexItems.length > 0) {
    lines.push(
      "",
      `### 其余记忆索引（${indexItems.length} 条，一行一条——正文不在提示里，要用时 memory_search "<关键词>" 或 lab recall "<任务原话>" 取全文）`,
    );
    for (const d of indexItems) lines.push(fmtDigest(d.m));
  }
  const midCount = indexItems.filter((d) => (d.m.importance ?? 3) === 4).length;
  const lowCount = indexItems.length - midCount;
  const notes = [
    report.horizon.short > 0
      ? `全文注入 ${shown.length} 条（≤${SHORT_FULL_MAX} 字的短规则 + ${report.horizon.short} 条短期记忆 horizon=short）`
      : `全文注入 ${shown.length} 条（≤${SHORT_FULL_MAX} 字的短规则）`,
    `另有 ${longItems.length} 条长条目只给前 ${LONG_DIGEST_CHARS} 字摘要`,
    `其余 ${indexItems.length} 条给一行索引（4/5 ${midCount} 条 + 3/5 及以下 ${lowCount} 条，正文一律按需检索）`,
  ];
  if (report.fours.hidden > 0) {
    notes.push(
      `另有 ${report.fours.hidden} 条因超准入上限（${report.limit} 字符）整条缺席：${report.hiddenIds.slice(0, 10).join(", ")}${report.hiddenIds.length > 10 ? " …" : ""}`,
    );
  }
  lines.push("", `（以上记忆会在每次会话自动加载：${notes.join("；")}；需要时用 memory_search 检索全文）`);
  const text = identity.text + user.text + assets.text + lines.join("\n") + health.text + recall.text + tool.text;
  report.chars = text.length; // 从 "## 长期记忆" 到最后一个字符，就是真正注入 prompt 的长度
  injectionCache = { signature, text, report };
  return text + clock.text;
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

/* ------------------------------------------------------------------ */
/* v0.6.1：与当前任务相关的记忆自动浮出                                    */
/* ------------------------------------------------------------------ */

/** 自动浮出的 2-gram 命中门槛。ngramRecall 用 2 是"兜底召回"的松标准，
 *  但那是给"用户主动搜"用的（搜不到才用兜底）；自动推送没人要求，
 *  太松就等于每句话都弹一堆记忆 → 我会习惯性无视 → 比不推更坏。
 *  6 是实测值：能滤掉"我/的/了/这个/那个"凑出来的假命中。 */
const RECALL_MIN_GRAM_HITS = 6;
const RECALL_MAX_ITEMS = 2;
/** 同一会话里两条自动浮出之间至少隔这么久，防连续对话时刷屏。 */
const RECALL_COOLDOWN_MS = 10 * 60 * 1000;

/** agentId → { at: 上次推送时间戳, ids: Set<memoryId>（本会话已推过的） } */
const recallState = new Map();

/** 从 session/event 的 data 里取用户消息的纯文本。 */
function userTextOf(data) {
  const c = data?.content ?? data?.message?.content;
  if (typeof c === "string") return c;
  if (Array.isArray(c)) {
    return c
      .filter((x) => x && x.type === "text" && typeof x.text === "string")
      .map((x) => x.text)
      .join(" ");
  }
  if (typeof data?.text === "string") return data.text;
  return "";
}

/** 挑出该在这时候浮出来的记忆；已在注入里的、本会话推过的、deprecated 的都排除。 */
function recallPick(db, userText, excludeIds) {
  const qg = queryGrams(userText);
  // 太短的消息（"好""继续""嗯"）不查——没有检索价值，只会浪费分数
  if (qg.size < 4) return [];
  const scored = [];
  for (const m of db.memories) {
    if (m.deprecated === true) continue;
    if (excludeIds.has(m.id)) continue;
    const tg = queryGrams(`${m.content} ${(m.tags || []).join(" ")}`);
    let hit = 0;
    for (const g of qg) if (tg.has(g)) hit += 1;
    if (hit >= RECALL_MIN_GRAM_HITS) scored.push({ m, hit });
  }
  scored.sort((a, b) => {
    if (b.hit !== a.hit) return b.hit - a.hit;
    return (b.m.importance ?? 3) - (a.m.importance ?? 3);
  });
  return scored.slice(0, RECALL_MAX_ITEMS);
}

/** 拼成推给模型看的那一小段。要短：这不是正文，是"提示你去搜"。 */
function buildRecallNotice(hits) {
  const lines = hits.map(({ m }) => {
    const body = String(m.content || "").replace(/\s+/g, " ").trim();
    const brief = body.length > 110 ? body.slice(0, 110) + "…" : body;
    return `- ${m.id}｜${brief}`;
  });
  return [
    "〔记忆库自动浮出〕下面这几条跟你刚才说的相关，不在常规注入里：",
    ...lines,
    `要看全文：memory_search "<关键词>"；不相关就无视它（这只是一次提示）。`,
  ].join("\n");
}

/** 2026-11-05：开工检查——这轮还没跑 lab recall 就提醒一次。
 *  起因：用户说「提词 → 搜 → 贴账太笼统，不够有保障」，要一个"我不记得也会被提醒"的机制。
 *  `lab recall` 每次调用都往 `.recall.log` 追加一行，所以"最后一行的 at"就是
 *  "上次真的查过"的客观证据——不是靠我自称搜过。 */
const RECALL_STALE_MS = 5 * 60 * 1000; // 距上次 recall 超过 5 分钟 = 这轮还没查
const HINT_COOLDOWN_MS = 10 * 60 * 1000; // 同一会话两次提醒至少隔 10 分钟，防刷屏
const HINT_LOG = join(DSH_HOME, "memory", ".recall.log");
/**
 * 诊断日志（2026-11-05 加）：开工检查第一次上线时"该响却没响，且查不出为什么"——
 * 它不像 fail-guard 那样自带 log，而触发条件全在暗处（agent.steer 在不在、
 * session/event 到不到、文本长度够不够、上次 recall 隔了多久）。写一份到文件里，
 * 写不进去也绝不影响对话——诊断永远不能成为新的故障点。
 */
const HINT_TRACE = join(DSH_HOME, "memory", ".memory-hint.log");
function hlog(msg) {
  try {
    appendFileSync(HINT_TRACE, `${new Date().toISOString()} ${msg}\n`);
  } catch {
    /* 诊断日志失败不影响任何事 */
  }
}
/** agentId → 上次提醒时间戳 */
const hintState = new Map();

function lastRecallAt() {
  try {
    const lines = readFileSync(HINT_LOG, "utf8").trim().split("\n").filter(Boolean);
    if (lines.length === 0) return 0;
    const row = JSON.parse(lines[lines.length - 1]);
    return Date.parse(row.at) || 0;
  } catch {
    return 0; // 没跑过 / 读不了，都按"没查过"处理
  }
}

/**
 * steer 只接受 UserMessage（`{ content: [...], source: { kind } }`）。
 * 2026-11-05 事故：v0.6.6 直接把字符串传给 steer，DSH 的 `inbox.splice` 会把它
 * 原样塞进 `inserted` 数组——日志里就成了 `inserted: ["..."]`，下一次 resume 撞
 * `SessionFormatError: agent/inbox/spliced requires message objects`，**整个会话
 * 打不开**。18 个会话中招。提醒是增强功能，写不进去也绝不能影响对话。
 */
function steerText(agent, text) {
  try {
    agent.steer({ content: [{ type: "text", text }], source: { kind: "dsh-memory" } });
  } catch (e) {
    console.warn("[dsh-memory] steer 失败（不影响对话）: " + (e?.message || e));
  }
}

function maybeHintRecall(agent, agentId, now) {
  const last = lastRecallAt();
  const ago = last ? Math.round((now - last) / 1000) : -1;
  if (last && now - last < RECALL_STALE_MS) {
    hlog(`hint skip: 上次 recall ${ago}s 前（<300s）`);
    return; // 刚查过，不打扰
  }
  const prev = hintState.get(agentId) || 0;
  if (now - prev < HINT_COOLDOWN_MS) {
    hlog(`hint skip: 冷却中，上次提醒 ${Math.round((now - prev) / 1000)}s 前`);
    return;
  }
  hintState.set(agentId, now);
  hlog(
    `hint FIRE agent=${agentId} 上次 recall=${ago === -1 ? "从未" : ago + "s 前"}` +
      "（只记日志：提醒已由系统提示 readRecallLine 负责，steer 这条路 v0.6.7 起停用）"
  );
  // v0.6.7：这里原本调 agent.steer(字符串)，是 2026-11-05「18 个会话打不开」的根因。
  // v0.6.6 已把提醒改走系统提示（renderInjection→readRecallLine），但忘了删这条旧调用，
  // 两条路并存 → 系统提示正常、steer 却把裸字符串写进 inbox。现在彻底停用。
}

/** 给一个 agent 挂"用户发消息就查一次记忆"的监听。 */
function attachRecall(ctx, agent) {
  if (!agent?.ctx || typeof agent.ctx.on !== "function") {
    hlog(`attach SKIP agent=${agent?.id}: 没有 ctx.on`);
    return;
  }
  if (typeof agent.steer !== "function") {
    hlog(`attach SKIP agent=${agent?.id}: 没有 steer`);
    return;
  }
  const agentId = String(agent.id || "unknown");
  hlog(`attach OK agent=${agentId}`);
  agent.ctx.on("session/event", (session, event) => {
    try {
      if (event?.type === "assistant/message") {
        // 2026-11-05 修时机：在 user/message 里 steer 太晚——那条消息进来时当轮
        // 已经组装完毕，推的东西要等下一轮才被消费（实测：hint FIRE 了，但当轮
        // 上下文里看不到任何提醒）。改在"我这一轮说完"之后预置，下一轮用户开口
        // 时提醒已经在上下文里。maybeHintRecall 自带 10 分钟冷却，不会刷屏。
        maybeHintRecall(agent, agentId, Date.now());
        return;
      }
      if (event?.type !== "user/message") return;
      const text = userTextOf(event?.data);
      hlog(`event user/message len=${text.length}`);
      if (!text) return;
      // 工具提示：短消息也要匹配（"修图标"只有三个字），所以放在长度门槛之前。
      writeToolHint(text, Date.now());
      if (text.length < 8) return;

      const st = recallState.get(agentId) || { at: 0, ids: new Set() };
      recallState.set(agentId, st);
      const now = Date.now();

      // 自动浮出：只在冷却过后查一次（原有逻辑，v0.6.1）
      if (now - st.at >= RECALL_COOLDOWN_MS) {
        const db = loadDb();
        // 排除已经在常规注入里的（5/5 全注入 + 有常驻资格的 4/5），
        // 否则会推"我本来就能看到的东西"，那是噪音不是帮助。
        const exclude = new Set();
        for (const m of computeInjection(sortMemories(db.memories)).shown) exclude.add(m.id);
        for (const id of st.ids) exclude.add(id);

        const hits = recallPick(db, text, exclude);
        if (hits.length > 0) {
          st.at = now;
          for (const { m } of hits) st.ids.add(m.id);
          steerText(agent, buildRecallNotice(hits));
        }
      }
      // 开工检查已挪到上面的 assistant/message 分支（在用户消息里推太晚）
    } catch (e) {
      // 自动浮出是增强，失败绝不能影响对话
      console.warn("[dsh-memory] 自动浮出失败（不影响对话）: " + (e?.message || e));
    }
  });

  // 会话刚创建、用户还没开口时先查一次：这时 steer 的东西能赶上**第一条**消息。
  // 在 user/message 事件里 steer 太晚（当轮已组装完毕，见 v0.6.3 的日志实证），
  // assistant/message 是"预置下一轮"的兜底，这里才是能让第一条就看到的时机。
  // maybeHintRecall 自带冷却，重复调用不会刷屏。
  maybeHintRecall(agent, agentId, Date.now());
}

/** 仅供 iterate/ 下的测试脚本用；插件运行时不会读它。 */
export const __test = { queryGrams, recallPick, buildRecallNotice, userTextOf, lastRecallAt, maybeHintRecall, readHealthLine, readRecallLine, readToolHintLine, writeToolHint, renderInjection };

export function apply(ctx) {
  const systemPrompt = ctx.get("systemPrompt");
  if (systemPrompt !== undefined) {
    systemPrompt.section({
      name: "dsh-memory",
      order: 8,
      text: () => renderInjection(),
    });
  }

  // v0.6.1：用户发来消息时，把"跟这段相关、但不在常规注入里"的记忆推一条提示。
  // 为什么挂在 agent.ctx 而不是根 ctx：session/event 是在 agent 自己的 ctx 上发出的
  // （跟 dsh-fail-guard 同一个结论——根 ctx 收到的是冒泡副本，会造成重复）。
  const mountedAgents = new Set();
  const attachOnce = (agent) => {
    const id = String(agent?.id || "");
    hlog(`attachOnce id=${id || "(空)"} seen=${mountedAgents.has(id)}`);
    if (!id || mountedAgents.has(id)) return;
    mountedAgents.add(id);
    attachRecall(ctx, agent);
  };
  try {
    ctx.on("agent/created", (payload) => {
      hlog(`agent/created payloadKeys=${Object.keys(payload || {}).join(",")}`);
      attachOnce(payload?.agent ?? payload);
    });
    hlog("apply: 已挂 agent/created");
  } catch (e) {
    hlog("apply: 挂 agent/created 失败: " + (e?.message || e));
    console.warn("[dsh-memory] 挂 agent/created 失败: " + (e?.message || e));
  }
  try {
    const list = ctx.agents?.list?.();
    hlog(`apply: 现存 agent 数=${Array.isArray(list) ? list.length : "不可用"}`);
    if (Array.isArray(list)) for (const a of list) attachOnce(a);
  } catch (e) {
    hlog("apply: 枚举现存 agent 失败: " + (e?.message || e));
    console.warn("[dsh-memory] 枚举现存 agent 失败: " + (e?.message || e));
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
        horizon: { type: "string", enum: ["short", "long"], description: "可选：时效。short = 这几天正在做的事，不管多长都全文注入、不占 5/5 竞争位（上限 8 条 / 12,000 字符），任务做完记得改回 long；不填 = long（默认，长条目只给前 150 字摘要）。" },
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
        // v0.6.21：短期记忆（正在做的任务）给全文注入；不填 = long，不带这个字段以免污染存量格式
        ...(args?.horizon === "short" ? { horizon: "short" } : {}),
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
        (rep.fours.digest > 0 ? `4/5 ${rep.fours.digest} 条只给索引（正文按需检索）` : `4/5 注入 ${rep.fours.shown}/${rep.fours.count} 条`) +
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
      // 命中即记录最近使用时间（用于注入排序）+ 累加命中次数（用于动态分层判定）
      const now = nowIso();
      for (const m of hits) {
        m.lastUsedAt = now;
        m.hits = Number(m.hits || 0) + 1;
        m.lastHitAt = now;
      }
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
        horizon: { type: "string", enum: ["short", "long"], description: "可选：改时效。short = 正在做的事，全文注入；long = 默认（长条目给摘要）。任务做完记得改回 long。" },
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
      // v0.6.21：horizon 可改回 long（任务做完撤销短期标记时用）
      if (args?.horizon === "short") memory.horizon = "short";
      else if (args?.horizon === "long") delete memory.horizon;
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
