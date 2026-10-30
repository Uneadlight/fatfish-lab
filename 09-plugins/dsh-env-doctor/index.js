import { execFileSync } from "node:child_process";
import { readFileSync, readdirSync, statSync, lstatSync, accessSync, mkdirSync, existsSync, constants, appendFileSync, writeFileSync, renameSync, statfsSync } from "node:fs";
import { join, dirname } from "node:path";
import { homedir } from "node:os";
import { pathToFileURL, fileURLToPath } from "node:url";

export const name = "dsh-env-doctor";
export const inject = ["tools"];

const HOME = homedir();
const DSH_HOME = process.env.DSH_HOME || join(HOME, ".dsh");
const PROFILE_DIR = join(DSH_HOME, "profiles", "desktop");
const BILI_CONFIG = join(HOME, ".config", "billion-context", "billion-context.json");
const BILI_STATE = join(HOME, ".local", "state", "billion-context");
const BILI_INSTANCES = join(BILI_STATE, "instances");
const BILI_LOG = join(BILI_STATE, "bili.log");
const ITERATE_DIR = join("D:\work", "dsh-plugin-iterate");
const APPLY_BILI = join(ITERATE_DIR, "apply-bili.ps1");
const CHECK_MJS = join(ITERATE_DIR, "check.mjs");
const NODE_BIN = join(DSH_HOME, "dsh-runtimes", "dsh-primary-runtime", "dependencies", "node", "bin", "node.exe");
// The plugin's own directory: needed by the toolchain self-check, which runs
// `node --check` against this very file.
const SELF_DIR = dirname(fileURLToPath(import.meta.url));
const COMPAT_CHECK = join(ITERATE_DIR, "compat-check.ps1");
const POWERSHELL_EXE = join(process.env.SystemRoot || "C:\\Windows", "System32", "WindowsPowerShell", "v1.0", "powershell.exe");
const PROFILE_PKG = join(PROFILE_DIR, "package.json");
const PROFILE_PATCH = join(PROFILE_DIR, "cordis.patch.yml");
const MEMORY_FILE = join(DSH_HOME, "memory", "memories.json");
const WORKSPACE_ROOT = "E:\\";

const OK = "OK";
const WARN = "WARN";
const FAIL = "FAIL";
const INFO = "INFO";

