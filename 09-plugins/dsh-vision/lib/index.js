// 大肥鱼本地识图插件：双引擎（智谱 GLM-4V API 优先 + Ollama Qwen2.5-VL 本地兜底）
// 提供 vision_describe 工具：看图描述 / 提取文字 / 回答问题
import { readFileSync, existsSync, statSync, writeFileSync, mkdirSync, renameSync, unlinkSync } from "node:fs";
import { basename, join } from "node:path";
import { homedir } from "node:os";
import { spawn } from "node:child_process";
import { createHash } from "node:crypto";

export const name = "dsh-vision";
export const inject = ["tools"];

const DSH_HOME = process.env.DSH_HOME || join(homedir(), ".dsh");
const KEY_FILE = join(DSH_HOME, "dsh-vision-key.txt");
const OLLAMA_URL = process.env.DSH_VISION_OLLAMA_URL || "http://127.0.0.1:11434";
const OLLAMA_MODEL = process.env.DSH_VISION_MODEL || "qwen2.5vl:3b";
const OLLAMA_EXE =
  process.env.DSH_VISION_OLLAMA_EXE ||
  join(process.env.LOCALAPPDATA || join(homedir(), "AppData", "Local"), "Programs", "Ollama", "ollama.exe");
const ZHIPU_URL = "https://open.bigmodel.cn/api/paas/v4/chat/completions";
const ZHIPU_MODEL = process.env.DSH_VISION_ZHIPU_MODEL || "glm-4v-flash";
const IMAGE_EXTS = new Set([".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tiff", ".tif"]);

// ── 视觉结果缓存（2026-11-02）──────────────────────────────────────────────
// 同一张图 + 同一个问题重复调用智谱 API 是按次付费的浪费。用「图片内容 sha256 +
// question + mode」做 key，把成功结果落到本地，默认复用 7 天；图片内容变了 key 就变，
// 不会拿旧图的结果冒充新图。可用 DSH_VISION_CACHE=off 整体关闭。
const CACHE_FILE = join(DSH_HOME, "dsh-vision-cache.json");
const CACHE_OFF = ["0", "off", "false", "no"].includes(String(process.env.DSH_VISION_CACHE || "").toLowerCase());
const CACHE_TTL_MS = (() => {
  const h = Number(process.env.DSH_VISION_CACHE_TTL_H || 0);
  return Number.isFinite(h) && h > 0 ? h * 3600000 : 7 * 86400000;
})();
const CACHE_MAX = (() => {
  const n = Number(process.env.DSH_VISION_CACHE_MAX || 0);
  return Number.isFinite(n) && n > 0 ? Math.floor(n) : 100;
})();

function cacheKey(path, question, mode) {
  const imageHash = createHash("sha256").update(readFileSync(path)).digest("hex");
  return createHash("sha256")
    .update(imageHash)
    .update("\0")
    .update(String(mode || "auto"))
    .update("\0")
    .update(String(question || ""))
    .digest("hex");
}

function loadCache() {
  try {
    const db = JSON.parse(readFileSync(CACHE_FILE, "utf8"));
    if (db && db.entries && typeof db.entries === "object") return db;
  } catch { /* 文件不存在或损坏：按空缓存处理，下次成功调用会重建 */ }
  return { version: 1, entries: {} };
}

function saveCache(db) {
  try {
    mkdirSync(DSH_HOME, { recursive: true });
    const tmp = CACHE_FILE + ".tmp-" + process.pid;
    writeFileSync(tmp, JSON.stringify(db, null, 2) + "\n", "utf8");
    try {
      renameSync(tmp, CACHE_FILE);
    } catch {
      // 个别 Windows 环境 rename 覆盖失败：退化为直接写 + 清理临时文件
      writeFileSync(CACHE_FILE, JSON.stringify(db, null, 2) + "\n", "utf8");
      try { unlinkSync(tmp); } catch { /* ignore */ }
    }
  } catch { /* 缓存写失败不影响识图主流程 */ }
}

function getCache(key) {
  if (CACHE_OFF) return null;
  const db = loadCache();
  const entry = db.entries[key];
  if (!entry) return null;
  if (!(Number(entry.at) > 0) || Date.now() - Number(entry.at) > CACHE_TTL_MS) {
    delete db.entries[key];
    saveCache(db);
    return null;
  }
  return entry;
}

