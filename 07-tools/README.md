# ghctl —— 把「改文件 → 提交 → 推送 → 验远端」收成一条命令

这个工具不是计划出来的，是被坑逼出来的。

某一天为了给仓库改几行字、开两个 PR，我在 `tools/gh-login/` 下攒了 **21 个一次性脚本、959 行**，真正能复用的只有 3 个。同样的坑反复踩：

| 坑 | 踩了几次 | 现在的默认行为 |
| --- | --- | --- |
| git 不在 PATH（本机是便携版 MinGit） | 2 | 内置绝对路径候选，再退 `shutil.which` |
| 中文 commit message 被 GBK 转码 | 2 | 写 UTF-8 无 BOM 临时文件 + `commit -F`，提交后用 `git cat-file` 校验原始字节 |
| push 被 `Connection was reset` | 3 | `http.version=HTTP/1.1` + 最多 5 次退避重试 |
| 取 README 拿到的是 JSON 元数据不是正文 | 1 | 固定 `Accept: application/vnd.github.raw` |
| 报错说不清是「不会」还是「不让」 | —— | 统一 `[FAIL:能力缺失\|权限被拒\|执行失败]` + 一句提示 |

## 子命令

```
ghctl whoami                      # token 是谁、带什么 scope
ghctl use Uneadlight/fatfish-lab  # 记成默认目标，之后不用每次 --repo
ghctl sync -m "..." --all         # 暂存 + 提交（UTF-8 安全）+ 推送（自动重试）
ghctl readme --line 12            # 取远端 README 正文，按行号 / 关键字看
ghctl meta --desc "..." --topics a,b,c
ghctl issue 750 --repo ollama/ollama-python
ghctl release create --tag v1.1.0 --title "..." --notes-file notes.md
```

## 一条设计原则

**能自己判断的，不问人。**

失败时它必须自己说清属于哪一类，而不是抛一句 `Exception` 让人猜。把「我做不到」（能力缺失）和「你不让我做」（权限被拒）混在一起，是这里最贵的错误——前者要去找办法，后者只能去改授权，处置方式完全相反。

写成这样也是被逼的：我踩过一次「没有权限」被误判成「没有能力」，白找了两小时的办法。
