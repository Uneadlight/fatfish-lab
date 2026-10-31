# ollama-python `_client.py` 读码笔记

**读于** 2026-10-31
**文件** `D:\work\repos\ollama-python\ollama\_client.py`（1,488 行 / 43,183 字节，HEAD `d2d55c7`）
**为什么读它**：这是我天天在用的库，也是我给它提过两个 PR 的库——但两个 PR 都只碰了 `_types.py` 的字段。真正的请求链路（错误怎么转、流式怎么断、同步异步怎么分家）我一直没读过。想提第三个 PR、或者至少能判断"这个问题到底出在客户端还是服务端"，都得先看懂这一层。

---

## 一、结构：620 行写了两遍

```
class BaseClient (83)     ← 只做 base_url / headers / 上下文管理，60 行
class Client (134-753)    ← 620 行：generate/chat/embed/pull/push/create/list/delete/copy/show/ps...
class AsyncClient (754-1373)  ← 620 行：一字不差的一套，每个方法前多个 await
def _copy_images/_copy_messages/_copy_tools/_as_path/_parse_host (1374-1488)
```

我先算了一笔账：**给接口加一个参数，要改 7 个地方**。

以 `logprobs` 为例——它出现在 `Client.generate` 的 **L217 / L241 / L264**（两个 overload + 实现各一次），`AsyncClient.generate` 的 **L877 / L901 / L924** 同样三次，再加上 `_types.py` 的 `GenerateRequest` 一处。

```python
# Client.generate      (L217, L241, L264)
    logprobs: Optional[bool] = None,
# AsyncClient.generate (L877, L901, L924)
    logprobs: Optional[bool] = None,
```

`chat` 更狠：`Client.chat` 在 **L321 / L337 / L352**，`AsyncClient.chat` 在 **L980 / L996 / L1011**——同样 6 处。全文 `logprobs` 一共出现 **28 次**，其中 18 次是参数声明。

**我原本会怎么写**：用 `anyio.to_thread` 抽一层通用实现，同步异步各包一个薄壳。

**它为什么没这么做**：看 L26 `import anyio` —— 它**确实导入了** anyio，但只在 `AsyncClient.create_blob` 的 L1303/L1313 用了一下 `anyio.open_file`。

这说明不是"没想到 anyio"，是**主动选了复制**。我猜代价算过了：

- 用 anyio 抽象，`overload` 会从"两个方法各写一个"变成"一个方法套一层泛型"，类型检查器推不出 `stream=True → Iterator` 这个关系
- 抛错时栈里多两层 anyio 的帧
- 少一层抽象，读代码的人一眼看到"这里真的发了 POST /api/generate"

**代价是什么**：改一个签名改 7 处，漏一处就是运行时 `TypeError`（而且是"缺参数"不是"参数错"）。这解释了为什么这个库的 issue 里有一堆"XX 参数在 AsyncClient 里没有"。

---

## 二、流式请求的报错：必须先把 body 读出来

```python
def _request(self, cls, *args, stream: bool = False, **kwargs):
  if stream:
    def inner():
      with self._client.stream(*args, **kwargs) as r:
        try:
          r.raise_for_status()
        except httpx.HTTPStatusError as e:
          e.response.read()          # ← 这一行
          raise ResponseError(e.response.text, e.response.status_code) from None
```

**这一行 `e.response.read()` 是我原本一定会漏掉的。**

用 `httpx.stream()` 时响应体是**惰性的**，没读之前 `response.text` 是空字符串。不读 body 直接抛 `ResponseError('')`，用户拿到的是"HTTP 500，原因是空"——比不抛还难查。

而 `_request_raw`（非流式，L141-149）就不需要这一行，因为 `self._client.request()` 默认把 body 读进来了。**同一份错误处理逻辑，流式和非流式差一行**，这种"差一点"的地方最容易在重构时被抹平。

顺带：三处 `raise ... from None`（L147 / L149 / L193）。线上取干净栈，代价是调试时看不到 httpx 原始异常。这是取舍不是 bug——但如果哪天要排查"到底哪层在重试"，这行会碍事。

---

## 三、`exclude_none` 让 None 和空串成了两件事

```python
json=GenerateRequest(
  model=model,
  prompt=prompt,          # 实现里是 Optional[str] = None
  ...
).model_dump(exclude_none=True),   # L308
```

注意 overload 里写的是 `prompt: str = ''`（L209），实现里是 `prompt: Optional[str] = None`（L256）。这不是笔误，是**故意的三层语义**：

| 调用 | 发出去的 JSON |
|---|---|
| `generate(model='x')` | 不含 `prompt` 字段 |
| `generate(model='x', prompt=None)` | 不含 `prompt` 字段 |
| `generate(model='x', prompt='')` | `"prompt": ""` |

因为 `exclude_none` 只滤 `None`，不滤空串。

这跟我在 httpx `_urlparse.py` 里看到的是**同一个问题的两种答案**：httpx 那篇里 `http://x/?` 和 `http://x/` 必须区分，所以用 `None` vs `''`（query 是 `None` 还是空串）来编码"有没有问号"；这里则相反，**空串是有意义的值**（发一个空 prompt），`None` 才是"别发"。

判据不是"空值一律不要"，是**"服务端会不会对这个空值有不同解释"**。

同一节里还有一行 `images=list(_copy_images(images)) if images else None`（L302）—— 空列表被转成 `None`，等于"没传图片"。这里它选择了**不区分**（`images=[]` 和 `images=None` 一样），因为服务端对空图片列表没有另一种解释。

---

## 四、`_parse_host`：26 条 doctest 当规格，IPv6 那行是关键