function fmtTime(ms) {
  if (!ms) return "?";
  const d = new Date(ms);
  const p = (n) => String(n).padStart(2, "0");
  return `${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
}

function ps(script, timeout = 20000) {
  return execFileSync(
    "powershell.exe",
    ["-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command",
      "[Console]::OutputEncoding=[Text.Encoding]::UTF8;" + script],
    { encoding: "utf8", timeout, windowsHide: true },
  ).trim();
}

function briefError(e) {
  const raw = String(e?.stderr || e?.message || e || "");
  const first = raw.split("\n").map((l) => l.trim()).find((l) => l.length > 0 && !l.startsWith("+")) || raw.split("\n")[0];
  return first.slice(0, 180);
}

function readJson(path) {
  return JSON.parse(readFileSync(path, "utf8"));
}

function cmpVer(a, b) {
  const pa = String(a).replace(/^[\^~>=<]+/, "").split(".").map((n) => parseInt(n, 10) || 0);
  const pb = String(b).replace(/^[\^~>=<]+/, "").split(".").map((n) => parseInt(n, 10) || 0);
  for (let i = 0; i < 3; i += 1) {
    if ((pa[i] || 0) !== (pb[i] || 0)) return (pa[i] || 0) - (pb[i] || 0);
  }
  return 0;
}

/* ================================================================ */
/* 1. 工作区                                                        */
/* ================================================================ */

function checkWorkspace(workspace) {
  const out = [];
  try {
    statSync(workspace);
  } catch {
    return [{ level: FAIL, title: "工作区路径不存在或不可访问", detail: String(workspace), fix: "确认路径拼写；跨盘请用绝对路径" }];
  }

  const p = String(workspace).replace(/'/g, "''");
  let info;
  try {
    const raw = ps(
      `$ErrorActionPreference='Stop';$p='${p}';` +
        `$i=Get-Item -LiteralPath $p -Force;$acl=Get-Acl -LiteralPath $p;` +
        `$k=Get-ItemProperty -Path 'HKLM:\\SOFTWARE\\Microsoft\\PowerShell\\1\\ShellIds\\Microsoft.PowerShell' -Name ExecutionPolicy -ErrorAction SilentlyContinue;` +
        `@{ owner=$acl.Owner; me=[Security.Principal.WindowsIdentity]::GetCurrent().Name; ` +
        `reparse=((($i.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) -or ($null -ne $i.LinkTarget)); ` +
        `policy=if($k){$k.ExecutionPolicy}else{''} } | ConvertTo-Json -Compress`,
    );
    info = JSON.parse(raw);
  } catch (e) {
    return [{ level: WARN, title: "工作区探测失败", detail: `PowerShell 调用失败：${briefError(e)}`, fix: null }];
  }

  const owner = String(info.owner || "");
  const me = String(info.me || "");
  if (owner.toLowerCase() === me.toLowerCase()) {
    out.push({ level: OK, title: "工作区 owner", detail: `${owner}` });
  } else {
    out.push({
      level: FAIL,
      title: "工作区 owner 不是当前用户",
      detail: `owner=${owner}，当前=${me}。workspace-write 下 DSH 会拒绝准备 ACL。`,
      fix: `icacls "${workspace}" /setowner "${me}"`,
      risky: true,
    });
  }

  if (info.reparse === true) {
    out.push({ level: FAIL, title: "工作区是符号链接/junction", detail: "沙箱要求真实目录", fix: `fsutil reparsepoint query "${workspace}"` });
  } else {
    out.push({ level: OK, title: "工作区非 reparse point", detail: "真实目录" });
  }

  const policy = String(info.policy || "");
  if (!policy || /^(Unrestricted|Bypass|RemoteSigned)$/i.test(policy)) {
    out.push({ level: OK, title: "PowerShell 执行策略", detail: policy || "未设置（默认）" });
  } else {
    out.push({
      level: WARN,
      title: `PowerShell 执行策略=${policy}，禁止直接运行 .ps1`,
      detail: "会话里 & script.ps1 会报 UnauthorizedAccess",
      fix: "powershell.exe -NoProfile -ExecutionPolicy Bypass -File <脚本路径>",
    });
  }
  return out;
}

/* ================================================================ */
/* 2. billion-context                                               */
/* ================================================================ */

function checkBili() {
  const out = [];
  let cfgMtime = 0;
  let cfg;
  try {
    cfgMtime = statSync(BILI_CONFIG).mtimeMs;
    cfg = readJson(BILI_CONFIG);
    out.push({ level: OK, title: "bili 配置文件", detail: `${fmtTime(cfgMtime)} 写入，JSON 合法` });
  } catch (e) {
    out.push({ level: WARN, title: "bili 配置不可读或非法", detail: briefError(e), fix: "检查 billion-context.json，必要时从 .bak 恢复" });
    return out;
  }

  const wantNudge = Number(cfg?.compress?.nudgeGrowthTokens || 0);

  let instances = [];
  try {
    instances = readdirSync(BILI_INSTANCES)
      .filter((f) => f.endsWith(".json"))
      .map((f) => {
        const path = join(BILI_INSTANCES, f);
        try {
          return { path, ...readJson(path) };
        } catch {
          return null;
        }
      })
      .filter(Boolean);
  } catch {
    instances = [];
  }

  const alive = instances.filter((i) => {
    const pid = Number(i.pid);
    if (!Number.isFinite(pid) || pid <= 0) return false;
    try {
      process.kill(pid, 0);
      return true;
    } catch {
      return false;
    }
  });

  if (alive.length === 0) {
    out.push({ level: WARN, title: "bili sidecar 未在运行", detail: "DSH 下次启动会拉起新的", fix: null });
    return out;
  }

  for (const inst of alive) {
    // 实例文件可能在 readdir 之后、这里之前被 sidecar 清掉；statSync 不能裸奔，
    // 否则一个瞬时 ENOENT 会让整次 env_doctor 直接抛错，别的检查也看不到。
    let started = Number(inst.startedAt || 0);
    if (!started) {
      try {
        started = statSync(inst.path).mtimeMs;
      } catch {
        started = 0;
      }
    }
    if (!started) {
      out.push({
        level: WARN,
        title: "bili sidecar 启动时间未知",
        detail: `pid ${inst.pid}，无法确认它是否加载了最新配置`,
        fix: `powershell -NoProfile -ExecutionPolicy Bypass -File "${APPLY_BILI}" -Force`,
      });
    } else if (cfgMtime > started + 1500) {
      out.push({
        level: FAIL,
        title: "bili 配置未生效：sidecar 比配置旧",
        detail: `sidecar pid ${inst.pid} 启动于 ${fmtTime(started)}，配置写入于 ${fmtTime(cfgMtime)}`,
        fix: `powershell -NoProfile -ExecutionPolicy Bypass -File "${APPLY_BILI}"`,
        risky: true,
      });
    } else {
      out.push({ level: OK, title: "bili sidecar 已加载最新配置", detail: `pid ${inst.pid}，启动于 ${fmtTime(started)}` });
    }
  }

  if (wantNudge > 0) {
    try {
      const size = statSync(BILI_LOG).size;
      const buf = readFileSync(BILI_LOG);
      const tail = buf.subarray(Math.max(0, size - 96 * 1024)).toString("utf8");
      const lines = tail.split("\n").filter((l) => l.includes("interval="));
      const m = (lines[lines.length - 1] || "").match(/interval=(\d+)/);
      if (m) {
        const live = Number(m[1]);
        if (live === wantNudge) {
          out.push({ level: OK, title: "bili 运行时值一致", detail: `nudgeGrowthTokens=${live}` });
        } else {
          out.push({ level: WARN, title: "bili 运行时值与配置不一致", detail: `配置 ${wantNudge}，日志 ${live}`, fix: `powershell -NoProfile -ExecutionPolicy Bypass -File "${APPLY_BILI}" -Force` });
        }
      }
    } catch {
      /* 日志还没写出来不算问题 */
    }
  }
  return out;
}

/* ================================================================ */
/* 3. 关键目录                                                      */
/* ================================================================ */

function checkPaths() {
  const out = [];
  for (const dir of [DSH_HOME, join(DSH_HOME, "sessions"), BILI_STATE]) {
    try {
      statSync(dir);
    } catch {
      out.push({
        level: WARN,
        title: "目录不存在",
        detail: dir,
        fix: `mkdir "${dir}"`,
        autoFix: () => mkdirSync(dir, { recursive: true }),
      });
      continue;
    }
    try {
      accessSync(dir, constants.W_OK);
      out.push({ level: OK, title: "目录可写", detail: dir });
    } catch {
      out.push({ level: FAIL, title: "目录不可写", detail: dir, fix: `icacls "${dir}" /grant "${process.env.USERNAME}:(OI)(CI)M"`, risky: true });
    }
  }
  return out;
}

/* ================================================================ */
/* 3.5 记忆库完整性 / 插件目录 / 磁盘空间 / 配置漂移                 */
/* ================================================================ */

function checkMemories() {
  let raw;
  try {
    raw = readFileSync(MEMORY_FILE, "utf8");
  } catch {
    return [{ level: INFO, title: "记忆库不存在", detail: MEMORY_FILE, fix: null }];
  }
  let db;
  try {
    db = JSON.parse(raw);
  } catch (e) {
    return [{ level: FAIL, title: "记忆库 JSON 损坏", detail: briefError(e), fix: "从 backups 恢复：把 memories.json.bak-* 里最近一份复制覆盖回来" }];
  }
  const count = Array.isArray(db?.memories) ? db.memories.length : -1;
  if (count < 0) return [{ level: FAIL, title: "记忆库结构异常", detail: "没有 memories 数组", fix: null }];
  if (count === 0) return [{ level: WARN, title: "记忆库为空", detail: MEMORY_FILE, fix: null }];
  const mems = db.memories;
  const chars = mems.reduce((n, m) => n + String(m?.content || "").length, 0);
  const live = mems.filter((m) => m.deprecated !== true);
  const fiveList = live.filter((m) => (m.importance ?? 3) >= 5);
  const fives = fiveList.length;
  const fiveChars = fiveList.reduce((n, m) => n + String(m?.content || "").length, 0);
  const fours = live.filter((m) => (m.importance ?? 3) === 4).length;
  const detail = `${count} 条（5/5:${fives} · 4/5:${fours}） · ${(raw.length / 1024).toFixed(1)} KB · 正文 ${chars} 字符 · 5/5 ${fiveChars} 字符`;
  // 净化触发条件（对齐 D:\work\自进化\记忆库优化规则.md）：
  // 成本由「注入字符量」决定（字符是硬指标，条数只是近似），总条数只要别失控就不算问题。
  // 2026-10-27 用户拍板：上限从 7,500 扩到 12,000 字符（约 32 条）——边际成本实测 <1.5 元/月，可接受。
  // 2026-10-29 定档重算：dsh-memory v0.4.6 把注入预算 18,000 → 30,000、并给 4/5 保底 12,000，
  // 5/5 现为 13,302 字符属正常水平，旧的 12,000 阈值会让 WARN 永远挂着（误报）。
  // 新口径：5/5 > 24,000（占预算 40%）或「估算注入量」> 32,000 才提醒；估算 = 5/5 正文 + 4/5 正文每人按 ≤500 计（截断后）。
  // 2026-10-30 再对齐：预算 30,000 → 60,000、4/5 保底 12,000 → 20,000，5/5 报警线按 40% 同步到 24,000
  // （5/5 现 37 条 / 18,466 字符；24,000 给正常增长留了余量，又能在真失控前报出来）。
  const LIMIT_FIVE_CHARS = 24000;
  const LIMIT_FIVES = 40;
  const LIMIT_FOURS = 60;
  const LIMIT_COUNT = 150;
  const LIMIT_CHARS = 90000;
  const LIMIT_INJECT_EST = 48000;
  const fourInjectEst = live
    .filter((m) => (m.importance ?? 3) === 4)
    .reduce((n, m) => n + Math.min(String(m?.content || "").length, 500), 0);
  const injectEst = fiveChars + fourInjectEst;
  const reasons = [];
  if (fiveChars > LIMIT_FIVE_CHARS) reasons.push(`5/5 已 ${fiveChars} 字符 > ${LIMIT_FIVE_CHARS}（全量注入，直接推高每轮成本）`);
  if (injectEst > LIMIT_INJECT_EST) reasons.push(`估算注入量 ${injectEst} 字符 > ${LIMIT_INJECT_EST}（5/5 全量 + 4/5 截断后合计）`);
  if (fives > LIMIT_FIVES) reasons.push(`5/5 已 ${fives} 条 > ${LIMIT_FIVES}`);
  if (fours > LIMIT_FOURS) reasons.push(`4/5 已 ${fours} 条 > ${LIMIT_FOURS}`);
  if (count > LIMIT_COUNT) reasons.push(`总条数 ${count} > ${LIMIT_COUNT}`);
  if (chars > LIMIT_CHARS) reasons.push(`正文 ${chars} 字符 > ${LIMIT_CHARS}`);
  if (reasons.length > 0) {
    return [
      { level: OK, title: "记忆库正常", detail },
      {
        level: WARN,
        title: "记忆库该净化了（触发自我优化前提）",
        detail: reasons.join("；"),
        fix: "按 D:\work\\自进化\\记忆库优化规则.md 执行：先备份 memories.json，再合并重复/降级次要/删除过时，保留身份·规则·偏好骨架，改完校验 JSON 与重复 id",
      },
    ];
  }
  return [{ level: OK, title: "记忆库正常", detail }];
}

function checkPluginDirs() {
  let pkg;
  try {
    pkg = readJson(PROFILE_PKG);
  } catch {
    return [{ level: WARN, title: "profile 清单读不到", detail: PROFILE_PKG, fix: null }];
  }
  const bundles = pkg?.dsh?.profile?.bundles || [];
  const deps = pkg?.dependencies || {};
  const missing = [];
  for (const name of bundles) {
    // 只检查 profile 自己声明依赖的插件；内置/外部 bundle 由 DSH 运行时解析，不在 node_modules 里
    if (!isDeclaredDependency(name, deps)) continue;
    if (!existsSync(join(PROFILE_DIR, "node_modules", name))) missing.push(name);
  }
  const checked = bundles.filter((name) => isDeclaredDependency(name, deps)).length;
  if (missing.length) {
    return [{ level: FAIL, title: "插件目录缺失", detail: missing.join("、"), fix: `plugin_manager install_bundle 重装：${missing.join(" / ")}` }];
  }
  return [{ level: OK, title: "插件目录齐全", detail: `${checked} 个自带依赖 · 内置 ${bundles.length - checked} 个` }];
}

/* ---- 插件变更追踪：装/删/升级任何插件，大内总管都会自己发现并体检 ---- */

const PLUGIN_SNAPSHOT = join(SELF_DIR, ".plugin-snapshot.json");

/** 当前所有已装插件的 name → version（profile bundles + @local 目录）。 */
function installedPluginMap() {
  const map = new Map();
  let pkg = null;
  try {
    pkg = readJson(PROFILE_PKG);
  } catch {
    pkg = null;
  }
  const bundles = pkg?.dsh?.profile?.bundles || [];
  for (const raw of bundles) {
    const name = String(raw);
    let version = "?";
    try {
      version = String(readJson(join(PROFILE_DIR, "node_modules", name, "package.json")).version || "?");
    } catch {
      version = "?";
    }
    map.set(name, version);
  }
  try {
    const localRoot = join(PROFILE_DIR, "node_modules", "@local");
    for (const d of readdirSync(localRoot, { withFileTypes: true })) {
      // link 安装的包是符号链接（isSymbolicLink），不能只认 isDirectory
      if (!d.isDirectory() && !d.isSymbolicLink()) continue;
      const name = "@local/" + d.name;
      let version = "?";
      try {
        version = String(readJson(join(localRoot, d.name, "package.json")).version || "?");
      } catch {
        version = "?";
      }
      if (!map.has(name)) map.set(name, version);
    }
  } catch {
    // 没有 @local 目录就只比 bundles
  }
  return map;
}

function readPluginSnapshot() {
  try {
    const raw = readJson(PLUGIN_SNAPSHOT);
    if (raw && typeof raw === "object" && raw.plugins && typeof raw.plugins === "object") {
      return { takenAt: String(raw.takenAt || ""), plugins: raw.plugins };
    }
  } catch {
    // 首次运行或文件损坏
  }
  return null;
}

function savePluginSnapshot(map) {
  try {
    const data = { takenAt: new Date().toISOString(), plugins: Object.fromEntries(map) };
    const tmp = PLUGIN_SNAPSHOT + ".tmp-" + process.pid;
    writeFileSync(tmp, JSON.stringify(data, null, 1), "utf8");
    renameSync(tmp, PLUGIN_SNAPSHOT);
  } catch {
    // 写不进去最多下次重复报一次变更
  }
}

/**
 * 插件变更追踪：对比上次基线，报告新增/移除/版本变化，并自动更新基线。
 * 这样不管是我装的、用户装的、第三方市场装的，还是自研插件升级，大内总管都能接管。
 */
function checkPluginDrift() {
  const current = installedPluginMap();
  const prev = readPluginSnapshot();
  if (!prev) {
    savePluginSnapshot(current);
    return [{ level: INFO, title: "插件变更追踪：首次建立基线", detail: `已记录 ${current.size} 个插件，之后有增减/升级会在这里报出来` }];
  }
  const prevPlugins = prev.plugins || {};
  const added = [];
  const removed = [];
  const changed = [];
  for (const [name, version] of current) {
    if (!(name in prevPlugins)) added.push(`${name}@${version}`);
    else if (String(prevPlugins[name]) !== String(version)) changed.push(`${name} ${prevPlugins[name]}→${version}`);
  }
  for (const name of Object.keys(prevPlugins)) {
    if (!current.has(name)) removed.push(`${name}@${prevPlugins[name]}`);
  }
  if (added.length === 0 && removed.length === 0 && changed.length === 0) {
    return [{ level: OK, title: "插件变更追踪：无变化", detail: `${current.size} 个插件与上次基线一致（基线 ${prev.takenAt ? fmtTime(Date.parse(prev.takenAt)) : "未知"}）` }];
  }
  const parts = [];
  if (added.length) parts.push(`新增 ${added.length}：${added.join("、")}`);
  if (removed.length) parts.push(`移除 ${removed.length}：${removed.join("、")}`);
  if (changed.length) parts.push(`版本变化 ${changed.length}：${changed.join("、")}`);
  savePluginSnapshot(current);
  return [{
    level: added.length || removed.length ? WARN : INFO,
    title: "插件变更追踪：检测到变化（基线已更新）",
    detail: parts.join("；"),
    fix: "新增/升级的插件建议跑 env_doctor only=health 验证入口能加载；移除的插件确认是有意卸载",
  }];
}

function checkDisk() {
  const out = [];
  for (const [label, path] of [["工作区盘", WORKSPACE_ROOT], ["用户盘", HOME]]) {
    try {
      const st = statfsSync(path);
      const freeGB = (st.bavail * st.bsize) / 1024 / 1024 / 1024;
      const totalGB = (st.blocks * st.bsize) / 1024 / 1024 / 1024;
      const pct = totalGB ? Math.round((freeGB / totalGB) * 100) : 0;
      if (freeGB < 5) out.push({ level: WARN, title: `磁盘剩余偏少：${label}`, detail: `${path} 剩 ${freeGB.toFixed(1)} GB`, fix: "清理大文件或换盘" });
      else out.push({ level: OK, title: `磁盘空间：${label}`, detail: `${path} 剩 ${freeGB.toFixed(1)} GB（${pct}%）` });
    } catch (e) {
      out.push({ level: WARN, title: `磁盘查询失败：${label}`, detail: briefError(e), fix: null });
    }
  }
  return out;
}

const configBaseline = new Map();
function captureConfigBaseline() {
  for (const file of [PROFILE_PKG, PROFILE_PATCH]) {
    try {
      configBaseline.set(file, statSync(file).mtimeMs);
    } catch {
      // 不存在就算了，下次再看
    }
  }
}

function checkConfigDrift() {
  if (configBaseline.size === 0) captureConfigBaseline();
  const out = [];
  for (const [file, base] of configBaseline) {
    let now;
    try {
      now = statSync(file).mtimeMs;
    } catch {
      out.push({ level: WARN, title: "配置文件消失", detail: file, fix: null });
      continue;
    }
    if (now > base + 1000) {
      out.push({ level: WARN, title: "配置已改动，可能没重启", detail: `${file} 于 ${fmtTime(now)} 被改，DSH 仍在用旧配置`, fix: "确认改动无误后重启 DSH" });
    } else {
      out.push({ level: OK, title: "配置未漂移", detail: file });
    }
  }
  return out;
}

/* ================================================================ */
/* 4. 插件健康（版本 / 本地链接 / 禁用）                              */
/* ================================================================ */

const BUILTIN = /^@deepseek-ai\//;

/**
 * bundle 是否由 profile 自己安装。
 * 不在 dependencies 里的 bundle 由 DSH 运行时/外部管理器提供（如 @deepseek-ai/*
 * 和 @agents-anywhere/dsh-bridge-next 这种桥接 bundle），不能拿 node_modules
 * 里有没有来判死，否则每次巡检都会误报“插件目录缺失”。
 */
function isDeclaredDependency(name, deps) {
  return Object.prototype.hasOwnProperty.call(deps, name);
}

function pluginEntry(name) {
  const local = join(PROFILE_DIR, "node_modules", name);
  try {
    const pkg = readJson(join(local, "package.json"));
    return { name, version: String(pkg.version || "?"), description: String(pkg.description || ""), missing: false };
  } catch {
    return { name, version: "?", description: "", missing: true };
  }
}

/**
 * 工具链自检：验证「质检命令本身」还能不能跑。
 * 教训：v0.4 加了 ctx.effect 之后 selftest.mjs 的 mock 缺这个方法，自检脚本
 * 静默崩了很久没人发现——检查工具坏了，比不做检查更危险。
 * 只读执行，不改任何文件；成本 3-5 秒，所以只在 only=all 和慢档（每 6 小时）跑。
 */
function checkToolchain() {
  const out = [];
  const selfIndex = join(SELF_DIR, "index.js");
  const required = [
    ["iterate.ps1", join(ITERATE_DIR, "iterate.ps1")],
    ["prompt-fix.txt", join(ITERATE_DIR, "prompt-fix.txt")],
    ["iterate-doctor.ps1", join(ITERATE_DIR, "iterate-doctor.ps1")],
    ["prompt-doctor.txt", join(ITERATE_DIR, "prompt-doctor.txt")],
    ["check-task.ps1", join(ITERATE_DIR, "check-task.ps1")],
    ["compat-check.ps1", COMPAT_CHECK],
  ];

  // 1) 自己不能执行自己（会递归启动守护），只做语法检查
  try {
    execFileSync(NODE_BIN, ["--check", selfIndex], { timeout: 30000, windowsHide: true, stdio: "ignore" });
    out.push({ level: OK, title: "工具链：插件自身语法", detail: "node --check 通过" });
  } catch (e) {
    out.push({
      level: FAIL,
      title: "工具链：插件自身语法错误",
      detail: briefError(e),
      fix: `"${NODE_BIN}" --check "${selfIndex}" 看行号；语法错会让整个插件加载失败`,
    });
  }

  // 2) 自动化脚本是否齐全
  const missing = required.filter(([, p]) => !existsSync(p)).map(([n]) => n);
  if (missing.length === 0) {
    out.push({ level: OK, title: "工具链：关键脚本齐全", detail: `${required.length} 个文件都在` });
  } else {
    out.push({
      level: FAIL,
      title: "工具链：关键脚本缺失",
      detail: missing.join("、"),
      fix: "按 ITERATE.md 的文件表核对；缺了脚本，定时任务会静默失败",
    });
  }

  // 3) check.mjs 能不能跑通（exit 0/1 = 能跑，2 = 有真 FAIL，其他 = 崩了）
  if (existsSync(CHECK_MJS)) {
    try {
      execFileSync(NODE_BIN, [CHECK_MJS, "--no-network"], { timeout: 90000, windowsHide: true, stdio: "ignore" });
      out.push({ level: OK, title: "工具链：check.mjs 可执行", detail: "跑通，无 WARN/FAIL" });
    } catch (e) {
      const code = typeof e.status === "number" ? e.status : -1;
      if (code === 1) {
        out.push({ level: OK, title: "工具链：check.mjs 可执行", detail: "跑通，有 WARN（属正常提醒）" });
      } else if (code === 2) {
        out.push({
          level: WARN,
          title: "工具链：check.mjs 报 FAIL",
          detail: "脚本本身能跑，但有检查项真的没过",
          fix: `"${NODE_BIN}" "${CHECK_MJS}" --no-network 看明细，或看 reports/latest.json`,
        });
      } else {
        out.push({
          level: FAIL,
          title: "工具链：check.mjs 跑不起来",
          detail: briefError(e),
          fix: "手动跑一次 node check.mjs --no-network；它挂了周迭代会静默跳过",
        });
      }
    }
  }

  // 4) compat-check.ps1 能不能跑通（exit 1 = 检查不通过，不是脚本跑不起来）
  if (existsSync(COMPAT_CHECK)) {
    let text = "";
    let runError = null;
    let runCode = 0;
    try {
      text = String(
        execFileSync(POWERSHELL_EXE, ["-NoProfile", "-ExecutionPolicy", "Bypass", "-File", COMPAT_CHECK], {
          timeout: 90000,
          windowsHide: true,
          encoding: "utf8",
        }),
      );
    } catch (e) {
      // compat-check 用 exit 1 表示“版本不匹配”，此时 stdout 里已有完整 RESULT。
      // 以前把所有非 0 退出都当成“脚本跑不起来”，会把真正的兼容性问题误诊成工具链坏了。
      runCode = typeof e.status === "number" ? e.status : -1;
      if ((runCode === 1 || runCode === 2) && e.stdout) {
        text = String(e.stdout);
      } else {
        runError = e;
      }
    }
    if (runError) {
      out.push({
        level: FAIL,
        title: "工具链：compat-check 跑不起来",
        detail: briefError(runError),
        fix: "powershell -NoProfile -ExecutionPolicy Bypass -File compat-check.ps1 手动试",
      });
    } else {
      const hit = text.match(/RESULT:[^\r\n]*/);
      if (!hit) {
        out.push({
          // exit 0 但没 RESULT 才是“输出异常”；exit 1/2 说明脚本自己失败了，不能降级。
          level: runCode === 0 ? WARN : FAIL,
          title: runCode === 0 ? "工具链：compat-check 输出异常" : "工具链：compat-check 执行失败",
          detail: runCode === 0 ? "跑完了但没有 RESULT 行" : `退出码 ${runCode}，但没有 RESULT 行`,
          fix: "手动跑一次看完整输出，可能是插件目录结构变了",
        });
      } else if (runCode === 0 && /RESULT:\s*PASS/i.test(hit[0])) {
        out.push({ level: OK, title: "工具链：compat-check 可执行", detail: hit[0].trim() });
      } else {
        // 脚本本身是好的，只是检查没通过；把 FAIL 明细一起带出来，别再让人去猜。
        const passText = /RESULT:\s*PASS/i.test(hit[0]);
        const failLines = text.split(/\r?\n/).filter((l) => /^\[FAIL\]/.test(l.trim())).slice(0, 3);
        out.push({
          level: FAIL,
          title: passText ? "工具链：compat-check 退出码异常" : "工具链：compat-check 不通过",
          detail: [hit[0].trim(), ...(runCode !== 0 ? [`退出码 ${runCode}`] : []), ...failLines].join("\n"),
          fix: "按上面的 FAIL 行处理（版本/依赖/bundle 登记），修好后重跑 compat-check",
        });
      }
    }
  }

  return out;
}

// 自研插件与本地工具（2026-10-25 新增：识图/Ollama/RapidOCR/ffmpeg）
function checkLocalTools() {
  const out = [];
  // 1) @local 自研插件：动态扫描目录（不再硬编码名单，装/删自研插件自动适配）
  const localRoot = join(PROFILE_DIR, "node_modules", "@local");
  let localNames = [];
  try {
    localNames = readdirSync(localRoot, { withFileTypes: true })
      // link 安装是符号链接，isDirectory 会漏掉它们
      .filter((d) => d.isDirectory() || d.isSymbolicLink())
      .map((d) => d.name)
      .sort();
  } catch {
    localNames = [];
  }
  const localMissing = localNames.filter((n) => !existsSync(join(localRoot, n, "package.json")));
  let registered = new Set();
  try {
    const pkg = readJson(PROFILE_PKG);
    registered = new Set((pkg?.dsh?.profile?.bundles || []).map(String));
    for (const dep of Object.keys(pkg?.dependencies || {})) registered.add(dep);
  } catch {
    // profile 清单读不到时跳过「未登记」检查
  }
  const unregistered = localNames.filter((n) => !registered.has("@local/" + n));
  if (localNames.length === 0) {
    out.push({ level: WARN, title: "本地工具：自研插件目录为空", detail: localRoot + " 下没有 @local 包", fix: "确认自研插件是否被卸载" });
  } else if (localMissing.length === 0) {
    out.push({ level: OK, title: "本地工具：自研插件目录", detail: `${localNames.length} 个都在（${localNames.map((n) => "@local/" + n).join("、")}）` });
  } else {
    out.push({ level: WARN, title: "本地工具：自研插件目录缺 package.json", detail: localMissing.join("、"), fix: "检查 @local 下对应目录是否完整，或重新安装" });
  }
  if (unregistered.length > 0) {
    out.push({
      level: WARN,
      title: "自研插件未登记到 profile",
      detail: unregistered.map((n) => "@local/" + n).join("、") + "（目录在但不在 profile 的 bundles/dependencies 里，DSH 不会加载）",
      fix: "plugin_manager install_bundle link:E:/DS公作区/<目录名> 重新登记",
    });
  }

  // 2) Ollama 服务 + 视觉模型
  let ollamaOk = false;
  try {
    const raw = String(execFileSync("curl", ["-s", "--max-time", "8", "http://127.0.0.1:11434/api/tags"], { timeout: 12000, encoding: "utf8", windowsHide: true })).trim();
    const data = JSON.parse(raw || "{}");
    const models = (data.models || []).map((m) => m.name);
    ollamaOk = true;
    const vl = models.filter((m) => /vl|vision|llava|minicpm/i.test(m));
    if (vl.length > 0) {
      out.push({ level: OK, title: "本地工具：Ollama 视觉模型", detail: vl.join("、") });
    } else {
      out.push({ level: WARN, title: "本地工具：Ollama 服务通但无视觉模型", detail: "识图本地兜底不可用", fix: "ollama pull qwen2.5vl:7b" });
    }
  } catch (e) {
    out.push({ level: INFO, title: "本地工具：Ollama 未运行（按需启动）", detail: "OD 不常驻、不占内存；识图走智谱 API，需要本地兜底时 dsh-vision 会自动拉起 ollama serve", fix: null });
  }
  if (!ollamaOk) out.push({ level: INFO, title: "本地工具：Ollama 可选", detail: "不装也能用智谱 API 通道" });

  // 3) 智谱视觉 key
  const keyFile = join(DSH_HOME, "dsh-vision-key.txt");
  try {
    const k = existsSync(keyFile) ? readFileSync(keyFile, "utf8").trim() : "";
    if (k.length > 20) out.push({ level: OK, title: "本地工具：智谱视觉 key", detail: "已配置（API 通道可用）" });
    else out.push({ level: WARN, title: "本地工具：智谱视觉 key 缺失/过短", detail: "API 通道不可用", fix: "open.bigmodel.cn 注册取 key，写入 " + keyFile });
  } catch (e) {
    out.push({ level: WARN, title: "本地工具：智谱 key 读取失败", detail: briefError(e) });
  }

  // 4) RapidOCR venv
  //    2026-10-29 修正：原来只查目录存在就报 OK —— 实际那个 venv 里只有 pip/setuptools，
  //    rapidocr 根本 import 不到，是假阳性。现在做真 import 探测。
  //    另外 py3.10 的 venv 里 onnxruntime 会 "DLL load failed"，换 3.12 才正常，
  //    所以按候选顺序探测，报"哪个 venv 真的能跑"。
  const ocrScript = join("D:\work", "tools", "ocr.py");
  const ocrCandidates = [
    join("D:\work", "tools", "ocr-venv312", "Scripts", "python.exe"),
    join("D:\work", "tools", "ocr-venv", "Scripts", "python.exe"),
  ];
  const probeOcr = (exe) => {
    try {
      // stdio 显式给 pipe，否则 execFileSync 会把子进程 stderr（整段 traceback）漏到巡检输出里
      const ver = execFileSync(exe, ["-c", "from importlib.metadata import version;print(version('rapidocr_onnxruntime'))"], { encoding: "utf8", timeout: 25000, windowsHide: true, stdio: ["ignore", "pipe", "pipe"] }).trim();
      return { ok: true, ver };
    } catch (e) {
      return { ok: false, err: briefError(e) };
    }
  };
  const exists = ocrCandidates.filter((p) => existsSync(p));
  if (exists.length === 0) {
    out.push({ level: WARN, title: "本地工具：RapidOCR venv 缺失", detail: "没有 tools\\ocr-venv312 或 tools\\ocr-venv", fix: "uv venv tools\\ocr-venv312 --python <py3.12> && uv pip install rapidocr_onnxruntime==1.4.4" });
  } else {
    // 懒探测：按候选顺序试，第一个成功的就停（坏的 venv 不必每次白跑一遍 import）
    let good = null;
    let firstErr = "";
    for (const p of exists) {
      const r = probeOcr(p);
      if (r.ok) { good = { p, r }; break; }
      if (!firstErr) firstErr = r.err;
    }
    if (good) {
      const extra = existsSync(ocrScript) ? "" : "；但 tools\\ocr.py 不存在";
      out.push({ level: OK, title: "本地工具：RapidOCR 可用", detail: `rapidocr ${good.r.ver}（import 实测通过，用 ${good.p}）${extra}` });
    } else {
      out.push({
        level: WARN,
        title: "本地工具：RapidOCR 装了壳跑不了",
        detail: `venv 在、import rapidocr_onnxruntime 失败：${firstErr}`,
        fix: `uv venv tools\\ocr-venv312 --python <py3.12>; uv pip install --python tools\\ocr-venv312\\Scripts\\python.exe rapidocr_onnxruntime==1.4.4`,
      });
    }
  }

  // 5) ffmpeg（剪映内置，版本目录可能随升级变化）
  try {
    const jyRoot = "E:\\JianyingPro";
    let ffmpeg = "";
    if (existsSync(jyRoot)) {
      for (const d of readdirSync(jyRoot)) {
        const p = join(jyRoot, d, "ffmpeg.exe");
        if (existsSync(p)) { ffmpeg = p; break; }
      }
    }
    if (ffmpeg) out.push({ level: OK, title: "本地工具：ffmpeg", detail: ffmpeg });
    else out.push({ level: WARN, title: "本地工具：ffmpeg 缺失", detail: "视频处理不可用", fix: "装剪映或单独安装 ffmpeg" });
  } catch (e) {
    out.push({ level: WARN, title: "本地工具：ffmpeg 检查失败", detail: briefError(e) });
  }

  return out;
}

// ============ SSOT 一致性审计（2026-10-29 新增） ============
// 独立脚本 D:\work\自进化\audit_ssot.py 负责干活（约 50-60 秒，扫全工作区 3000+ 文件），
// 这里只做"入口 + 统一格式"，不把审计逻辑搬进本插件：
//   ① 职能不同 —— 本插件查"环境/插件现在能不能用"，审计查"文档与代码说的一致不一致"；
//   ② 耗时差 100 倍（0.5s vs 55s），并进 only=all 会把每次巡检拖慢；
//   ③ 失败隔离 —— 审计脚本崩了不该连带大内总管整体失败。
const SSOT_SCRIPT = join("D:\work", "自进化", "audit_ssot.py");
const SSOT_PY = join(DSH_HOME, "dsh-runtimes", "dsh-plugin-desktop-primary-runtime", "dependencies", "python", "python.exe");

function checkSsotAudit() {
  const out = [];
  if (!existsSync(SSOT_SCRIPT)) {
    return [{ level: WARN, title: "SSOT 审计：脚本缺失", detail: SSOT_SCRIPT, fix: "恢复 D:\work\\自进化\\audit_ssot.py" }];
  }
  if (!existsSync(SSOT_PY)) {
    return [{ level: WARN, title: "SSOT 审计：找不到 python", detail: SSOT_PY, fix: "确认 dsh-plugin-desktop-primary-runtime 已安装" }];
  }
  let text = "";
  const t0 = Date.now();
  try {
    text = execFileSync(SSOT_PY, [SSOT_SCRIPT], {
      cwd: dirname(SSOT_SCRIPT),
      encoding: "utf8",
      // 2026-10-29 修：Python 在 Windows 上重定向 stdout 时默认用系统代码页（GBK），
      // 而这里按 utf8 解码 → 报告路径里的中文变成 `E:\DS������\�Խ���\...`。
      // 强制子进程用 UTF-8 输出（和 audit_ssot.py 自身的中文路径一致）。
      env: { ...process.env, PYTHONIOENCODING: "utf-8", PYTHONUTF8: "1" },
      timeout: 300000,
      windowsHide: true,
      maxBuffer: 8 * 1024 * 1024,
    });
  } catch (e) {
    return [{
      level: FAIL,
      title: "SSOT 审计：脚本执行失败",
      detail: briefError(e),
      fix: `cd D:\work\\自进化; "${SSOT_PY}" audit_ssot.py`,
    }];
  }
  const seconds = ((Date.now() - t0) / 1000).toFixed(1);
  const grab = (key) => {
    const m = text.match(new RegExp("^\\s*" + key + "\\s+(\\d+)\\s*$", "m"));
    return m ? parseInt(m[1], 10) : null;
  };
  let mdPath = (text.match(/^\s*MD\s*:\s*(.+)$/m) || [])[1] || "";
  // 兜底：万一还是因为编码拿到乱码路径（含 U+FFFD），直接列出 audit 目录里最新的报告
  if (!mdPath || mdPath.includes("\uFFFD")) {
    try {
      const auditDir = join(dirname(SSOT_SCRIPT), "audit");
      const files = readdirSync(auditDir).filter((f) => f.endsWith(".md")).map((f) => join(auditDir, f));
      if (files.length) {
        files.sort((a, b) => statSync(b).mtimeMs - statSync(a).mtimeMs);
        mdPath = files[0];
      }
    } catch { /* 拿不到就不显示路径，不影响结论 */ }
  }
  const mdLine = mdPath ? ` · 报告 ${mdPath}` : "";

  // 真腐化：文档写了错数字 / 索引指向不存在的文件 / 僵尸进程 → WARN
  const hard = [
    ["stale_params", "参数漂移（文档写的数字与代码不符）", "改文档里的过期数字，或改代码"],
    ["ghost_index_files", "索引幽灵文件（索引里有、磁盘没有）", "重跑知识库索引重建"],
    ["out_of_range_refs", "索引越界引用", "重跑知识库索引重建"],
    ["zombie_processes", "僵尸进程（ExePath 已不存在）", "按报告里的 PID 结束后重新拉起"],
  ];
  // 候选类：可能是设计如此，只提示 → INFO
  const soft = [
    ["undeclared_imports", "未声明依赖（requirements/pyproject 里没写）", "补 requirements 或确认是本地包"],
    ["dead_code_candidates", "疑似死代码（只是候选，反射/框架调用会误判）", "人工确认后再删"],
    ["dead_links", "疑似死链（模板占位/待创建目录会误报）", "人工确认"],
    ["junk_files", "残留文件（.lock/.tmp）", "确认没进程在用后归档"],
  ];
  let hardCount = 0;
  let softCount = 0;
  for (const [key, label, fix] of hard) {
    const n = grab(key);
    if (n === null) continue;
    if (n > 0) { hardCount += n; out.push({ level: WARN, title: `SSOT 审计：${label} ${n} 项`, detail: `${key}=${n}${mdLine}`, fix }); }
  }
  for (const [key, label, fix] of soft) {
    const n = grab(key);
    if (n === null) continue;
    if (n > 0) { softCount += n; out.push({ level: INFO, title: `SSOT 审计：${label} ${n} 项`, detail: `${key}=${n}${mdLine}`, fix }); }
  }
  if (hardCount === 0) {
    out.push({
      level: OK,
      title: "SSOT 审计：无真腐化",
      detail: `耗时 ${seconds}s · 真腐化 0 项 · 候选 ${softCount} 项${mdLine}`,
    });
  }
  return out;
}

async function checkPlugins({ noNetwork }) {
  const out = [];  let pkg;
  try {
    pkg = readJson(join(PROFILE_DIR, "package.json"));
  } catch (e) {
    return [{ level: WARN, title: "profile package.json 不可读", detail: briefError(e), fix: null }];
  }

  const bundles = pkg?.dsh?.profile?.bundles || [];
  const deps = pkg?.dependencies || {};
  const rows = [];

  for (const name of bundles) {
    const declared = isDeclaredDependency(name, deps);
    const spec = String(deps[name] ?? "");
    const entry = pluginEntry(name);
    // 未声明依赖的 bundle 归入“内置/外部”，不能按 npm 包查 node_modules。
    let kind = BUILTIN.test(name) || !declared ? "builtin" : "npm";
    if (kind === "npm") {
      if (spec.startsWith("link:") || spec.startsWith("workspace:")) kind = "link";
      else if (spec.startsWith("file:")) kind = "file";
    }
    rows.push({ ...entry, kind, spec });
  }

  // 本地缺失 = 真的坏了
  const broken = rows.filter((r) => r.missing && r.kind !== "builtin");
  for (const r of broken) {
    out.push({ level: FAIL, title: "插件目录缺失", detail: `${r.name}（bundle 已登记但 node_modules 里没有）`, fix: `重新 plugin_manager install_bundle 安装 ${r.name}` });
  }

  // npm 版本检查
  const checkable = rows.filter((r) => r.kind === "npm" && !r.missing);
  let upToDateCount = 0;
  if (noNetwork) {
    out.push({ level: INFO, title: "跳过 npm 版本检查", detail: "本次带 noNetwork" });
  } else {
    const results = await Promise.all(
      checkable.map(async (r) => {
        try {
          const res = await fetch(`https://registry.npmjs.org/${encodeURIComponent(r.name).replace("%40", "@")}/latest`, {
            signal: AbortSignal.timeout(6000),
          });
          if (!res.ok) return { ...r, latest: null, err: `HTTP ${res.status}` };
          const body = await res.json();
          return { ...r, latest: String(body.version || "") };
        } catch (e) {
          return { ...r, latest: null, err: briefError(e) };
        }
      }),
    );
    for (const r of results) {
      if (!r.latest) {
        out.push({ level: INFO, title: "版本查询失败", detail: `${r.name}: ${r.err || "无响应"}` });
        continue;
      }
      const diff = cmpVer(r.version, r.latest);
      if (diff < 0) {
        out.push({
          level: INFO,
          title: `插件有新版：${r.name}`,
          detail: `本地 ${r.version} → npm ${r.latest}`,
          fix: `plugin_manager install_bundle ${r.name}@${r.latest}`,
        });
      } else {
        upToDateCount += 1;
      }
    }
  }

  out.push({
    level: OK,
    title: "插件清单",
    detail: `${rows.length} 个 bundle：内置 ${rows.filter((r) => r.kind === "builtin").length}、npm ${checkable.length}、本地 link ${rows.filter((r) => r.kind === "link").length}、本地文件 ${rows.filter((r) => r.kind === "file").length}；${
      noNetwork ? "未查版本" : `${upToDateCount} 个已是最新`
    }`,
  });

  // 明细（本地链接与内置不查版本，但列出来让你知道自己装了什么）
  const locals = rows.filter((r) => r.kind === "link" || r.kind === "file");
  if (locals.length) {
    out.push({
      level: INFO,
      title: "本地包（不参与版本检查）",
      detail: locals.map((r) => `${r.name}@${r.version}${r.kind === "link" ? " [link]" : " [file]"}`).join(" / "),
    });
  }
  return out;
}

