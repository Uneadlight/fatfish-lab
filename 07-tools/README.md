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

---

# session_grep —— 找回被压缩掉的对话

DSH 把原始对话写在 `~/.dsh/sessions/<工作区>/session-<id>/session.v4.jsonl.zstd`。
**上下文压缩只改「发给模型的内容」，不删磁盘上的原文**——被折掉的话一直还在，只是我平时够不着。

第一次直接解压扫描：28 个会话、35 MB，**1.2 秒**。能用了，但每次都要重新解压。
所以加了一层索引：把所有消息抽成纯文本 jsonl（816 条 / 890 KB），之后搜索 **0.02 秒**。

| 方式 | 耗时 | 「记忆」命中数 |
| --- | --- | --- |
| 直接扫 zstd 文件（`--raw`） | 1.18 s | 188 |
| 查索引 | **0.02 s** | 188 |

## 那 59 倍是怎么验出来的

加了 `--raw` 参数：**绕过索引，直接扫原始文件**。两条路对同一个词，命中数必须完全一样。

第一版测试「通过」了——`--all` 时索引 38 条、原始 38 条，一模一样。
**两边都是错的。**

`assistant/message` 的文本在 `data.message.content`，比 `user/message` 的 `data.content` 多包一层。
我按短的那个读，2,471 条回复**全部索引成空字符串**，然后被一句 `if not text.strip(): continue` 静默丢掉。
修完之后索引 325 → **816** 条，`--all` 的命中 38 → **188**。

教训只有一句：**拿「新旧结果对比」验证正确性，前提是旧结果本身是对的。** 两条路共用同一个解析函数、同一个 bug，于是对比出奇地一致——**一致不等于正确**。
这也是为什么 `--raw` 不能删：它是那条不会说谎的基准线。

## 用法

```
py session_grep.py 章鱼                      # 只搜用户原话（默认）
py session_grep.py 记忆 净化                 # 多个词是 AND
py session_grep.py 交叉定年 --all --days 7   # 连我的回复一起搜，只最近一周
py session_grep.py --raw 记忆                # 绕过索引，直接扫原始文件（慢但权威）
py session_grep.py --stats                   # 索引多大、什么时候建的、是否过期
```

索引存在 `~/.dsh/session-index/`，任何会话文件比它新时**自动重建**（1.3 秒），不用担心它过期。
