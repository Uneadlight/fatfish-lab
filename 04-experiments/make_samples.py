"""造一批「长输出 + 真因」样本，用来量 3b 做归因初筛的命中率。

为什么用合成样本：真实输出里"哪几行是真因"我可能也判断错，
那就没法当标准答案。合成样本里真因是我自己埋的，**标准答案 100% 可信**，
这样才能算出真实的命中率/漏报率。

样本类型：
    pytest   —— 一堆通过日志 + 1~2 个真实失败栈
    audit    —— 审计报告式长表 + 2 条真问题
    log      —— 服务日志 + 1 条致命错误 + 若干无害 warning
    nvidia   —— nvidia-smi 长表 + 1 行"显存被挤爆"

输出：samples/*.txt（正文）+ samples/truth.json（每份的真因行号与关键词）
"""

from __future__ import annotations

import json
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SAMPLES = ROOT / "samples"
rng = random.Random(20261030)

OK_TESTS = [
    "tests/test_codec.py::test_roundtrip_1000",
    "tests/test_codec.py::test_边界_空串",
    "tests/test_framing.py::test_粘包_100帧",
    "tests/test_rpc.py::test_并发50连接",
    "tests/test_bplus.py::test_随机5000步对照dict",
    "tests/test_paged.py::test_查找页读不超过树高",
    "tests/test_router.py::test_隐私标记禁止走云端",
    "tests/test_orchestrator.py::test_同秒同大小改写不会骗过判分",
    "tests/test_guard.py::test_暖机不重复计数",
    "tests/test_judge.py::test_无测试用例判红",
]


def pytest_sample(mode: str) -> tuple[list[str], dict]:
    """mode: 'fail_impl' = 实现有 bug；'fail_test' = 测试自己写错。"""
    lines: list[str] = []
    for name in OK_TESTS:
        lines.append(f"{name} PASSED")
        for _ in range(3):
            lines.append(f"    [debug] fixture setup ok, tmp={rng.randint(1000, 9999)}")
    if mode == "fail_impl":
        lines += [
            "tests/test_bplus.py::test_删除后区间扫描 PASSED",
            "=================================== FAILURES ===================================",
            "__________________ test_范围删除返回个数 __________________",
            "",
            "    def test_范围删除返回个数():",
            "        tree = BPlusTree(order=8)",
            "        for k in range(0, 100, 2):",
            "            tree.insert(k, k)",
            ">       assert tree.range_delete(10, 20) == 6",
            "E       assert 5 == 6",
            "E        +  where 5 = range_delete(10, 20)",
            "",
            "tests/test_bplus.py:88: AssertionError",
            "=========================== short test summary info ===========================",
            "FAILED tests/test_bplus.py::test_范围删除返回个数 - assert 5 == 6",
            "1 failed, 40 passed in 3.21s",
        ]
        truth = {"keyword": "range_delete(10, 20) == 6", "type": "实现漏算右边界"}
    else:
        lines += [
            "tests/test_guard.py::test_温度冷却命中 PASSED",
            "=================================== ERRORS ====================================",
            "__________________ ERROR at setup of test_冷却后恢复 __________________",
            "",
            "    @pytest.fixture",
            "    def sampler():",
            ">       return FakeSampler(temp=)  # 参数漏填",
            "E       SyntaxError: invalid syntax",
            "",
            "tests/test_guard.py:41: SyntaxError",
            "=========================== short test summary info ===========================",
            "ERROR tests/test_guard.py::test_冷却后恢复",
            "1 error, 41 passed in 0.58s",
        ]
        truth = {"keyword": "SyntaxError: invalid syntax", "type": "测试文件自己写错"}
    return lines, truth


def audit_sample() -> tuple[list[str], dict]:
    lines = [
        "# SSOT 审计报告 2026-10-30",
        "",
        "| 维度 | 数量 | 判定 |",
        "|---|---|---|",
        "| 文档参数过期 | 1 | WARN |",
        "| 索引幽灵文件 | 0 | OK |",
        "| 未声明依赖 | 0 | OK |",
        "| 死代码候选 | 13 | INFO |",
        "| 死链 | 2 | WARN |",
        "| 残留文件 | 0 | OK |",
        "",
        "## 明细",
        "",
        "- [WARN] `记忆注入字符预算`：代码 60000，文档写 30000（来源 自进化\\记忆库优化规则.md:41）",
        "- [INFO] dead_code `Puppy`（学习计划\\01-编程\\python\\第30课.py）",
        "- [INFO] dead_code `cleanup_stale_temps`（学习计划\\01-编程\\tools\\clean.py）",
        "- [WARN] 死链 `E:\\DS公作区\\tools\\deepseek.md`（来源 救回手册.md:88）",
        "- [INFO] dead_code `verify_pair`（学习计划\\01-编程\\项目3\\dedupe.py）",
        "",
        "## 结论",
        "0 项需处理，2 项注意。",
    ]
    truth = {"keyword": "代码 60000，文档写 30000", "type": "文档参数与代码不一致"}
    return lines, truth


def log_sample() -> tuple[list[str], dict]:
    lines = []
    for i in range(60):
        lines.append(f"2026-10-30 12:{i % 60:02d}:00 INFO  worker-{i % 4} heartbeat ok latency={rng.randint(3, 40)}ms")
    lines += [
        "2026-10-30 12:31:07 WARN  cache miss ratio 0.71 (above 0.70, will retry next cycle)",
        "2026-10-30 12:31:09 WARN  slow query 812ms (threshold 500ms) sql=SELECT * FROM memories",
        "2026-10-30 12:32:11 ERROR failed to acquire store lock: E:\\DS公作区\\...\\memories.json.lock timeout 2000ms",
        "2026-10-30 12:32:11 ERROR write aborted, 3 pending changes dropped",
        "2026-10-30 12:32:12 INFO  retry 1/3",
        "2026-10-30 12:32:13 WARN  stale lock removed (age 11.2s)",
    ]
    for i in range(20):
        lines.append(f"2026-10-30 12:33:{i:02d} INFO  worker-{i % 4} heartbeat ok latency={rng.randint(3, 40)}ms")
    truth = {"keyword": "write aborted, 3 pending changes dropped", "type": "抢锁超时导致丢写"}
    return lines, truth


