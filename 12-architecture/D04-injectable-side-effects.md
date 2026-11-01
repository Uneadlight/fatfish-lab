# D04 可注入的副作用

> 出处：B05 crawler（`RateLimiter` / `retry_call` / `fetch`）、B03 request_log（`clock` / `sink`）

## 解决什么问题

代码里有三类东西天生不确定：**时间**（`time.time()`）、**IO**（网络/磁盘）、**随机**（`random()`）。它们让测试要么慢（真的 sleep 10 秒）、要么不稳（真的发网络请求）、要么没法断言（随机值）。

Mock 框架能解决，但引入 mock 会让测试和实现耦合（`mock.patch("module.time.time")` 一旦重构就断）。

## 结构：副作用作为参数，默认取真实实现

```python
class RateLimiter:
    def __init__(self, interval, clock=None, sleep=None):
        self.interval = interval
        self.clock = clock or time.monotonic    # 注意：函数内取默认
        self.sleep = sleep or time.sleep
        self._next = self.clock()

    def wait(self):
        now = self.clock()
        delay = max(0.0, self._next - now)
        if delay > 0:
            self.sleep(delay)
            now += delay
        self._next = now + self.interval
        return delay
```

关键点：

1. **默认值在 `__init__` 里取，不在参数默认值里写**——`def __init__(self, clock=time.monotonic)` 会在定义时绑定，之后想 patch `time.monotonic` 无效
2. **`self._next` 用"计划时间"而不是"睡醒后读真实时钟"**：`_next = now + interval` 保证固定间隔；如果睡醒重新 `clock()`，每次唤醒的调度延迟会累加，跑一天间隔就漂了
3. **返回值也要有**：`wait()` 返回 `delay`，测试才能断言"第 3 次等了 7 秒"，否则只能看副作用

## 三个副作用的常见参数名

| 副作用 | 参数 | 默认 |
|---|---|---|
| 时间（单调） | `clock` | `time.monotonic` |
| 休眠 | `sleep` | `time.sleep` |
| 网络 | `opener` | `urllib.request.urlopen` |
| 随机 | `rand` | `random.random` |
| 日志出口 | `sink` / `stream` | `sys.stderr` |

## 取舍

- **代价**：构造函数参数变多。一个类有 5 个副作用参数就该反思是不是职责太重
- **换来**：测试零 mock、零 patch，直接传假对象；生产路径和测试路径是同一份代码，不是两条
- **替代方案**：`freezegun`/`responses` 这类库能全局 patch，但它们是"测试时改环境"，注入式是"设计时就留口"，后者更稳

## 什么时候别用

- **副作用无处不在**（一个函数里 10 处 IO）：参数会爆炸，这时候该做的是拆分函数，不是继续注入
- **纯函数**：没有副作用就没有可注入的，别硬加

## 判据

问自己：**"这个测试会不会因为跑得慢/网络抖动而偶发失败？"** 会，就该注入。
