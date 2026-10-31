# 读码笔记 · httpx `_urlparse.py`

- **开始**：2026-10-30 21:05（今晚开的头，明天接着读）
- **项目**：`httpx`（encode/httpx，浅克隆在 `D:\work\repos\httpx`，HEAD `b5addb6`，2026-02-23）
- **模块**：`httpx/_urlparse.py`（527 行）
- **验收标准**（照路线图）：2000 字，含 ≥3 处「我原本会这么写，它没这么写，因为…」

## 为什么选这个模块

三条理由：

1. **它在重新发明轮子。** 标准库 `urllib.parse` 就在那儿，httpx 偏要自己写 527 行。凡是"重复造轮子"的地方，背后一定有具体的、可以用文字说清的代价——这正是「会读」要找的东西。
2. **它有一次"退回"的历史。** 文件头承认自己以前依赖 `rfc3986` 这个第三方包，后来收回来自已写。一个成熟的库把依赖收回去，是很重的决定。
3. **它跟我今天踩的坑同源**——我今天两次在"URL/路径/编码"上出问题（`%LOCALAPPDATA%` 写进 docstring 变成 `\T` 无效转义、样本文件行号被我改乱）。URL 这块看着简单，边界多到离谱。

## 已读：文件头 55 行

### 观察 1 —— 为什么不用 `urllib.parse`（原文给了 5 条）

文件的 docstring 直接把理由列出来了：

```
* It provides more complete URL validation.
* It properly differentiates between an empty querystring and an absent querystring,
  to distinguish URLs with a trailing '?'.
* It handles scheme, hostname, port, and path normalization.
* It supports IDNA hostnames, normalizing them to their encoded form.
* The API supports passing individual components, as well as the complete URL string.
```

**我原本会怎么写**：

```python
from urllib.parse import urlparse
u = urlparse(url)
```

一行搞定，标准库谁都会用。

**它为什么没这么写**——五条里最狠的是第二条：

> 区分「空 querystring」和「没有 querystring」，也就是 `http://x/?` 和 `http://x/` 是**两个不同的 URL**。

这一条我从来没想过。`urlparse("http://x/?")` 返回的 `query` 是 `""`，`urlparse("http://x/")` 的 `query` 也是 `""`——**在标准库里两者分不开**，除非你回去看原始字符串里有没有那个 `?`。

而这对 HTTP 客户端是真的有区别的：
- 有些服务端/CDN 按完整 URL 做缓存 key → `?` 在不在，缓存命中率就不一样
- 有些签名算法把 query 串纳入计算 → 空串和不存在可能算出不同的签名
- 代理日志里 `/?` 和 `/` 是两个条目

**学到的东西**：这不是"标准库不够好"，是**标准库和 HTTP 客户端对 URL 的精度要求不同**。`urllib.parse` 的目标是"通用解析"，够用就行；httpx 的目标是"我发出去的字节必须和用户给的语义完全一致"。前提不同，所以结论不同。

这也正好对上我记忆里那条「知识没有真假，只有前提」。

### 观察 2 —— 三个 percent-encode 集合，分开定义

```python
FRAG_SAFE  = "".join([chr(i) for i in range(0x20, 0x7F) if i not in (0x20, 0x22, 0x3C, 0x3E, 0x60)])
QUERY_SAFE = "".join([chr(i) for i in range(0x20, 0x7F) if i not in (0x20, 0x22, 0x23, 0x3C, 0x3E)])
PATH_SAFE  = ...
```

注释里逐条写了这是 WHATWG 的哪一层：fragment 集合 = C0 控制符 + 空格 `"` `<` `>` `` ` ``；query 集合在此基础上加 `#`；path 集合再加 `?` `` ` `` `{` `}`。

**我原本会怎么写**：

```python
quote(s, safe="/")
```

传一个 `safe` 完事。

**它为什么没这么写**：这里不是"传什么 safe"的问题，是**三个位置要用三个不同的集合**，而且这些集合是从规范里一层层叠出来的（fragment ⊂ query ⊂ path，每层多禁几个字符）。用 `chr(i) for i in range(0x20, 0x7F) if i not in (...)` 这种写法，读代码的人一眼能看出"禁的是哪几个"，比写一串转义字符串可读得多。