/* ================================================================ */
/* 5. 计划任务（自动化还在不在跑）                                    */
/* ================================================================ */

/** PowerShell 的 ConvertTo-Json 把日期序列化成 "/Date(ms)/"，直接 new Date() 会 Invalid。 */
function checkMiscAndMcp() {
  const checks = [];
  // 1. profile node_modules 全量包完整性
  try {
    const nm = join(PROFILE_DIR, "node_modules");
    let total = 0;
    let broken = 0;
    for (const d of readdirSync(nm)) {
      if (d.startsWith(".")) continue;
      if (d.startsWith("@")) {
        for (const s of readdirSync(join(nm, d))) {
          const sp = join(nm, d, s);
          try { if (!lstatSync(sp).isDirectory()) continue; } catch { continue; }
          total++;
          if (!existsSync(join(sp, "package.json"))) broken++;
        }
      } else {
        const sp = join(nm, d);
        try { if (!lstatSync(sp).isDirectory()) continue; } catch { continue; }
        total++;
        if (!existsSync(join(sp, "package.json"))) broken++;
      }
    }
    checks.push({ level: broken ? WARN : OK, title: "插件包完整性", detail: total + " 个包" + (broken ? "，" + broken + " 个缺 package.json" : "，全部完整"), fix: null });
  } catch (e) {
    checks.push({ level: INFO, title: "插件包完整性", detail: briefError(e), fix: null });
  }
  // 2. OpenDesign MCP（依赖 OD daemon 端口 63256）
  let odUp = false;
  try {
    const n = execFileSync(POWERSHELL_EXE, ["-NoProfile", "-NonInteractive", "-Command", "(Get-NetTCPConnection -LocalPort 63256 -ErrorAction SilentlyContinue | Measure-Object).Count"], { timeout: 15000, encoding: "utf8", windowsHide: true }).trim();
    odUp = parseInt(n, 10) > 0;
  } catch {}
  checks.push({ level: odUp ? OK : INFO, title: "OpenDesign MCP", detail: odUp ? "OD daemon 运行中（63256），open_design 工具可用" : "OD 未启动 → open_design MCP 断开（需要时启动 OpenDesign）", fix: null });
  // 3. .dsh 数据体积（用 DSH_HOME，不能写死某个用户名）
  try {
    const dshHomePs = String(DSH_HOME).replace(/'/g, "''");
    const r = execFileSync(
      POWERSHELL_EXE,
      ["-NoProfile", "-NonInteractive", "-Command",
        `[math]::Round((Get-ChildItem -LiteralPath '${dshHomePs}' -Recurse -Force -ErrorAction SilentlyContinue | Measure-Object Length -Sum).Sum/1GB, 1)`],
      { timeout: 40000, encoding: "utf8", windowsHide: true },
    ).trim();
    const sizeGB = parseFloat(r);
    if (!Number.isFinite(sizeGB)) {
      // 查询失败时不能假装是 0 GB 全绿，否则磁盘真爆了也看不出来。
      checks.push({ level: INFO, title: ".dsh 数据体积", detail: `无法读取 ${DSH_HOME}（PowerShell 返回空值）`, fix: null });
    } else {
      checks.push({ level: sizeGB > 6 ? INFO : OK, title: ".dsh 数据体积", detail: sizeGB + " GB" + (sizeGB > 6 ? "（偏大，可清理旧日志/缓存）" : ""), fix: null });
    }
  } catch (e) {
    checks.push({ level: INFO, title: ".dsh 数据体积查询失败", detail: briefError(e), fix: null });
  }
  return checks;
}

function checkModelVersions() {
  const checks = [];
  // LOCALAPPDATA 才是 Ollama 的默认安装位置；写死 ~ 换用户就查不到。
  const OLLAMA_EXE = join(process.env.LOCALAPPDATA || join(HOME, "AppData", "Local"), "Programs", "Ollama", "ollama.exe");

  let localVer = "";
  try {
    localVer = execFileSync(OLLAMA_EXE, ["--version"], { timeout: 15000, encoding: "utf8", windowsHide: true }).trim();
  } catch {}
  let latestVer = "";
  try {
    const r = execFileSync("curl", ["-s", "--max-time", "10", "https://api.github.com/repos/ollama/ollama/releases/latest"], { timeout: 15000, encoding: "utf8", windowsHide: true });
    const j = JSON.parse(r);
    latestVer = String(j.tag_name || "").replace(/^v/, "");
  } catch {}
  const localNum = (localVer.match(/(\d+\.\d+\.\d+)/) || [])[1] || "";
  if (localNum && latestVer && cmpVer(localNum, latestVer) < 0) {
    checks.push({ level: WARN, title: "Ollama 版本可升级", detail: "本地 " + localNum + " < 最新 " + latestVer, fix: null });
  } else {
    checks.push({ level: OK, title: "Ollama 版本", detail: (localNum || "?") + (latestVer ? "（最新 " + latestVer + "）" : ""), fix: null });
  }

  let models = [];
  try {
    const r = execFileSync(OLLAMA_EXE, ["list"], { timeout: 15000, encoding: "utf8", windowsHide: true });
    models = (r || "").split(/\r?\n/).slice(1).map((l) => l.trim().split(/\s+/)[0]).filter(Boolean);
  } catch {}
  const vl = models.find((m) => /vl/i.test(m));
  checks.push({
    level: vl ? OK : INFO,
    title: "本地视觉模型",
    detail: vl
      ? vl + "（升级：ollama pull " + vl + " 或新版 + 设 DSH_VISION_MODEL）"
      : "未安装（可选：智谱 API 已是主通道，需要离线兜底再 ollama pull qwen2.5vl:7b）",
    fix: null,
  });
  checks.push({ level: INFO, title: "智谱模型可配", detail: "设环境变量 DSH_VISION_ZHIPU_MODEL=<新版模型名> 即可升级（智谱发布 GLM 新版本时改一行）", fix: null });
  return checks;
}

function psDate(v) {
  if (v == null) return 0;
  if (typeof v === "number") return v;
  const m = String(v).match(/\/Date\((-?\d+)\)\//);
  if (m) return Number(m[1]);
  const t = new Date(v).getTime();
  return Number.isFinite(t) ? t : 0;
}

/**
 * 计划任务的统一解读：结果码、上次/下次时间、"从未运行"哨兵。
 * checkTasks 与 checkAutomation 共用，避免两处判据漂移；key 让守护巡检
 * 把同一个任务的重复告警合并成一条。
 */
const TASK_RESULT_TEXT = {
  0: "成功",
  267009: "运行中",
  267010: "运行中（长任务）",
  267011: "尚未运行",
  2147942404: "程序不存在",
  3221225786: "被中断（Ctrl+C/任务被停止）",
};
const TASK_NEVER_BEFORE = Date.UTC(2000, 0, 1);

function taskStatus(t) {
  const name = String(t.name || "?");
  const code = Number(t.result ?? 0);
  const last = psDate(t.last);
  const next = psDate(t.next);
  const never = !last || last < TASK_NEVER_BEFORE;
  const state = String(t.state || "");
  const txt = TASK_RESULT_TEXT[code] || `0x${(code >>> 0).toString(16).toUpperCase()}`;
  const desc =
    `上次 ${never ? "从未" : fmtTime(last)}，结果 ${code}（${txt}），` +
    `下次 ${next ? fmtTime(next) : "未排期"}`;
  // 告警 key 要带上问题类型/结果码：同一任务从"已禁用"变成"执行失败"时，
  // 旧告警要先被清掉，否则 guardSummary 会一直显示过期标题。
  const healthy = code === 0 || code === 267009 || code === 267010;
  const kind = state === "Disabled" ? "disabled" : code === 267011 && never ? "notrun" : healthy ? "ok" : `failed:${code}`;
  return { name, code, last, next, never, state, txt, desc, key: `sched:${name}:${kind}` };
}

/**
 * 用户主动停用的任务不算故障，不该每轮报警。
 * 期望清单放数据文件，改配置不用改代码：
 *   D:\work\自进化\task-expectations.json
 *   { "expectedDisabled": { "任务名": "为什么停用" } }
 * 只有"在清单里 + 状态 Disabled"才静音；新停掉的任务照旧报警。
 * 文件不存在/坏了 = 什么都不静音（fail-open 到"照旧报"，宁可吵也别漏）。
 */
const TASK_EXPECTATIONS_FILE = join("D:\work", "自进化", "task-expectations.json");
let taskExpectCache = { mtime: -1, map: {} };
function expectedDisabled(name) {
  try {
    const st = statSync(TASK_EXPECTATIONS_FILE);
    if (st.mtimeMs !== taskExpectCache.mtime) {
      const raw = JSON.parse(readFileSync(TASK_EXPECTATIONS_FILE, "utf8"));
      const map = raw && typeof raw.expectedDisabled === "object" && raw.expectedDisabled ? raw.expectedDisabled : {};
      taskExpectCache = { mtime: st.mtimeMs, map };
    }
    return taskExpectCache.map[name] || null;
  } catch {
    return null;
  }
}

function checkTasks(verbose = false) {
  const out = [];
  let raw;
  try {
    raw = ps(
      `$ErrorActionPreference='SilentlyContinue';` +
        `Get-ScheduledTask -TaskName 'DSH-*' | ForEach-Object {` +
        `$i=Get-ScheduledTaskInfo -TaskName $_.TaskName;` +
        `[pscustomobject]@{ name=$_.TaskName; state=[string]$_.State; last=$i.LastRunTime; result=$i.LastTaskResult; next=$i.NextRunTime }` +
        `} | ConvertTo-Json -Compress`,
    );
  } catch (e) {
    return [{ level: WARN, title: "计划任务查询失败", detail: briefError(e), fix: null }];
  }
  if (!raw) return [{ level: INFO, title: "没有 DSH-* 计划任务", detail: "自动化尚未注册", fix: null }];

  let list;
  try {
    list = JSON.parse(raw);
  } catch {
    return [{ level: WARN, title: "计划任务输出无法解析", detail: raw.slice(0, 160), fix: null }];
  }
  if (!Array.isArray(list)) list = [list];

  const muted = [];
  for (const t of list) {
    const { name, code, never, state, desc, key } = taskStatus(t);
    if (state === "Disabled") {
      const why = expectedDisabled(name);
      if (why) {
        // 已知停用：默认只在末尾合并一行，verbose（only=tasks）时逐条给原因
        muted.push(`${name}（${why}）`);
        if (verbose) {
          out.push({ level: INFO, title: `计划任务已停用（已知）：${name}`, detail: `${desc}｜停用原因：${why}`, fix: null, key });
        }
        continue;
      }
      out.push({ level: WARN, title: `计划任务已禁用：${name}`, detail: desc, fix: `schtasks /Change /TN "${name}" /ENABLE`, key });
    } else if (code === 267011 && never) {
      out.push({ level: INFO, title: `计划任务 ${name} 尚未跑过`, detail: desc, fix: `schtasks /Run /TN "${name}" 手动触发一次确认能跑`, key });
    } else if (code === 0 || code === 267009 || code === 267010) {
      out.push({ level: OK, title: `计划任务 ${name}`, detail: desc, key });
    } else {
      out.push({ level: WARN, title: `计划任务上次失败：${name}`, detail: desc, fix: `schtasks /Run /TN "${name}" 然后看它的 log`, key });
    }
  }
  if (muted.length) {
    out.push({
      level: INFO,
      title: `已停用的计划任务 ${muted.length} 个（用户主动，不算故障）`,
      detail: `${muted.join("；")}｜要恢复：schtasks /Change /TN "<名字>" /ENABLE`,
      fix: null,
      key: "sched:muted",
    });
  }
  return out;
}

/* ================================================================ */
/* 6. deep：复用 check.mjs 的全量检查                               */
/* ================================================================ */

function checkDeep() {
  try {
    statSync(CHECK_MJS);
  } catch {
    return [{ level: INFO, title: "deep 检查不可用", detail: `找不到 ${CHECK_MJS}`, fix: null }];
  }
  let txt;
  try {
    txt = execFileSync(NODE_BIN, [CHECK_MJS, "--no-network", "--recent-hours=24"], {
      encoding: "utf8",
      timeout: 90000,
      windowsHide: true,
      cwd: ITERATE_DIR,
    });
  } catch (e) {
    // exit 1/2 是 check.mjs 在报 WARN/FAIL，stdout 里有完整明细；
    // 不能当成"执行失败"把真正的检查结果吞掉。
    const code = typeof e.status === "number" ? e.status : -1;
    if ((code === 1 || code === 2) && e.stdout) {
      txt = String(e.stdout);
    } else {
      return [{ level: WARN, title: "check.mjs 执行失败", detail: briefError(e), fix: `cd "${ITERATE_DIR}" && node check.mjs --no-network` }];
    }
  }

  // 只摘出 WARN/FAIL 行，避免整段塞回上下文
  const lines = txt.split("\n").filter((l) => /^\[(WARN|FAIL)\]/.test(l.trim()) || /^摘要:/.test(l.trim()));
  if (lines.length === 0) return [{ level: OK, title: "check.mjs 全量检查", detail: "无 WARN/FAIL", fix: null }];
  const summary = txt.split("\n").find((l) => l.startsWith("摘要:")) || "";
  return [
    {
      level: summary.includes("FAIL=0") && summary.includes("WARN=0") ? OK : WARN,
      title: "check.mjs 全量检查",
      detail: summary.trim(),
      fix: null,
    },
    ...lines.filter((l) => l.startsWith("[WARN]") || l.startsWith("[FAIL]")).map((l) => ({
      level: l.startsWith("[FAIL]") ? FAIL : WARN,
      title: "check.mjs",
      detail: l.replace(/^\[(WARN|FAIL)\]\s*/, "").trim(),
      fix: null,
    })),
  ];
}

/* ================================================================ */
/* 7. automation：插件 × 自动化任务覆盖矩阵                          */
/* ================================================================ */
// 登记「有哪些自动化任务、各服务哪些插件」。新增任务时在这里补一行，矩阵才认得；
// 不登记的任务不会出现在覆盖统计里，但也不会被当成异常。
const AUTOMATION_MAP = [
  { task: "DSH-Memory-Weekly-Iterate", plugins: ["dsh-memory"], purpose: "记忆插件每周复盘并自我迭代" },
  { task: "DSH-Plugin-Iterate", plugins: ["dsh-ops", "billion-context"], purpose: "两个底座的配置体检 + 自动修复" },
  { task: "DSH-Plugin-Check", plugins: ["dsh-ops", "billion-context"], purpose: "配置漂移与运行时一致性巡检" },
  { task: "DSH-EnvDoctor-Iterate", plugins: ["@local/dsh-env-doctor"], purpose: "大内总管每月自检并自我迭代" },
];


/** 真正注册到系统里的计划任务（名字 → {state, code, last, next}）。 */
function readScheduledTasks() {
  const raw = ps(
    `$ErrorActionPreference='SilentlyContinue';` +
      `Get-ScheduledTask -TaskName 'DSH-*' | ForEach-Object {` +
      `$i=Get-ScheduledTaskInfo -TaskName $_.TaskName;` +
      `[pscustomobject]@{ name=$_.TaskName; state=[string]$_.State; last=$i.LastRunTime; result=$i.LastTaskResult; next=$i.NextRunTime }` +
      `} | ConvertTo-Json -Compress`,
  );
  if (!raw) return new Map();
  let list;
  try {
    list = JSON.parse(raw);
  } catch {
    return new Map();
  }
  if (!Array.isArray(list)) list = [list];
  return new Map(list.map((t) => [String(t.name), t]));
}

function pluginNames() {
  try {
    const pkg = readJson(join(PROFILE_DIR, "package.json"));
    const bundles = pkg?.dsh?.profile?.bundles || [];
    const deps = pkg?.dependencies || {};
    return bundles
      .filter((n) => !BUILTIN.test(String(n)) && isDeclaredDependency(String(n), deps))
      .map((n) => {
        const spec = String(deps[n] ?? "");
        const entry = pluginEntry(n);
        let kind = "npm";
        if (spec.startsWith("link:") || spec.startsWith("workspace:")) kind = "link";
        else if (spec.startsWith("file:")) kind = "file";
        return { name: String(n), version: entry.version, kind, missing: entry.missing };
      });
  } catch {
    return [];
  }
}

function checkAutomation() {
  const out = [];
  const tasks = readScheduledTasks();
  const plugins = pluginNames();
  if (plugins.length === 0) {
    return [{ level: WARN, title: "插件清单不可读", detail: `检查 ${join(PROFILE_DIR, "package.json")}`, fix: null }];
  }

  const covered = new Map(); // 插件名 → [任务名]

  for (const def of AUTOMATION_MAP) {
    const t = tasks.get(def.task);
    if (!t) {
      // 任务登记了却没注册：对通配任务只提示，对专属任务算掉了
      const targeted = def.plugins.filter((p) => p !== "*");
      out.push({
        level: def.plugins.includes("*") ? INFO : WARN,
        title: `自动化任务未注册：${def.task}`,
        detail: `${def.purpose}${targeted.length ? `（服务 ${targeted.join("、")}）` : ""}`,
        fix: `重新运行对应的 register 脚本`,
      });
      continue;
    }
    const { code, never, state, desc, key } = taskStatus(t);

    if (state === "Disabled") {
      out.push({ level: WARN, title: `自动化任务已禁用：${def.task}`, detail: `${def.purpose}｜${desc}`, fix: `schtasks /Change /TN "${def.task}" /ENABLE`, key });
    } else if (code === 267011 && never) {
      out.push({ level: INFO, title: `自动化任务 ${def.task} 尚未跑过`, detail: `${def.purpose}｜${desc}`, fix: `schtasks /Run /TN "${def.task}"`, key });
    } else if (code !== 0 && code !== 267009 && code !== 267010) {
      out.push({
        level: WARN,
        title: `自动化任务上次失败：${def.task}`,
        detail: `${def.purpose}｜${desc}`,
        fix: `照旧用 schtasks /Run /TN "${def.task}" 重跑（直接调脚本不会更新任务记录）`,
        key,
      });
    } else {
      out.push({ level: OK, title: `自动化任务 ${def.task}`, detail: `${def.purpose}｜${desc}`, key });
    }

    for (const p of def.plugins) {
      if (p === "*") {
        for (const pl of plugins) {
          if (!covered.has(pl.name)) covered.set(pl.name, []);
          covered.get(pl.name).push(def.task);
        }
      } else if (plugins.some((x) => x.name === p)) {
        if (!covered.has(p)) covered.set(p, []);
        covered.get(p).push(def.task);
      }
    }
  }

  const uncovered = plugins.filter((p) => !covered.has(p.name));
  const coveredCount = plugins.length - uncovered.length;
  out.push({
    level: OK,
    title: "自动化覆盖",
    detail: `${plugins.length} 个本地插件，${coveredCount} 个有定时任务覆盖，${uncovered.length} 个只靠手动调大内总管`,
  });
  if (uncovered.length) {
    out.push({
      level: INFO,
      title: "没有专属定时任务的插件",
      detail: `${uncovered.map((p) => `${p.name}@${p.version}${p.kind === "link" ? "[link]" : ""}`).join("、")}——纯 UI/一次性插件没有运行时状态，每天查也是同一个「正常」，不需要定时任务`,
      fix: null,
    });
  }
  return out;
}

/* ================================================================ */
/* 8. health：插件能不能真的加载（入口解析 + 动态 import 自检）       */
/* ================================================================ */

const ENTRY_CANDIDATES = ["index.js", "index.mjs", "lib/index.js", "dist/index.js", "main.js"];

/**
 * 判断这个包到底是「插件本体」还是「纯配置 bundle」。
 * 判据：看它自己的 dsh.bundle.patch 里 insert 的 name 是不是自己——
 * 是 → 它自己就是插件，必须有 apply/default；
 * 不是（插的是 dsh-mcp-client、dsh-skill-filesystem 之类）→ 纯配置/资源 bundle，没有 JS 入口是设计如此。
 */
function classifyBundle(dir, pkg) {
  const patchRel = pkg?.dsh?.bundle?.patch;
  if (!patchRel) return { isBundle: false, patchPath: null, selfYaml: null, names: [] };
  const patchPath = join(dir, patchRel);
  let text = "";
  try {
    text = readFileSync(patchPath, "utf8");
  } catch {
    return { isBundle: true, patchPath, selfYaml: null, names: [], error: "patch 文件不可读" };
  }
  const names = [...text.matchAll(/^\s*-?\s*name:\s*['"]?([^'"\s#]+)['"]?\s*$/gm)].map((m) => m[1]);
  // 「自己」的三种写法：包名、包名/子路径（dsh-ops/shell）、包内相对路径（./index.js，cc-safety-net 这种）
  const selfName = pkg?.name;
  const selfYaml = names.some(
    (n) => n === selfName || (selfName && n.startsWith(`${selfName}/`)) || n.startsWith("."),
  );
  return { isBundle: true, patchPath, selfYaml, names };
}

/** 按 package.json 的 exports/main 解出入口文件；都没有再猜常见位置。 */
function resolveEntry(dir, pkg) {
  const exp = pkg?.exports;
  if (typeof exp === "string") return join(dir, exp);
  if (exp && typeof exp === "object") {
    const dot = exp["."];
    if (typeof dot === "string") return join(dir, dot);
    if (dot && typeof dot === "object") {
      const imp = dot.import ?? dot.default ?? dot.node;
      if (typeof imp === "string") return join(dir, imp);
      if (imp && typeof imp === "object" && typeof imp.default === "string") return join(dir, imp.default);
    }
  }
  if (typeof pkg?.main === "string") return join(dir, pkg.main);
  for (const c of ENTRY_CANDIDATES) {
    const p = join(dir, c);
    try {
      statSync(p);
      return p;
    } catch {
      /* 继续猜 */
    }
  }
  return null;
}

async function checkPluginHealth() {
  const plugins = pluginNames();
  const out = [];
  const configOnly = [];
  let okCount = 0;
  let skipped = 0;

  for (const p of plugins) {
    if (p.missing) {
      out.push({
        level: FAIL,
        title: `插件目录缺失：${p.name}`,
        detail: p.kind === "link" ? "link 指向的目录不在了（源码被移动/删除）" : "node_modules 里没有这个包",
        fix: p.kind === "link" ? `重新 link 或 plugin_manager install_bundle ${p.name}` : `plugin_manager install_bundle ${p.name}`,
      });
      continue;
    }
    const dir = join(PROFILE_DIR, "node_modules", p.name);
    let pkg;
    try {
      pkg = readJson(join(dir, "package.json"));
    } catch (e) {
      out.push({ level: FAIL, title: `package.json 不可读：${p.name}`, detail: briefError(e), fix: "重装这个插件" });
      continue;
    }
    const kind = classifyBundle(dir, pkg);
    // 纯配置 bundle：patch 插入的是别人的插件，自己没有 JS 入口是设计如此。
    if (kind.isBundle && kind.selfYaml === false) {
      if (kind.error) {
        out.push({ level: FAIL, title: `bundle patch 坏了：${p.name}`, detail: kind.error, fix: "确认 dsh.bundle.patch 指向的文件存在" });
      } else {
        configOnly.push(p.name);
        okCount++;
      }
      continue;
    }

    const entry = resolveEntry(dir, pkg);
    if (!entry) {
      out.push({
        level: WARN,
        title: `找不到入口：${p.name}`,
        detail: kind.selfYaml ? "patch 里插入的是它自己（说明是插件），但没有可加载的 JS 入口" : "没有 dsh.bundle.patch，也没有可用的 exports / main",
        fix: null,
      });
      continue;
    }
    try {
      statSync(entry);
    } catch {
      out.push({ level: FAIL, title: `入口文件不存在：${p.name}`, detail: entry, fix: "重装这个插件" });
      continue;
    }
    let mod;
    try {
      mod = await import(pathToFileURL(entry).href);
    } catch (e) {
      const msg = briefError(e);
      // DSH 的 @deepseek-ai/* 包在 app.asar 里，普通 import() 看不见；这类
      // peer 依赖缺失不代表插件坏了，不能报 WARN 让用户去重装。
      const missing = (msg.match(/Cannot find (?:module|package) '([^']+)'/i) || [])[1] || "";
      if (/^@deepseek-ai\//.test(missing)) {
        skipped += 1;
        out.push({
          level: INFO,
          title: `模块加载跳过：${p.name}`,
          detail: `依赖 ${missing} 由 DSH 运行时提供，独立 import 无法验证（不代表插件坏了）`,
          fix: null,
        });
        continue;
      }
      const dep = /Cannot find (module|package)|ERR_MODULE_NOT_FOUND/i.test(msg);
      out.push({
        level: WARN,
        title: `模块加载失败：${p.name}`,
        detail: `${dep ? "依赖解析不到（多半是装的包不完整）" : "顶层代码抛错"}｜${msg}`,
        fix: dep ? `plugin_manager install_bundle ${p.name} 重装` : null,
      });
      continue;
    }
    const hasApply = typeof mod.apply === "function";
    const hasDefault = mod.default !== undefined;
    if (!hasApply && !hasDefault) {
      out.push({
        level: WARN,
        title: `导出形态可疑：${p.name}`,
        detail: `既没有 apply() 也没有 default 导出（DSH 会忽略它）｜实际导出 ${Object.keys(mod).slice(0, 6).join(",") || "(空)"}`,
        fix: null,
      });
    } else {
      okCount++;
    }
  }

  out.unshift({
    level: brokenCount(out) ? WARN : OK,
    title: "插件加载自检",
    detail: `${plugins.length} 个本地插件，${okCount} 个能正常加载${configOnly.length ? `（含 ${configOnly.length} 个纯配置 bundle，本来就没有 JS 入口）` : ""}${skipped ? `，${skipped} 个依赖 DSH 运行时（独立 import 跳过）` : ""}${brokenCount(out) ? `，${brokenCount(out)} 个有问题（见下）` : ""}`,
    fix: null,
  });
  return out;
}

function brokenCount(checks) {
  return checks.filter((c) => c.level === FAIL || c.level === WARN).length;
}

/* ================================================================ */
/* 8.6 插件风险扫描（只读，不改第三方源码）                           */
/* ================================================================ */

const RISK_SCRIPT_KEYS = ["preinstall", "install", "postinstall", "prepare"];
const RISK_PATTERNS = [
  { re: /\bchild_process\b|\bexecSync\s*\(|\bexecFileSync\s*\(|\bspawnSync\s*\(/, why: "子进程/命令执行" },
  { re: /\brmSync\s*\(|\bunlinkSync\s*\(|\brmdirSync\s*\(|rm\s+-rf|rimraf\s*\(/, why: "删除文件/目录" },
  { re: /\bfetch\s*\(|\bhttps?\.request\s*\(|\bnet\.connect\s*\(/, why: "网络请求" },
  { re: /\beval\s*\(|new\s+Function\s*\(/, why: "动态代码执行" },
];

/** 收集插件目录里的源码文件（跳过 node_modules/dist，最多 40 个、每个 ≤400KB）。 */
function walkPluginJs(dir, out = [], depth = 0) {
  if (depth > 3 || out.length >= 40) return out;
  let entries;
  try {
    entries = readdirSync(dir, { withFileTypes: true });
  } catch {
    return out;
  }
  for (const e of entries) {
    if (out.length >= 40) break;
    if (e.name === "node_modules" || e.name === ".git" || e.name === "dist" || e.name === "iterate" || e.name === "test" || e.name === "tests" || e.name === "__tests__" || e.name === "bench") continue;
    const p = join(dir, e.name);
    if (e.isDirectory()) {
      walkPluginJs(p, out, depth + 1);
      continue;
    }
    if (!/\.(js|mjs|cjs)$/i.test(e.name)) continue;
    if (/^(test-|.*\.test\.|.*\.spec\.)/i.test(e.name)) continue;
    try {
      if (statSync(p).size > 400 * 1024) continue;
    } catch {
      continue;
    }
    out.push(p);
  }
  return out;
}

/** 插件风险扫描：安装脚本 / exports 悬空 / 源码敏感调用。只出证据，不动第三方源码。 */
function checkPluginRisk() {
  let pkg;
  try {
    pkg = readJson(PROFILE_PKG);
  } catch {
    return [{ level: WARN, title: "风险扫描跳过", detail: "profile package.json 不可读", fix: null }];
  }
  const deps = pkg?.dependencies || {};
  const names = Object.keys(deps).filter((n) => /^(dsh-|@local\/dsh-|@dsh-)/.test(n));
  const out = [];
  let scanned = 0;
  for (const name of names) {
    const spec = String(deps[name] ?? "");
    const dir = spec.startsWith("link:") ? spec.slice(5) : join(PROFILE_DIR, "node_modules", name);
    // 自研插件（link 到 D:\work）不参与"第三方"风险扫描：自家代码，风险由迭代流程管
    if (/^E:[\\/]DS公作区/i.test(String(dir))) continue;
    if (!existsSync(join(dir, "package.json"))) continue;
    scanned += 1;
    let p;
    try {
      p = readJson(join(dir, "package.json"));
    } catch {
      continue;
    }
    // 1) 安装脚本：会在安装时执行，必须让人看见
    const scripts = p?.scripts || {};
    const risky = RISK_SCRIPT_KEYS.filter((k) => typeof scripts[k] === "string" && scripts[k].trim());
    if (risky.length) {
      out.push({
        level: WARN,
        title: `插件带安装脚本：${name}`,
        detail: risky.map((k) => `${k}: ${scripts[k].slice(0, 120)}`).join("｜"),
        fix: "只读提示：安装脚本会在安装时执行，确认内容可信再装",
      });
    }
    // 2) exports 指向的文件是否真实存在
    const targets = [];
    const collect = (v) => {
      if (typeof v === "string") targets.push(v);
      else if (v && typeof v === "object") for (const x of Object.values(v)) collect(x);
    };
    collect(p?.exports);
    const dangling = targets
      .filter((t) => t.startsWith("./") && !t.includes("*"))
      .filter((t) => !existsSync(join(dir, t)));
    if (dangling.length) {
      out.push({
        level: WARN,
        title: `exports 指向的文件不存在：${name}`,
        detail: dangling.slice(0, 3).join("｜"),
        fix: "插件包可能不完整，重装或确认版本",
      });
    }
    // 3) 源码危险调用（只出前 3 条证据，避免刷屏）
    const hits = [];
    for (const file of walkPluginJs(dir)) {
      let text;
      try {
        text = readFileSync(file, "utf8");
      } catch {
        continue;
      }
      const lines = text.split(/\r?\n/);
      for (let i = 0; i < lines.length && hits.length < 6; i += 1) {
        for (const pat of RISK_PATTERNS) {
          if (pat.re.test(lines[i])) {
            hits.push(`${file.slice(dir.length + 1)}:${i + 1} [${pat.why}] ${lines[i].trim().slice(0, 80)}`);
            break;
          }
        }
      }
      if (hits.length >= 6) break;
    }
    if (hits.length) {
      out.push({
        level: INFO,
        title: `插件源码含敏感调用：${name}`,
        detail: hits.slice(0, 3).join("\n"),
        fix: null,
      });
    }
  }
  const warnCount = out.filter((c) => c.level === WARN).length;
  const infoCount = out.filter((c) => c.level === INFO).length;
  out.unshift({
    level: warnCount ? WARN : infoCount ? INFO : OK,
    title: "插件风险扫描",
    detail: `${scanned} 个第三方插件：${warnCount ? `${warnCount} 个有安装脚本/悬空 exports（需人工确认）` : "无安装脚本、无悬空 exports"}${infoCount ? `；${infoCount} 个源码含敏感调用（子进程/删除/网络/动态执行，见下）` : ""}`,
    fix: null,
  });
  return out;
}

/* ================================================================ */
/* 8.5 客户端 bundle 一致性：防「打开就崩 / 图标不出现」            */
/* ================================================================ */

/** 定位 bundle 包目录（内置包在 DSH 应用里，第三方/自研在 profile node_modules）。 */
function locateBundleDir(name, deps) {
  if (name.startsWith("@deepseek-ai/")) {
    const appRoot = process.resourcesPath ? join(process.resourcesPath, "app") : "";
    const p = appRoot ? join(appRoot, "node_modules", name) : "";
    return p && existsSync(join(p, "package.json")) ? p : null;
  }
  const p = join(PROFILE_DIR, "node_modules", name);
  if (existsSync(join(p, "package.json"))) return p;
  const spec = deps[name];
  if (typeof spec === "string" && spec.startsWith("link:")) {
    const p2 = spec.slice(5);
    if (existsSync(join(p2, "package.json"))) return p2;
  }
  // 桌面版随包发布的 bundle（如 dsh-community-market）在应用自己的 node_modules 里，
  // 由 Loader 从应用 baseUrl 解析，不算「profile 里装坏了」。
  const appRoot = process.resourcesPath ? join(process.resourcesPath, "app") : "";
  const p3 = appRoot ? join(appRoot, "node_modules", name) : "";
  if (p3 && existsSync(join(p3, "package.json"))) return p3;
  return null;
}

function checkClientBundles() {
  let pkg;
  try {
    pkg = readJson(PROFILE_PKG);
  } catch (e) {
    return [{ level: WARN, title: "bundle 清单不可读", detail: briefError(e), fix: null }];
  }
  const bundles = pkg?.dsh?.profile?.bundles || [];
  const deps = pkg?.dependencies || {};
  const failed = [];
  const clientOk = [];
  let builtinCount = 0;
  for (const name of bundles) {
    // @deepseek-ai 内置 bundle 随 DSH 应用发布，Loader 从应用自己的 baseUrl 解析，
    // 不在 profile node_modules；它们不参与「第三方插件装坏」的判定。
    if (name.startsWith("@deepseek-ai/")) { builtinCount += 1; continue; }
    const dir = locateBundleDir(name, deps);
    if (!dir) { failed.push(`${name}：包目录不存在`); continue; }
    let m;
    try { m = readJson(join(dir, "package.json")); } catch { failed.push(`${name}：package.json 不可读`); continue; }
    const decl = m?.dsh?.client;
    if (!decl) continue; // 纯 host 插件不校验浏览器端
    if (decl.platform !== undefined && decl.platform !== "web") { failed.push(`${name}：dsh.client.platform 非 web`); continue; }
    const exportsMap = m.exports;
    const hasClientExport = !!(exportsMap && typeof exportsMap === "object" && exportsMap["./client"] !== undefined);
    if (!hasClientExport) { failed.push(`${name}：声明 dsh.client 但 exports 缺 "./client"（启动会崩）`); continue; }
    let rel = exportsMap["./client"];
    if (rel && typeof rel === "object") rel = rel.default ?? rel.import ?? rel.require;
    if (typeof rel !== "string") { failed.push(`${name}：exports["./client"] 无法解析`); continue; }
    const clientPath = join(dir, rel);
    if (!existsSync(clientPath)) { failed.push(`${name}：client 文件不存在（${rel}）`); continue; }
    let id = "";
    try {
      const body = readFileSync(clientPath, "utf8");
      const mm = body.match(/__ModuleLoader__\.load\(\{\s*id:\s*['"]([^'"]+)['"]/);
      id = mm ? mm[1] : "";
    } catch { /* 读不到按未注册处理 */ }
    if (!id) { failed.push(`${name}：client 未找到 ModuleLoader.load({id})`); continue; }
    if (id !== m.name) { failed.push(`${name}：注册 id "${id}" ≠ 包名（图标/面板不会出现）`); continue; }
    clientOk.push(m.name);
  }
  if (bundles.length === 0) {
    return [{ level: WARN, title: "bundle 清单为空", detail: PROFILE_PKG, fix: null }];
  }
  if (failed.length === 0) {
    return [{
      level: OK,
      title: "客户端 bundle 一致性",
      detail: `${bundles.length} 个 bundle 入口全部可解析${builtinCount ? `（其中 ${builtinCount} 个 DSH 内置）` : ""}，${clientOk.length} 个带浏览器端 bundle 且注册 id 与包名一致`,
    }];
  }
  return [{
    level: FAIL,
    title: `客户端 bundle 异常 ${failed.length} 个（可能导致打不开 DSH 或图标不出现）`,
    detail: failed.join("；"),
    fix: "修 package.json 的 exports（缺 \"./client\"）或 client.js 里 ModuleLoader.load 的 id（必须等于包名）",
  }];
}

/* ================================================================ */
/* 9. inventory：一屏看清所有插件（类型/健康/覆盖）                  */
/* ================================================================ */

async function checkInventory() {
  const plugins = pluginNames();
  const tasks = readScheduledTasks();
  const covered = new Map();
  for (const def of AUTOMATION_MAP) {
    if (!tasks.has(def.task)) continue;
    for (const p of def.plugins) {
      if (p === "*") continue;
      if (!covered.has(p)) covered.set(p, []);
      covered.get(p).push(def.task.replace(/^DSH-/, ""));
    }
  }

  const rows = [];
  let bad = 0;
  for (const p of plugins) {
    const tag = p.kind === "link" ? "link" : p.kind === "file" ? "file" : "npm";
    let state = "OK";
    if (p.missing) {
      state = "目录缺失";
      bad++;
    } else {
      const dir = join(PROFILE_DIR, "node_modules", p.name);
      let pkg = null;
      try {
        pkg = readJson(join(dir, "package.json"));
      } catch {
        state = "package.json 坏了";
        bad++;
      }
      if (pkg) {
        const kind = classifyBundle(dir, pkg);
        if (kind.isBundle && kind.selfYaml === false) {
          state = "配置bundle";
        } else {
          const entry = resolveEntry(dir, pkg);
          if (!entry) {
            state = "无入口";
            bad++;
          } else {
            try {
              statSync(entry);
            } catch {
              state = "入口缺失";
              bad++;
            }
          }
        }
      }
    }
    const cover = covered.get(p.name);
    rows.push(`${p.name}@${p.version} [${tag}] ${state}${cover ? ` 巡检:${cover.join("+")}` : ""}`);
  }

  return [
    {
      level: bad ? WARN : OK,
      title: `插件档案（${plugins.length} 个本地插件${bad ? `，${bad} 个异常` : "，全部就位"}）`,
      detail: rows.join("\n"),
      fix: null,
    },
  ];
}

/* ================================================================ */
/* 渲染 + 工具                                                      */
/* ================================================================ */

function textOutput() {
  return {
    schema: { type: "string" },
    render: (_args, value) => [{ type: "text", text: String(value) }],
  };
}

const ICON = { OK: "[OK]  ", WARN: "[WARN]", FAIL: "[FAIL]", INFO: "[INFO]" };

function runFix(checks) {
  const done = [];
  for (const c of checks) {
    if (typeof c.autoFix !== "function") continue;
    try {
      c.autoFix();
      c.fixed = true;
      done.push(c.title);
    } catch (e) {
      done.push(`${c.title}（修复失败：${briefError(e)}）`);
    }
  }
  return done;
}

/* ================================================================ */
/* 后台守护巡检（v0.4）                                             */
/* 常驻：DSH 一启动就在后台盯着环境，发现异常才出声，正常时零噪音。 */
/* ================================================================ */

const GUARD_DISABLED = process.env.DSH_ENV_DOCTOR_GUARD === "0";
const GUARD_INTERVAL_MS = 30 * 60 * 1000;
const GUARD_FIRST_DELAY_MS = 90 * 1000;
const GUARD_LOG_FILE = join(ITERATE_DIR, "reports", "guard-log.txt");
// 告警表落在插件自己目录里，用来跨 DSH 重启去重：同一条故障只记一次，
// 恢复时再记一条；否则每重启一次，guard-log 就把旧告警当新告警重写一遍。
const GUARD_STATE_FILE = join(SELF_DIR, ".guard-alerts.json");

const guardAlerts = new Map();
let guardLastRun = 0;
let guardLastError = null;

function logGuard(line) {
  try {
    mkdirSync(dirname(GUARD_LOG_FILE), { recursive: true });
    appendFileSync(GUARD_LOG_FILE, `${new Date().toISOString()} ${line}\n`, "utf8");
  } catch {
    // 日志写不进去不影响巡检本身
  }
}

function loadGuardAlerts() {
  try {
    const raw = JSON.parse(readFileSync(GUARD_STATE_FILE, "utf8"));
    if (!Array.isArray(raw)) return;
    for (const a of raw) {
      if (!a || typeof a.key !== "string" || !a.key) continue;
      if (guardAlerts.size >= 50) break;
      guardAlerts.set(a.key, {
        level: a.level === FAIL ? FAIL : WARN,
        title: String(a.title || "未命名检查"),
        detail: String(a.detail || ""),
        fix: String(a.fix || ""),
        scope: a.scope === "slow" ? "slow" : "fast",
        firstSeen: Number(a.firstSeen) || Date.now(),
      });
    }
  } catch {
    // 首次运行、文件损坏或目录只读：从空告警表开始，不影响巡检
  }
}

function saveGuardAlerts() {
  try {
    writeFileSync(
      GUARD_STATE_FILE,
      JSON.stringify([...guardAlerts].map(([key, a]) => ({ key, ...a }))),
      "utf8",
    );
  } catch {
    // 状态文件写不进去最多让下次重启重复报一次，不影响告警本身
  }
}

/**
 * 常驻巡检：两档频率，覆盖「环境 + 插件 + 配置 + 磁盘」。
 * 快档每 30 分钟（全本地），慢档每 6 小时（计划任务 + npm 版本）。
 */
const GUARD_SLOW_INTERVAL_MS = 6 * 60 * 60 * 1000;
let guardLastSlow = 0;

/** 自动学习任务监控：计划任务状态 / 循环进程 / 日志异常。 */
function checkAutoLearn() {
  const out = [];
  const taskName = "DSH-Auto-Learn";
  const logPath = join("D:\work", "学习计划", "auto-learn-log.txt");
  const tasks = readScheduledTasks();
  const t = tasks.get(taskName);
  if (!t) {
    out.push({ level: WARN, title: `自动学习任务未注册：${taskName}`, detail: "自主编程学习没挂到计划任务，开机不会自动学", fix: "重新注册 DSH-Auto-Learn（LogonTrigger + auto-learn-loop.ps1）", key: "autolearn:task-missing" });
    return out;
  }
  const { code, never, state, desc, key } = taskStatus(t);
  if (state === "Disabled") {
    const why = expectedDisabled(taskName);
    if (why) {
      // 已知停用（用户主动）：不报 WARN，也不重复报——这一项由 checkTasks 的汇总行负责
      return out;
    }
    out.push({ level: WARN, title: `自动学习任务已禁用：${taskName}`, detail: desc, fix: `schtasks /Change /TN "${taskName}" /ENABLE`, key: "autolearn:disabled" });
  } else if (code === 267011 && never) {
    out.push({ level: INFO, title: `自动学习任务尚未跑过：${taskName}`, detail: desc, fix: `schtasks /Run /TN "${taskName}"`, key: "autolearn:never" });
  } else {
    out.push({ level: OK, title: `自动学习任务：${taskName}`, detail: desc, key: "autolearn:task" });
  }
  let loopCount = -1;
  try {
    loopCount = parseInt(ps("(Get-CimInstance Win32_Process -Filter \"Name='powershell.exe'\" | Where-Object { $_.CommandLine -like '*auto-learn-loop*' }).Count", 15000), 10) || 0;
  } catch (e) {
    loopCount = -1;
  }
  if (loopCount === 0 && state !== "Disabled") {
    // 用户要求：循环不在就自动重启，不用人工喊
    let restarted = false;
    try {
      ps(`Start-ScheduledTask -TaskName "${taskName}"`, 20000);
      restarted = true;
    } catch (e) {
      restarted = false;
    }
    if (restarted) {
      out.push({ level: OK, title: "自动学习循环不在，已自动重启", detail: "auto-learn-loop.ps1 未运行，已自动 Start-ScheduledTask 拉起（下次检查确认进程）", key: "autolearn:loop" });
    } else {
      out.push({ level: WARN, title: "自动学习循环不在且自动重启失败", detail: "auto-learn-loop.ps1 未运行，自动重启失败", fix: `Start-ScheduledTask -TaskName "${taskName}"`, key: "autolearn:loop" });
    }
  }
  if (!existsSync(logPath)) {
    out.push({ level: WARN, title: "自动学习日志不存在", detail: `找不到 ${logPath}`, fix: "确认 auto-learn-loop.ps1 正常写日志", key: "autolearn:log-missing" });
    return out;
  }
  try {
    const lines = readFileSync(logPath, "utf8").split(/\r?\n/).filter(Boolean);
    const now = Date.now();
    let errLine = null;
    for (let i = lines.length - 1; i >= 0; i -= 1) {
      if (lines[i].includes("异常:")) { errLine = lines[i]; break; }
    }
    let fresh = false;
    let staleNote = "历史异常已过 30 分钟窗口";
    if (errLine) {
      const m = errLine.match(/\[(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2}):(\d{2})\]/);
      if (m) {
        const ts = new Date(m[1] + "-" + m[2] + "-" + m[3] + "T" + m[4] + ":" + m[5] + ":" + m[6] + "+08:00").getTime();
        fresh = Number.isFinite(ts) && (now - ts) <= 30 * 60 * 1000;
      } else {
        // 没有时间戳无法判断新旧；以前当成“永远新鲜”，一条旧异常能报警一辈子。
        staleNote = "异常行没有时间戳，无法判断新旧";
      }
    }
    if (fresh) {
      out.push({ level: WARN, title: "自动学习最近一轮报错", detail: errLine.slice(0, 160), fix: "看 auto-learn-log.txt 尾部；修好后重跑任务", key: "autolearn:error" });
    } else {
      out.push({ level: OK, title: "自动学习日志无异常", detail: errLine ? (staleNote + "：" + errLine.slice(0, 80)) : ("最后一条：" + (lines[lines.length - 1] || "").slice(0, 120)), key: "autolearn:log" });
    }
  } catch (e) {
    out.push({ level: WARN, title: "自动学习日志读取失败", detail: briefError(e), fix: null, key: "autolearn:log-read" });
  }
  return out;
}

function guardLightChecks(workspace) {
  return [
    ...checkWorkspace(workspace),
    ...checkBili(),
    ...checkPaths(),
    ...checkMemories(),
    ...checkPluginDirs(),
    ...checkPluginDrift(),
    ...checkClientBundles(),
    ...checkDisk(),
    ...checkConfigDrift(),
    ...checkAutoLearn(),
  ];
}

/** 把一轮检查结果并进告警表；scope 区分快/慢档，各自清理互不干扰。 */
function absorbGuardChecks(checks, scope) {
  const alive = new Set();
  let changed = false;
  for (const c of checks) {
    if (c.level !== FAIL && c.level !== WARN) continue;
    const title = String(c.title || "未命名检查");
    // 同一个根因可能被两个检查组各报一次（如 checkTasks 和 checkAutomation
    // 都会报某个计划任务失败）；带 key 的结果按根因合并，只留一条告警。
    const key = `${scope}:${c.key || title}`;
    alive.add(key);
    const detail = c.detail == null ? "" : String(c.detail);
    const fix = c.fix == null ? "" : String(c.fix);
    const existing = guardAlerts.get(key);
    if (existing) {
      // 同一条告警还在：只刷新级别/详情，不重复写日志。重启后从状态文件
      // 读回来的告警也走这里，所以不会把旧问题当成“新告警”再刷一遍。
      if (existing.level !== c.level || existing.detail !== detail || existing.fix !== fix) {
        existing.level = c.level;
        existing.detail = detail;
        existing.fix = fix;
        changed = true;
      }
      continue;
    }
    guardAlerts.set(key, {
      level: c.level,
      title,
      detail,
      fix,
      scope,
      firstSeen: Date.now(),
    });
    changed = true;
    logGuard(`[${c.level}] 新告警：${title}${detail ? ` — ${detail.split("\n")[0]}` : ""}`);
  }
  for (const [key, alert] of [...guardAlerts]) {
    if (alert.scope !== scope) continue;
    if (alive.has(key)) continue;
    guardAlerts.delete(key);
    changed = true;
    logGuard(`[恢复] ${alert.title}`);
  }
  if (changed) saveGuardAlerts();
}

async function guardSlowTick(workspace) {
  guardLastSlow = Date.now();
  try {
    const checks = [...checkTasks(), ...checkAutomation(), ...checkToolchain()];
    checks.push(...(await checkPlugins({ noNetwork: false })));
    absorbGuardChecks(checks, "slow");
  } catch (e) {
    logGuard(`[guard-slow-error] 慢档巡检失败：${briefError(e)}`);
  }
}

function guardTick(workspace) {
  if (guardAlerts.size > 50) {
    guardAlerts.clear();
    saveGuardAlerts();
  }
  try {
    absorbGuardChecks(guardLightChecks(workspace), "fast");
    guardLastRun = Date.now();
    guardLastError = null;
  } catch (e) {
    guardLastError = briefError(e);
    logGuard(`[guard-error] 巡检本身失败：${guardLastError}`);
    return;
  }
  if (Date.now() - guardLastSlow >= GUARD_SLOW_INTERVAL_MS) {
    void guardSlowTick(workspace);
  }
}

function guardSummary() {
  if (guardAlerts.size === 0) return "";
  const items = [...guardAlerts.values()]
    .slice(0, 6)
    .map((a) => `- [${a.level}] ${a.title}`);
  const more = guardAlerts.size > 6 ? `\n- ……另有 ${guardAlerts.size - 6} 条` : "";
  return `\n\n【大内总管后台巡检告警 ${guardAlerts.size} 条，最近巡检 ${fmtTime(guardLastRun)}】\n${items.join("\n")}${more}\n有告警先调 env_doctor only=all 看详情；要清掉告警需要先排除原因。`;
}

export const apply = (ctx, config) => {
  const defaultWorkspace = String(config?.workspace || process.cwd());

  const systemPrompt = ctx.get?.("systemPrompt");
  if (systemPrompt !== undefined) {
    systemPrompt.section({
      name: "dsh-env-doctor",
      order: 9,
      text: () =>
        "环境或插件出怪问题（沙箱 ACL 拒绝、配置改完不生效、插件版本/状态可疑、插件装完没反应、自动化任务没在跑）时先找大内总管（env_doctor）；怀疑某个插件坏了用 only=health 当场验证能不能加载。" +
        guardSummary(),
    });
  }

  if (!GUARD_DISABLED) {
    loadGuardAlerts();
    captureConfigBaseline();
    ctx.effect(() => {
      const first = setTimeout(() => guardTick(defaultWorkspace), GUARD_FIRST_DELAY_MS);
      const timer = setInterval(() => guardTick(defaultWorkspace), GUARD_INTERVAL_MS);
      if (typeof first.unref === "function") first.unref();
      if (typeof timer.unref === "function") timer.unref();
      logGuard("守护巡检已启动（首次 90s 后，快档每 30 分钟、慢档每 6 小时）");
      return () => {
        clearTimeout(first);
        clearInterval(timer);
        // 正常热重载也会走这里，不记日志，免得把真正的告警刷没
      };
    }, "dsh-env-doctor: guard");
  }

  ctx.tools.register({
    name: "env_doctor",
    description:
      "大内总管（Env Doctor）：一条命令把 DSH 的运行状态查清楚。默认查工作区沙箱前置、billion-context sidecar 是否重读配置、目录可写性、计划任务是否还活着；only=changes 查插件增减/升级（自动与上次基线对比，装任何插件都会被它发现）；only=plugins 查全部 bundle 的版本与缺失；only=health 逐个插件验证入口能不能真的 import（揪出界面显示正常、实际已经装坏的插件）；only=automation 看每个插件被哪些定时任务覆盖；only=tools 查自研插件目录（动态发现）/Ollama/OCR/ffmpeg/包完整性；only=ssot 跑数据腐化审计（文档里的参数与代码真值、知识库索引、依赖声明、死代码/死链、残留文件，约 1 分钟，不在 all 里跑）；only=version 查模型版本升级；deep=true 复用 check.mjs 跑全量 11 项。异常项都带可直接执行的修复命令，fix=true 会自动修安全项（建目录等），危险操作（改 owner/杀进程）永远只给命令。",
    parameters: {
      type: "object",
      properties: {
        workspace: { type: "string", description: "要检查的工作区绝对路径，默认配置里的 D:\work。" },
        only: {
          type: "string",
          enum: ["all", "workspace", "bili", "paths", "plugins", "tasks", "automation", "health", "inventory", "tools", "ssot", "version", "changes", "bundles"],
          description: "只跑某一组。all=工作区+目录+bili+计划任务（不含 plugins/ssot，因为一个要联网、一个要跑 1 分钟）；changes=只查插件增减/升级+客户端 bundle 一致性；bundles=只查客户端 bundle 一致性（exports/main/注册 id，防启动崩溃）；ssot=数据腐化审计（文档参数 vs 代码真值、索引、依赖、死代码/死链、残留）。",
        },
        deep: { type: "boolean", description: "额外调用 check.mjs 做全量 11 项检查（慢，几秒）。" },
        fix: { type: "boolean", description: "自动执行安全的修复动作（建目录等），危险操作仍只返回命令。" },
        noNetwork: { type: "boolean", description: "跳过 npm 版本查询。" },
      },
      required: [],
    },
    output: textOutput(),
    async execute(args) {
      const workspace = String(args?.workspace || defaultWorkspace);
      const only = String(args?.only || "all");
      const deep = args?.deep === true;
      const fix = args?.fix === true;
      const noNetwork = args?.noNetwork === true;
      const t0 = Date.now();

      let checks = [];
      if (only === "all" || only === "workspace") checks = checks.concat(checkWorkspace(workspace));
      if (only === "all" || only === "bili") checks = checks.concat(checkBili());
      if (only === "all" || only === "paths") checks = checks.concat(checkPaths());
      if (only === "all" || only === "tasks") checks = checks.concat(checkTasks(only === "tasks"));
      if (only === "all") checks = checks.concat(checkMemories(), checkPluginDirs(), checkPluginDrift(), checkClientBundles(), checkDisk(), checkConfigDrift(), checkToolchain(), checkLocalTools(), checkModelVersions(), checkMiscAndMcp());
      if (only === "tools") checks = checks.concat(checkLocalTools(), checkMiscAndMcp());
      if (only === "changes") checks = checks.concat(checkPluginDrift(), checkClientBundles());
      if (only === "bundles") checks = checks.concat(checkClientBundles());
      if (only === "version") checks = checks.concat(checkModelVersions());
      if (only === "plugins") checks = checks.concat(await checkPlugins({ noNetwork }), checkPluginRisk());
      if (only === "automation") checks = checks.concat(checkAutomation());
      if (only === "health") checks = checks.concat(await checkPluginHealth());
      if (only === "inventory") checks = checks.concat(await checkInventory());
      if (only === "ssot") checks = checks.concat(checkSsotAudit());
      if (deep) checks = checks.concat(checkDeep());

      // 2026-10-29 补：未知的 only 值原来会"静默返回 0 项 + 全部通过"（实测 only=ssot 在旧代码里就这样），
      // 这会把参数写错伪装成体检正常 —— 必须显式报错。
      const KNOWN_ONLY = new Set(["all", "workspace", "bili", "paths", "plugins", "tasks", "automation", "health", "inventory", "tools", "ssot", "version", "changes", "bundles"]);
      if (!KNOWN_ONLY.has(only)) {
        checks.push({
          level: FAIL,
          title: `env_doctor：未知的 only=${only}`,
          detail: `可用值：${[...KNOWN_ONLY].join(" / ")}`,
          fix: `用 env_doctor only=all 或只跑某一组（见参数说明）`,
        });
      }

      let fixedList = [];
      if (fix) fixedList = runFix(checks);

      const order = { FAIL: 0, WARN: 1, INFO: 2, OK: 3 };
      checks.sort((a, b) => (order[a.level] ?? 9) - (order[b.level] ?? 9));

      const bad = checks.filter((c) => c.level === FAIL);
      const warn = checks.filter((c) => c.level === WARN);
      const infos = checks.filter((c) => c.level === INFO);

      const lines = [`env_doctor | workspace=${workspace} | ${checks.length} 项 | ${Date.now() - t0}ms | ${fix ? "fix=on" : "只诊断"}`, ""];
      for (const c of checks) {
        lines.push(`${ICON[c.level]} ${c.title}`);
        if (c.detail) lines.push(String(c.detail).split("\n").map((l) => `       ${l}`).join("\n"));
        if (c.fix) lines.push(`       -> ${c.fix}`);
      }
      if (fixedList.length) {
        lines.push("", `已自动修复 ${fixedList.length} 项：${fixedList.join("；")}`);
      }
      lines.push("");
      if (bad.length === 0 && warn.length === 0) {
        lines.push(`结论：全部通过${infos.length ? `（${infos.length} 条提示）` : ""}。`);
      } else {
        lines.push(`结论：${bad.length} 项需处理，${warn.length} 项注意${infos.length ? `，${infos.length} 条提示` : ""}。`);
        if (bad.length) lines.push("标 FAIL 的通常手上有活就跑不顺；带 -> 的命令可直接复制执行。");
      }
      return lines.join("\n");
    },
  });
};