function putCache(key, text, engine, path) {
  if (CACHE_OFF) return;
  const db = loadCache();
  const now = Date.now();
  db.entries[key] = { text, engine, at: now, file: basename(path), chars: String(text || "").length };
  // 过期项先清，再按最久未用淘汰，避免缓存文件无限长
  for (const [k, v] of Object.entries(db.entries)) {
    if (!(Number(v?.at) > 0) || now - Number(v.at) > CACHE_TTL_MS) delete db.entries[k];
  }
  const keys = Object.keys(db.entries);
  if (keys.length > CACHE_MAX) {
    keys.sort((a, b) => Number(db.entries[a]?.at || 0) - Number(db.entries[b]?.at || 0));
    for (const k of keys.slice(0, keys.length - CACHE_MAX)) delete db.entries[k];
  }
  saveCache(db);
}

function textOutput() {
  return {
    schema: { type: "string" },
    render: (_args, value) => [{ type: "text", text: String(value) }],
  };
}

function mimeOf(path) {
  const ext = path.slice(path.lastIndexOf(".")).toLowerCase();
  if (ext === ".jpg" || ext === ".jpeg") return "image/jpeg";
  if (ext === ".webp") return "image/webp";
  if (ext === ".gif") return "image/gif";
  if (ext === ".bmp") return "image/bmp";
  if (ext === ".tif" || ext === ".tiff") return "image/tiff";
  return "image/png";
}

function readZhipuKey() {
  // 优先环境变量（符合大多数人的习惯），其次读 ~/.dsh/dsh-vision-key.txt 一行。
  const fromEnv = String(process.env.ZHIPU_API_KEY || "").trim();
  if (fromEnv) return fromEnv;
  try {
    return readFileSync(KEY_FILE, "utf8").trim();
  } catch {
    return "";
  }
}

function validateImage(path) {
  if (!path) throw new Error("缺少 path 参数");
  if (!existsSync(path)) throw new Error(`图片不存在: ${path}`);
  const size = statSync(path).size;
  if (size > 40 * 1024 * 1024) throw new Error(`图片太大（${(size / 1024 / 1024).toFixed(1)}MB），请先压缩`);
  const ext = path.slice(path.lastIndexOf(".")).toLowerCase();
  if (!IMAGE_EXTS.has(ext)) throw new Error(`不支持的图片格式: ${ext}`);
  return size;
}

async function callZhipu(path, question) {
  const key = readZhipuKey();
  if (!key) throw new Error("智谱 key 未配置（~/.dsh/dsh-vision-key.txt）");
  const b64 = readFileSync(path).toString("base64");
  const mime = mimeOf(path);
  const res = await fetch(ZHIPU_URL, {
    method: "POST",
    headers: { Authorization: `Bearer ${key}`, "Content-Type": "application/json" },
    body: JSON.stringify({
      model: ZHIPU_MODEL,
      messages: [
        {
          role: "user",
          content: [
            { type: "text", text: question },
            { type: "image_url", image_url: { url: `data:${mime};base64,${b64}` } },
          ],
        },
      ],
    }),
    signal: AbortSignal.timeout(90000),
  });
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`智谱 API HTTP ${res.status}: ${body.slice(0, 300)}`);
  }
  const data = await res.json();
  const content = data?.choices?.[0]?.message?.content;
  if (!content) throw new Error("智谱 API 返回空内容");
  return String(content);
}

/** 探测 Ollama 是否已在监听（短超时，不拖慢主流程）。 */
async function ollamaAlive() {
  try {
    const res = await fetch(`${OLLAMA_URL}/api/tags`, { signal: AbortSignal.timeout(1200) });
    return res.ok;
  } catch {
    return false;
  }
}

/** 按需启动 Ollama：没在跑就 spawn `ollama serve`，等端口就绪（最多 ~15s）。 */
async function ensureOllama() {
  if (await ollamaAlive()) return true;
  if (!existsSync(OLLAMA_EXE)) return false;
  try {
    const child = spawn(OLLAMA_EXE, ["serve"], {
      detached: true,
      stdio: "ignore",
      windowsHide: true,
    });
    child.unref();
  } catch {
    return false;
  }
  for (let i = 0; i < 50; i += 1) {
    await new Promise((r) => setTimeout(r, 300));
    if (await ollamaAlive()) return true;
  }
  return false;
}