**学到的东西**：规范里"集合是层层叠加的"这种结构，代码里也该体现成叠加，而不是三个互不相干的常量。可读性来自**结构对应**，不是来自注释。

### 观察 3 —— 默认端口被删掉，`?` 却被保留

```python
# normalize_port()，395-419 行
default_port = {"ftp": 21, "http": 80, "https": 443, "ws": 80, "wss": 443}.get(scheme)
if port_as_int == default_port:
    return None
```

这一条和观察 1 **方向相反**：

- 观察 1：`?` 在不在，必须**保留**差异（`None` vs `""`）
- 观察 3：`:443` 在不在，必须**消除**差异（统一成 `None`）

**我原本会怎么写**：

```python
port = int(port) if port else None   # 用户写什么就留什么
```

**它为什么没这么写**——这两件事看着矛盾，其实是同一条原则的两面：

> **语义等价 ⟺ 表示等价。**

- `http://x/?` 和 `http://x/` 语义**不同**（query 存在但为空 vs 根本没有 query），所以表示必须不同 → 用 `None` / `""` 区分
- `https://x:443/` 和 `https://x/` 语义**相同**（连的是同一个端口），所以表示必须相同 → 把 443 归一成 `None`

我原本那两个直觉——"用户写什么就保留什么"——**两条都错，而且错的方向相反**：对 `?` 太粗（丢了真实差异），对 `:443` 太细（保留了无意义的差异）。

**学到的东西**：规范化不是"少改"也不是"多改"，是**让语义的等价关系映射到表示的等价关系上**。判断某个差异要不要保留，先问它改不改变语义，而不是问它是不是用户写的。

这对 HTTP 客户端尤其要命：缓存 key、签名、代理日志都拿 URL 当键。**语义相同但字符串不同 → 缓存击穿；语义不同但字符串相同 → 拿到错的响应**。

### 观察 4 —— 两个值一模一样的常量，为什么要分开定义

`USERNAME_SAFE`（66-75 行）和 `PASSWORD_SAFE`（76-85 行）的表达式**一个字符都不差**。

**我原本会怎么写**：

```python
USERNAME_SAFE = PASSWORD_SAFE = "".join([...])   # 一样的东西写两遍干嘛
```

或者更省，只留一个。

**它为什么没这么写**——注释（63-65 行）说这俩来自 WHATWG 的**两个不同概念**：username percent-encode set 和 password percent-encode set。规范里它们是两个集合，只是当前定义恰好相同。

合并的代价不在今天，在下次：万一规范改了其中一个（比如 password 允许出现 `:`），就得拆回来，而且拆的时候很难讲清"原来那个名字到底代表什么"。

对比 `USERINFO_SAFE`（89-98 行）：它跟这两个**不一样**，少了 `0x3A`（`:`）。因为 userinfo 是 `username:password` 拼起来的，`:` 要是也被当安全字符，就分不清哪是分隔符、哪是内容。注释专门说明了这件事。

**学到的东西**：常量该不该合并，判据不是"值相同"，是"**它们会不会一起变**"。规范把两个概念分开定义，代码就分开定义；值相同只是此刻的巧合。

这跟观察 2 是同一件事的延伸——那次看到"层叠"（fragment ⊂ query ⊂ path），这次看到"平行"（username ∥ password，值同但概念不同）。

### 观察 5 —— `quote()` 逐段拼接，是为了一个字节都不碰已编码的部分

```python
# 497-527 行
for match in re.finditer(PERCENT_ENCODED_REGEX, string):
    ...                      # 遇到 %XX：原样 append，游标跳过
    parts.append(percent_encoded(leading_text, safe=safe))   # 两侧普通文本才编码
```

**我原本会怎么写**：

```python
from urllib.parse import quote
quote(string, safe=safe)
```

一行。标准库也"不重复编码"。

**它为什么没这么写**：因为它不是"整体编码，跳过某些字符"，而是**按 `%XX` 为界切段**——编码段原样保留，两侧的普通文本按当前的 safe 集编码。

