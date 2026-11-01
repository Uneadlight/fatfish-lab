# D01 子进程隔离

> 出处：Q01 `run_all.py`

## 解决什么问题

批量跑测试时，不同测试文件之间**共享同一个 Python 进程的全局状态**：

- `sys.modules` 缓存——骨架里有 3 个同名的 `app.py`（workbench v0/v1/v3），同进程 `import app` 只会拿到第一个，后两个测试跑的还是第一份代码
- 全局注册表——`logging.Logger.manager.loggerDict`、`atexit`、`signal` handler 都会跨测试残留
- 模块级副作用——`create_app()` 在 import 时就执行，第二个测试无法重新初始化

`setUp`/`tearDown` 清不干净这些，因为它们有的在 C 层、有的在解释器启动时就固定了。

## 结构

```python
import os, subprocess, sys

def run_one(path):
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    proc = subprocess.run(
        [sys.executable, path],
        cwd=os.path.dirname(os.path.abspath(path)),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return proc.returncode == 0, proc.stdout + proc.stderr

def main():
    ok = all(run_one(p)[0] for p in discover())
    return 0 if ok else 1
```

三个要点：

1. **一个测试文件一个子进程**，不是"一个测试用例一个"——粒度按隔离边界划，不按用例划
2. **`cwd` 显式设置**——子进程相对 import 依赖工作目录
3. **`PYTHONIOENCODING=utf-8`**——否则 Windows 下子进程按 GBK 输出，父进程按 utf-8 解码必乱码

## 取舍

- **代价**：每个子进程 50–150ms 启动开销。95 个测试拆 2 个文件，代价可忽略；如果拆成 95 个进程就得不偿失
- **换来**：绝对隔离，不需要任何清理代码，测试顺序无关
- **替代方案**：`importlib.reload()` 能重载模块但清不掉 C 层状态和注册表；`pytest-forked` 是同一思路的库版

## 什么时候别用

- **单文件内部**：同一测试文件里的用例用 `setUp` 清理就够，上子进程是杀鸡用牛刀
- **需要共享 fixture 的重测试**（如加载 100MB 模型）——每次重建代价太大，改用会话级 fixture + 手动 reset

## 判据

问自己一句：**"这些测试能不能任意换顺序跑？"** 不能，就是隔离不足。