async function callOllama(path, question) {
  // 按需启动：Ollama 平时不常驻（不占内存），只有真正要用本地视觉时才把它拉起来
  const started = await ensureOllama();
  if (!started) throw new Error("本地 Ollama 未运行且自动启动失败（可设 DSH_VISION_OLLAMA_EXE 指定 ollama.exe 路径）");
  const img = readFileSync(path).toString("base64");
  const res = await fetch(`${OLLAMA_URL}/api/generate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      model: OLLAMA_MODEL,
      prompt: question,
      images: [img],
      stream: false,
      options: { temperature: 0.2 },
    }),
    signal: AbortSignal.timeout(180000),
  });
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`Ollama 调用失败（HTTP ${res.status}）: ${body.slice(0, 300)}`);
  }
  const data = await res.json();
  if (data.error) throw new Error(`Ollama 错误: ${data.error}`);
  return String(data.response || "").trim();
}

export function apply(ctx) {
  ctx.tools.register({
    name: "vision_describe",
    description:
      "看图理解（不是看图计数）：智谱 GLM-4V API（旗舰质量、快，需联网）优先，失败兜底本地 Ollama Qwen2.5-VL（离线）。"
      + "**什么时候该用它**：需要「理解画面语义」时——这图在讲什么、人物什么表情、界面布局合不合理、这图有什么毛病、图里的字连起来是什么意思。"
      + "**什么时候不该用它**：只是要「看一眼 / 数个数 / 认个小字 / 确认某个图标在不在」→ 用 read_image 直看，更快也不用花钱。"
      // 2026-11-08 实测：read_image 被调 353 次、vision_describe 只有 8 次。不是它不好用，
      // 是我把「要理解」的事也用「看一眼」的方式处理了。把判据写进描述，让它在我选工具那一刻出现。
      + "同一张图 + 同一个问题默认复用 7 天内的缓存结果（省 API 费用），需要重算时传 noCache=true。",
    parameters: {
      type: "object",
      properties: {
        path: { type: "string", description: "本地图片绝对路径（png/jpg/jpeg/webp/gif/bmp/tiff）" },
        question: {
          type: "string",
          description: "想问的问题（可选）。不给则默认详细描述图片并完整提取文字。",
        },
        mode: {
          type: "string",
          enum: ["auto", "api", "local"],
          description: "auto=智谱优先、失败兜底本地（默认）；api=只用智谱；local=只用本地 Ollama。",
        },
        noCache: {
          type: "boolean",
          description: "可选：true 时跳过缓存、强制重新识图（默认 false，同图同问题复用 7 天内结果）。",
        },
      },
      required: ["path"],
    },
    output: textOutput(),
    async execute(args) {
      const path = String(args?.path || "").trim();
      const question =
        args?.question ||
        "请详细描述这张图片的内容（主体、场景、文字、风格）；如果图片中有文字，请完整、逐字地提取出来，不要遗漏。";
      const mode = String(args?.mode || "auto");
      const noCache = args?.noCache === true;
      const size = validateImage(path);
      const t0 = Date.now();
      const key = CACHE_OFF ? "" : cacheKey(path, question, mode);

      if (!noCache) {
        const cached = getCache(key);
        if (cached) {
          return `[${basename(path)} | ${(size / 1024).toFixed(0)}KB | 引擎: cache(${cached.engine || "?"}) | 缓存命中，0.0s]\n\n${cached.text}`;
        }
      }

      let text = "";
      let engine = "";
      if (mode === "local") {
        engine = "local";
        text = await callOllama(path, question);
      } else if (mode === "api") {
        engine = "api";
        text = await callZhipu(path, question);
      } else {
        try {
          engine = "api";
          text = await callZhipu(path, question);
        } catch (e) {
          engine = `local(兜底: ${String(e.message || e).slice(0, 80)})`;
          text = await callOllama(path, question);
        }
      }
      // 只缓存成功结果：失败会抛错，不会走到这里；engine 去掉兜底原因，避免把一次性的错误文案长期存进缓存
      putCache(key, text, String(engine).replace(/\(.*$/, ""), path);
      const elapsed = Date.now() - t0;
      return `[${basename(path)} | ${(size / 1024).toFixed(0)}KB | 引擎: ${engine} | 耗时 ${(elapsed / 1000).toFixed(1)}s]\n\n${text}`;
    },
  });
}
