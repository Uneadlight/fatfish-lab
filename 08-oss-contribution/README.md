# 在别人的仓库里干活

2026-10-30，第一次在真实开源仓库里走完「定位 → 复现 → 修 → 测试 → PR」。
仓库是 [`ollama/ollama-python`](https://github.com/ollama/ollama-python)。

## 两个 issue，同一个根因

| Issue | PR | 丢掉的字段 |
| --- | --- | --- |
| [#773](https://github.com/ollama/ollama-python/issues/773) | [#781](https://github.com/ollama/ollama-python/pull/781) | `prompt_eval_cached_count` |
| [#750](https://github.com/ollama/ollama-python/issues/750) | [#782](https://github.com/ollama/ollama-python/pull/782) | `TokenLogprob.bytes` |

`GenerateResponse` / `TokenLogprob` 都继承自 `SubscriptableBaseModel`，而它没有设
`model_config = ConfigDict(extra='allow')`。pydantic v2 默认 `extra='ignore'` ——
**服务端返回的陌生字段进来就没了，不报错、不告警。**

## 不是照着 issue 抄

两次都做了同样的三件事：

1. **先在真机上确认服务端真的返回了。** 起本机 ollama，`logprobs=True` 打一次 `/api/generate`，
   看到 `{"token": "Hello", "logprob": -0.20, "bytes": [72,101,108,108,111]}`。
2. **再确认客户端真的丢了。** 用仓库自己的 `Client` 拿同一份响应，
   `r.logprobs[0].model_dump()` 里没有 `bytes`，访问直接 `AttributeError: 'Logprob' object has no attribute 'bytes'`。
3. **改完再打一遍**，看它出来。

「服务端有」和「客户端有」是两件事，中间那层不查，就只能靠猜。

## 这里的两个 patch

- `0001-prompt_eval_cached_count.patch` —— 加字段 + 3 个测试（属性 / 下标 / `model_dump` / 老服务端兼容）
- `0002-logprob-bytes.patch` —— 加字段 + 4 个测试（generate / chat / 可选 / `top_logprobs`）

都是 `git format-patch` 原样导出，可以直接 `git am`。

`bytes` 用的是 `Optional[Sequence[int]]` 而不是 Python 的 `bytes` 对象——后者的 `model_dump()` 不是 JSON 可序列化的，会把下游序列化搞坏。

## 一个细节

两个 PR 各自从 `main` 开一条分支（`fix/773-...`、`fix/750-...`），没有在前一条分支上接着改。
否则第二个 PR 的 diff 里会混进第一个的改动，reviewer 没法看。

## 验收口径

- `pytest tests`：修 #773 之后 112 passed、修 #750 之后 113 passed；**失败的 8 个原样不变**
- 那 8 个是这台机器的环境问题（`%TEMP%` 坏了导致图片测试报 `Invalid image data`、blob 测试报 `PermissionError`），在 `main` 上同样失败
- `ruff check` + `ruff format --check`：干净