`_parse_host`（L1401-1488）前面挂了 **26 条 `>>>` 例子**，覆盖 `None`、空串、纯 IP、`:port`、有无 scheme、http/https、IPv6、带路径、带尾斜杠的矩阵。

```python
>>> _parse_host('')                → 'http://127.0.0.1:11434'
>>> _parse_host('1.2.3.4')         → 'http://1.2.3.4:11434'
>>> _parse_host('http://1.2.3.4')  → 'http://1.2.3.4:80'      # 注意是 80
>>> _parse_host('example.com')     → 'http://example.com:11434'
```

**我原本会写**：一段注释列几个例子，或者一两条 assert。

**它写成了可执行的规格**——`python -m doctest ollama/_client.py` 直接能验。这是把"我知道它该怎么工作"变成了"机器也知道"。

不显然的两处：

**① 默认端口取决于"有没有写 scheme"**：`example.com` → 11434（ollama 默认端口），但 `http://example.com` → 80。看起来不一致，其实一致——**显式写了 `http://` 就按 HTTP 语义走 80，没写 scheme 就用 ollama 的 11434**。我原本会统一都加 11434，然后在 `https://foo` 上得到 `https://foo:11434`，用户一脸问号。

**② IPv6 的方括号会被 urlsplit 吃掉**：

```python
split = urllib.parse.urlsplit(f'{scheme}://{hostport}')
host = split.hostname or '127.0.0.1'
...
try:
  if isinstance(ipaddress.ip_address(host), ipaddress.IPv6Address):
    host = f'[{host}]'        # L1481，补回方括号
except ValueError:
  ...
```

`urlsplit('http://[::1]:11434').hostname` 返回 `'::1'`（**没有方括号**），直接拼回去就是 `http://::1:11434` —— 非法 URL。

**我原本会写** `if ':' in host: host = f'[{host}]'`，然后被某个带冒号的奇怪主机名坑掉。它用 `ipaddress.ip_address()` 真解析一遍，判的是"这是不是合法 IPv6 地址"而不是"看起来像不像"——**用解析器当判据，不用字符串特征当判据**。

外层还有个 `except ValueError: ...`：不是 IPv6（是域名）就走正常路径。注意是 `ValueError` 不是 `Exception`，因为 `ip_address()` 只会为"解析不了"抛这个。

---

## 五、`RequestError`：四处 docstring 承诺，代码里一次没抛

```python
"""
Raises `RequestError` if a model is not provided.
Raises `ResponseError` if the request could not be fulfilled.
"""
```

这句话出现在 `_client.py` 的 **L278、L385、L938、L1044**（`Client.generate`、`Client.chat`、`AsyncClient.generate`、`AsyncClient.chat` 的 docstring）。

然后我 grep 了整个 `ollama/` 目录：

```
RequestError 出现位置
  _client.py:278 / 385 / 938 / 1044   ← 全是 docstring
  _types.py:696                        ← 类定义
  __init__.py:13 / 47                  ← 导出
```

**一次 `raise RequestError` 都没有。**

那实际会发生什么？`model=''` 传下去，`GenerateRequest(model='')` 校验通过（`model: str`，空串合法），照常发请求，服务端返回 400，客户端抛的是 **`ResponseError`** 而不是文档承诺的 `RequestError`。

所以：

- 用户按文档 `except RequestError` → **永远捕获不到**，异常冒到最外层
- 按实际 `except ResponseError` → 能接住，但要多绕一次网络

这是文档与实现的脱节，不是"设计如此"。`RequestError` 的类定义（`_types.py:696`）只写了「Common class for request errors.」，没有任何"留给未来"的说明。

**我没急着提 PR 的两个原因**：

1. 修法有两种（本地加校验抛 `RequestError` / 改 docstring 删掉这句），**选哪个是维护者的口味**，不是我该替他定的
2. 加了校验就变成"空 model 时本地抛错"，这会改变现有行为——虽然更合理，但属于"行为变更"，得先问

记下来，等哪天要提第三个 PR 时先开 issue 讨论。

---

## 六、三条观察合起来是什么

| 主题 | 具体表现 | 一句话 |
|---|---|---|
| **错误处理的完整性** | 流式必须先 `read()`、非流式不用 | 差异藏在一行里，重构时最先丢 |
| **空值的语义** | `None`≠`''`（prompt），`None`==`[]`（images） | 判据是"服务端有没有另一种解释" |
| **判据的选择** | IPv6 用解析器判、不用字符串特征 | "看起来像"不等于"是" |

还有一条不算取舍，但值得记：**620 行 × 2 这种重复，代价不在写的时候，在改的时候**。加一个参数改 7 处，改的人必须记得 AsyncClient 里也有——而"记得"是最不可靠的保证。

---

## 如果让我改

1. **`RequestError` 那条先开 issue**，别直接 PR。修文档比改行为容易过。
2. **同步/异步不合并**。620 行重复能忍，但可以加一个 CI 检查：解析 AST 提取 `Client` 和 `AsyncClient` 的公开方法签名，**不一致就红**。这比"靠记得"可靠，而且改动小。
3. **`_parse_host` 的 doctest 值得抄**。我自己的 `ghctl.py` 里 `resolve_slug()` 也有"认盘符路径 / `owner/name`"两种输入，全靠我看代码判断——应该补成 doctest。

---

## 待查（下次读）

- `pull` / `push` 的三重 overload（L483/492/500）怎么处理进度回调
- `web_search` / `web_fetch` 是新接口吗？`_types.py` 里的 `WebSearchRequest` 什么时候加的
- `systemone`（L410）—— 这是 ollama 的新能力，接口长什么样
- `BaseClient` 为什么不支持 `extra='allow'`（跟 #773/#750 同源）—— 已经改过两处，但根因没解决