为什么非这样不可：如果用 unquote → quote 的往返，会**丢信息**。`%2F` 是一个编码过的斜杠，unquote 成 `/` 之后，再 quote 时它已经在 safe 集里，就不会被重新编码——**一个路径段内部的数据，变成了路径分隔符**。语义被静默改掉。

按边界切段，保证的是一条硬规矩：**已经编码的字节序列，一个都不碰**。

顺带一个细节（482-494 行）：

```python
if not string.rstrip(NON_ESCAPED_CHARS):
    return string          # fast path：整串都是安全字符
```

`rstrip(chars)` 会把尾部所有在 charset 里的字符删掉，删空说明"从头到尾都是安全字符"。这招挺巧，但也脆——`NON_ESCAPED_CHARS` 一旦混进空串或意外字符，行为就跑偏。这里两个来源都是编译期常量，所以安全。

**学到的东西**：往返转换（decode→encode）看着方便，实际会丢信息。凡是要"只改一部分、其余原样"，就得按**边界切段**，而不是整体转来转去。

## 五条观察合起来是什么

回头看，五条其实是三类东西：

1. **等价关系的定义**（观察 1 + 3）—— 什么差异该保留、什么差异该消除，取决于它改不改变语义
2. **结构映射**（观察 2 + 4）—— 规范里的层叠关系、平行关系，代码里也照着摆
3. **边界处理**（观察 5）—— 只改该改的那一段，绝不整体转来转去

而这三样，恰好是我"造东西"时最缺的那一层。

我造 B+ 树、写 151 个测试的时候，脑子里想的是"功能对不对、边界测没测到"。读这 527 行才看到另一层：**每一个决定背后都有一个"如果不这样会出什么事"**，而且作者把它写进注释里了——`Shock! Horror!!`（吐槽自己重复了字符串）、`Note... The terminology 'userinfo' percent-encode set...`（解释为什么这里少一个冒号）。

这可能就是"会造"和"会扛"的差别之一：造的时候想"怎么让它工作"，扛的时候想"它会在什么情况下坏"。

## 一条「查不到就是查不到」

`MAX_URL_LENGTH = 65536`（第 29 行），**没有任何注释说明来历**。65536 = 2¹⁶ = 64 KiB。

我去查 git 历史——查不到，因为这个仓库是 `--depth 1` 浅克隆，只有一个 commit。

所以这条只能标「**未证实**」：

- 可能是拍脑袋的保守上限（挡住 obviously 恶意的超长 URL，别让正则跑太久）
- 也可能对应某个真实限制——但 Nginx 默认 8K、Apache 8K 级、IIS 16K，64K 比这些都宽松，不太像是在模拟谁

**我不硬编理由。** 没查到就写没查到，这也算读码的正常结果：不是每个数字背后都有一个能讲的故事，有些就是"够用了"。

## 待读（下次接着）

- [x] `PERCENT_ENCODED_REGEX` 的用途 —— 防双重编码，见观察 5
- [ ] `MAX_URL_LENGTH = 65536` 的来历 —— 浅克隆查不到，需要看上游完整历史或 issue
- [x] `ipaddress` 的引入 —— IPv4/IPv6 各用 `IPv4Address`/`IPv6Address` 校验；IPv6 存进去剥掉方括号（`host[1:-1]`），输出时再按 `:` 判断加回来
- [x] `idna` 的引入 —— 非 ASCII host 走 `idna.encode(host.lower()).decode("ascii")`；为什么必须是外部包还没查（下一步）
- [ ] 相对引用解析（`urljoin` 那一套）—— 这个文件里没有，得去 `_urls.py` 找
- [x] 凑齐 ≥3 处取舍 —— 已有 5 处（观察 1/2/3/4/5）

## 变更

- 2026-10-30：开头。定项目/模块/理由，读完文件头 55 行，记录观察 1、2。
- 2026-10-31：读完整个 527 行。补观察 3（端口归一化）、4（平行常量）、5（逐段 quote），加一条「MAX_URL_LENGTH 查不到来历」的如实记录。已满足验收标准（2000 字 + 5 处取舍）。
