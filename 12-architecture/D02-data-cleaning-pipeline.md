# D02 数据清洗流水线

> 出处：Q02 边界用例集、W03 流式改造（`clean_pipeline/pipeline.py` + `workbench_v2/app.py`）

## 解决什么问题

一批外部数据（CSV/Excel 上传）要清洗、校验、去重、统计，还要给前端报进度。三个硬约束：

1. **不能全读进内存**——10 万行全读峰值 50.6MB，100 万行就崩
2. **统计要能对账**——"处理了 10 万行，通过了 9.2 万"，剩下 8 千去哪了必须能说清
3. **进度要单调**——前端进度条不能跳回去

## 结构

```
生成器输入           流式消费              计数器/回调
_iter_rows(path)  →  clean_rows(rows)  →  report + progress(i)
```

```python
def _iter_rows(path, ext):
    """生成器：一次只持有一行"""
    if ext == ".csv":
        with open(path, encoding="utf-8-sig", newline="") as fh:
            for row in csv.DictReader(fh):
                yield row
    else:
        wb = load_workbook(path, read_only=True, data_only=True)
        try:
            for row in wb.active.iter_rows(values_only=True):
                yield row
        finally:
            wb.close()

def clean_rows(rows, dedupe_key="id", progress=None):
    clean, seen, i = [], set(), 0
    report = dict(total=0, ok=0, blank=0, bad_id=0, dup=0, key_missing=0, warn_date=0, rate=0.0)
    for i, raw in enumerate(rows, 1):          # 注意：不要先 list(rows)
        # 判定顺序固定：空 → 缺键 → 重复 → 坏证件
        ...
        if progress and i % 500 == 0:
            progress(i)
    report["total"] = i
    if progress and i and i % 500:
        progress(i)                            # 末尾必须补调
    report["rate"] = round(report["ok"] / i, 4) if i else 0.0
    return clean, report
```

## 四个关键点

**① 判定顺序不能换：空行 → 缺键 → 重复 → 坏证件。**
顺序反了会把空 key 判成"重复"——第一个空 key 进了 `seen` 集合，第二个空 key 就变成 dup 而不是 key_missing，报表全错。

**② 对账恒等式**：`ok + blank + bad_id + dup + key_missing == total`。
"非法但保留"（如日期格式错，`date=""` + `warn_date++`）**不进这个和**——它不是被拒绝，是被降级保留。混进去就永远对不平。

**③ 进度末尾必报**：1200 行的循环只在 500/1000 报，前端停在 83% 永远不到 100%。循环后补 `if i % 500: progress(i)`。

**④ 去重集合只存 key，不存整行**。10 万个 key 的 `set` 约 5MB，存整行就白流式了。

## 取舍

- **流式代价**：不能回头看。需要"和前 1000 行比对"这类逻辑就没法纯流式，得用滑动窗口或二次遍历
- **`total` 只能边跑边数**：想在上传时立刻显示总数，得单独 `_count_rows()`（xlsx 用 `ws.max_row`，csv 用 `sum(1 for _ in fh) - 1`），内存 O(1)
- **实测数据**（10 万行 CSV / 4.7MB / tracemalloc）：全读 50.6MB vs 流式 0.2MB，**626 倍**

## 什么时候别用

- **数据 < 1 万行**：全读再处理更简单，流式是为省内存，不是为了显技术
- **需要多轮遍历**：排序、聚合、二次校验都要求数据在内存里，硬流式会变成反复读盘

## 顺带一条：为什么不上多进程

清洗是 **I/O 密集**（读盘、编解码），不是 CPU 密集。GIL 不是瓶颈，多进程还要逐行 pickle 序列化——10 万行的序列化开销超过整个处理时间（2.0s）。**并发该用线程，内存该用流式，别把两个问题混在一起解决。**