def nvidia_sample() -> tuple[list[str], dict]:
    lines = ["Wed Oct 30 12:40:00 2026", "+-----------------------------------------------------------------------------+",
             "| NVIDIA-SMI 565.90    Driver Version: 565.90    CUDA Version: 12.7        |",
             "|-----------------------------------------+------------------------+----------------------|",
             "| GPU  Name              Persistence-M | Bus-Id          Disp.A | Volatile Uncorr. ECC |",
             "| Fan  Temp   Perf       Pwr:Usage/Cap |           Memory-Usage | GPU-Util  Compute M. |",
             "|=========================================+========================+======================|"]
    for i in range(8):
        lines.append(f"|   0  NVIDIA GeForce RTX 4060 ...  Off | 00000000:01:00.0  On |                  N/A |")
    lines += [
        "| N/A   78C    P0             62W /  67W |    7912MiB /   8188MiB |     96%      Default |",
        "+-----------------------------------------+------------------------+----------------------+",
        "",
        "+-----------------------------------------------------------------------------+",
        "| Processes:                                                                  |",
        "|  GPU   GI   CI        PID   Type   Process name                  GPU Memory |",
        "|=============================================================================|",
        "|    0   N/A  N/A     12345      C   ...s\\python.exe                    4100MiB |",
        "|    0   N/A  N/A     45210      C   ...ollama.exe                       3350MiB |",
        "+-----------------------------------------------------------------------------+",
    ]
    truth = {"keyword": "7912MiB /   8188MiB", "type": "显存已到 96.6%，随时 OOM"}
    return lines, truth


def normal_sample() -> tuple[list[str], dict]:
    """全绿输出——用来测**误报率**：它会不会在正常输出里硬找错误。"""
    lines = []
    for name in OK_TESTS * 3:
        lines.append(f"{name} PASSED")
    lines += [
        "============================== 133 passed in 12.40s ==============================",
    ]
    truth = {"keyword": None, "type": "无错误（测误报）"}
    return lines, truth


def long_log_sample() -> tuple[list[str], dict]:
    """200 行日志，只有 1 个致命错误埋在中间。"""
    lines = []
    for i in range(200):
        if i == 137:
            lines.append("2026-10-30 13:02:41 FATAL out of disk space while writing E:\\DS公作区\\tmp\\page.0001.bpt")
        elif i % 17 == 0:
            lines.append(f"2026-10-30 13:{i % 60:02d}:00 WARN  retry {i % 3 + 1}/3 block={i}")
        else:
            lines.append(f"2026-10-30 13:{i % 60:02d}:00 INFO  flush block={i} ok bytes={rng.randint(4096, 65536)}")
    truth = {"keyword": "FATAL out of disk space", "type": "磁盘写满"}
    return lines, truth


def mixed_sample() -> tuple[list[str], dict]:
    """多个 WARN + 1 个真 ERROR：看它会不会被 WARN 带偏。"""
    lines = [
        "2026-10-30 13:10:00 WARN  cache hit ratio 0.62 (target 0.80)",
        "2026-10-30 13:10:01 WARN  slow query 640ms",
        "2026-10-30 13:10:02 WARN  deprecated config key 'nudge_growth' used",
        "2026-10-30 13:10:03 INFO  worker restarted",
        "2026-10-30 13:10:04 ERROR 无法写入 memories.json：PermissionError [WinError 5] 拒绝访问",
        "2026-10-30 13:10:05 WARN  retry 1/3 in 15ms",
        "2026-10-30 13:10:06 INFO  fallback to read-only mode",
    ]
    truth = {"keyword": "PermissionError [WinError 5]", "type": "权限被拒导致写失败"}
    return lines, truth


def main() -> None:
    SAMPLES.mkdir(parents=True, exist_ok=True)
    cases = {
        "pytest_fail_impl": pytest_sample("fail_impl"),
        "pytest_fail_test": pytest_sample("fail_test"),
        "audit_report": audit_sample(),
        "worker_log": log_sample(),
        "nvidia_smi": nvidia_sample(),
        "all_green": normal_sample(),
        "long_log": long_log_sample(),
        "mixed_warn_error": mixed_sample(),
    }
    truth: dict[str, dict] = {}
    for name, (lines, t) in cases.items():
        (SAMPLES / f"{name}.txt").write_text("\n".join(lines), encoding="utf-8")
        # 真因行号（1-based）；keyword 为 None 表示"这份输出本来就没错"
        if t["keyword"] is None:
            hits: list[int] = []
        else:
            hits = [i + 1 for i, ln in enumerate(lines) if t["keyword"] in ln]
        truth[name] = {"keyword": t["keyword"], "type": t["type"], "lines": hits,
                       "total_lines": len(lines)}
    (SAMPLES / "truth.json").write_text(
        json.dumps(truth, ensure_ascii=False, indent=2), encoding="utf-8")
    for name, t in truth.items():
        print(f"{name:20s} {t['total_lines']:4d} 行  真因行 {t['lines']}  {t['type']}")


if __name__ == "__main__":
    main()
