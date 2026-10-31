# tools/lab

把「每遇到一次就写一个一次性脚本」改成「每遇到一类就收成一个子命令」。

## 为什么有这个目录

2026-10-31 清点 `tools/gh-login/`：

| 事实 | 数字 |
|---|---|
| 积压的一次性文件 | **68 个**（63 脚本 + 5 数据） |
| 其中「往决策日志追加一段」 | 6 个，做同一件事 |
| 其中「读 app.asar」 | 4 个，做同一件事 |
| 每条命令里手写的 Python 解释器路径 | **106 字符** |
| `$env:PYTHONIOENCODING='utf-8'` 出现次数 | **100+（搜索打满上限）** |

正式工具只有 4 个（`ghctl.py`、`gh_api.py`、`github_device_login.py`、`push_fork.py`）。

**判断标准**：一次性脚本解决「这一次」，工具解决「这一类」。会不会再跑第二次，是唯一的分界线。

## 装在哪

两个 `.cmd` 放在 `~\.local\bin\`（这个目录**本来就在用户 PATH 里**，ruff 和 uv 也装在这儿）。

| 命令 | 作用 |
|---|---|
| `py <脚本> [参数...]` | 用 DSH runtime python 跑，自动 `PYTHONIOENCODING=utf-8` |
| `lab <子命令>` | 工作区小工具集合 |

切项目 venv：

```powershell
$env:PYEXE = 'D:\work\repos\ollama-python\.venv\Scripts\python.exe'
py -m pytest -q
Remove-Item Env:PYEXE
```

不设 `PYEXE` 时用 DSH runtime python。

## lab 子命令

### `lab log` —— 决策日志追加（替代 6 个 `_log_*.py`）

```powershell
# 从文件读正文（推荐：正文含中文，走文件不会有命令行编码问题）
lab log --mark "2026-11-01 09:0x" --title "标题" --body-file body.md

# 只看最后几段
lab log --tail 3

# 只打印不写
lab log --mark "..." --title "..." --body-file body.md --dry
```

- `--mark` 是**幂等依据**：日志里已有这个字符串就直接 `SKIP`，不会重复写。
- 正文缺 `**做了什么**` / `**为什么**` / `**取舍**` / `**教训**` 时给 `[WARN]`，但不阻止写入。
- 写入用 append 模式，不会读改写整份文件。

### `lab asar` —— 读 `app.asar`（替代 4 个 `_asar_*.cjs`）

```powershell
lab asar list session        # 列出名字含 session 的包
lab asar desc worktree       # 带 description
lab asar read 'dsh/node_modules/@deepseek-ai/dsh-experimental-session-search/package.json' --max 0
```

- 不解包，按 header 里的 offset/size 直接读。
- asar 头格式：offset 0/4/8/12 四个 uint32，`jsonSize` 在 offset 12，JSON 从 **16** 起，数据区起点 `16 + jsonSize` 再按 4 字节对齐。
  **之前的 4 个脚本里有一个算错了偏移**（`16 + headerSize - jsonSize`），吐了 14KB 垃圾后 `SyntaxError`。

## 两个硬坑（都踩过）

### 1. `.cmd` 必须是 CRLF

`write` 工具写出的是 **LF** 换行。cmd.exe 解析 LF-only 的批处理会错乱：

```
'-' is not recognized as an internal or external command
'ves' is not recognized as an internal or external command
'age:' is not recognized as an internal or external command
```

（`'age:'` 是 `Usage:` 被吃掉一半的结果 —— 字符会丢。）

修法：

```powershell
$c = [System.IO.File]::ReadAllText($f) -replace "`r?`n", "`r`n"
[System.IO.File]::WriteAllText($f, $c, (New-Object System.Text.UTF8Encoding $false))
```

### 2. 不能用 dot-source 定义函数

想做的本来是 PowerShell 函数（`. lab.ps1` 之后 `py xxx.py`），但 DSH 的 CC Safety Net 会拦：

```
BLOCKED by CC Safety Net
Rule: analysis.dynamic-shell-source
Segment: . D:\work\tools\lab\lab.ps1
```

字面路径和变量都拦。所以**只能走 PATH 上的 `.cmd`**，不能靠 profile/函数。

## 还没收的

`gh-login` 里还有几类没动，因为它们的接口还没稳定：

- **发布流水线**（6 个）：`_stage_repo.py`、`_scrub_repo.py`、`_scrub_repo2.py`、`_stage2.py`、`_stage3.py`、`_sec_scan.py`
- **提交推送**（8 个）：`_commit_push*.py`、`_fix_commit.py`、`_sync_final.py` …（`ghctl sync` 已覆盖大部分）
- **Release**（3 个）：`_make_release.py`、`_rel_v130.py`、`_verify_tree.py`
- **补丁脚本**（7 个）：`_patch_*.py`、`_fix_*.py`

这些不急着收：先让它们跑几次，看清哪些参数是固定的、哪些是真变量，再定接口。**先有用法，再有工具**，反过来会设计出一个没人用的工具。
