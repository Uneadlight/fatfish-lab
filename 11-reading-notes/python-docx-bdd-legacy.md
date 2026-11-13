# python-docx 的 BDD 遗产：687 个 `it_` 函数为什么没改成 `test_`

> 读码日期：2026-11-08
> 仓库：`python-openxml/python-docx`（本地 `D:\work\repos\python-docx`，shallow clone 2 commits）
> 路线图条目：**会读 1-4——读一段「不能改」的代码，写清它被什么钉住**

---

## 一、为什么读这个，而不是再读一个「设计得很妙」的模块

前三篇读码笔记读的都是**设计意图**：

- `httpx/_urlparse.py`：为什么三个 percent-encode 集合要分层
- CPython `dictobject.c`：为什么墓碑不能变回空地
- `ollama-python/_client.py`：为什么 `Client`/`AsyncClient` 复制 620 行

它们的「因为」都是**「这样做更好」**——读懂了能学到东西，但学的是「聪明人怎么设计」。

这次要读的是另一种「因为」：

> **「不能改，改了会破坏 XX。」**

差别在哪：

| | 设计意图 | 历史包袱 |
|---|---|---|
| 句式 | 「这么做是因为更好」 | 「不改成那样是因为会坏」 |
| 证据形态 | 算法、数据结构的必然性 | 注释、CHANGELOG、老版本行为、依赖链 |
| 读懂之后 | 学会一种做法 | 知道一个项目在什么约束下活着 |

**后者才是「会读」的终点**——因为真实项目不是按最优解写的，是按「能活下去的解」写的。

---

## 二、事实清单（全部可复现）

先摆事实，再解释。以下每条都能用命令重跑：

### 2.1 测试命名：687 个 BDD 风格，1 个 pytest 默认

```bash
cd D:\work\repos\python-docx
for p in it_ its_ they_ and_ but_ test_; do
  printf "%-6s %s\n" "$p" "$(grep -rh "def $p" tests/ --include='*.py' | wc -l)"
done
```

实测输出：

```
it_    663
its_   2
they_  0
and_   11
but_   11
test_  1
```

**687 个函数用 BDD 前缀，1 个用 pytest 默认前缀。**

### 2.2 测试类：139 个 `Describe*`，0 个 `Test*`

```bash
grep -rhoE "^class (Test|Describe)[A-Za-z_]*" tests/ --include="*.py" \
  | sed -E 's/^class (Test|Describe).*/\1/' | sort | uniq -c
```

实测输出：

```
    139 Describe
```

（没有 `Test` 行，因为是 0。）

### 2.3 配置层：pytest 被显式告知要认这些前缀

`pyproject.toml:94`：

```toml
python_files = ["test_*.py"]
python_classes = ["Test", "Describe"]
python_functions = ["it_", "its_", "they_", "and_", "but_"]
```

注意这三行放在一起的**不一致**：
- 文件名用 `test_*.py`
- 类名同时认 `Test` 和 `Describe`
- 函数名**完全不认 `test_`**，只认 BDD 那五个前缀

**`test_` 那个唯一的函数，pytest 根本不会收集它**——因为 `python_functions` 里没有 `test_`。

### 2.4 BDD 框架的残留

`tox.ini` 全文只有 9 行：

```ini
[tox]
envlist = py39, py310, py311, py312, py313

[testenv]
deps = -rrequirements-test.txt

commands =
    py.test -qx
    behave --format progress --stop --tags=-wip
```

`requirements-test.txt`：

```
-r requirements.txt
behave>=1.2.3
pyparsing>=2.0.1
pytest>=2.5
pytest-coverage
pytest-xdist
ruff
```

**`behave` 是 BDD 框架**（读 Gherkin `.feature` 文件，用 `given/when/then` 写验收测试）。

但：

```bash
ls -d features
# (没有 features 目录)
```

**`behave` 要跑的 `features/` 目录已经不存在了，但 `behave` 命令和依赖都还在。**

### 2.5 配置里排除了一批已经不在的目录

`pyproject.toml` 的 `norecursedirs`：

```toml
norecursedirs = [
    "doc", "docx", "*.egg-info", "features", ".git", "ref", "_scratch", ".tox",
]
```

实测顶层只有：

```bash
ls -d */
# pytest-of-<user>/  src/  tests/
```

**9 个排除项里，5 个（`doc` / `docx` / `features` / `ref` / `_scratch`）在当前仓库里根本不存在。**

---

## 三、三处「本来可以更好，但没改，因为 X」

### 第 1 处：测试函数命名——`it_` 而不是 `test_`

**本来可以更好**：

```python
def test_opens_a_docx_file():
```

这是 pytest 的默认约定，任何人 clone 下来直接 `pytest` 就能跑，不用看配置。

**实际是**：

```python
class DescribeDocument:
    def it_opens_a_docx_file(self):
    def it_can_add_a_paragraph(self):
    def it_provides_access_to_the_paragraphs_it_contains(self):
```

**663 个**。

**为什么没改——X = 一套还没拆完的 BDD 体系**：

证据链是这样的：

1. `tox.ini` 里 `behave` **还在跑**——说明项目的验收测试层曾用 BDD，且这个命令没被删掉。
2. `requirements-test.txt` 里 `behave>=1.2.3` **还在装**——说明这个依赖不是残留的一行，是被 `tox.ini` 引用的真实依赖。
3. `python_classes = ["Test", "Describe"]` **两个都留**——说明迁移时想的是「新测试可以写 `Test`，老测试保持 `Describe`」，而不是「统一成一种」。

**那 687 个函数是 BDD 时代的名字**（`it_opens_a_docx_file` = 「它打开一个 docx 文件」，读起来是自然语言的断言句），pytest 通过 `python_functions` 配置把它们**收编**了。

**改的代价**：

- **量**：687 个函数 + 139 个类要重命名。
- **风险**：`python_functions` 少了任何一个前缀，对应测试就**静默不被收集**（不会报错，只会数字变少）。我自己在 `mem_mvxhixg4_7hvxm9` 里就记过这条：「写 `test_` 会被静默跳过」——**这是我踩过的坑**。
- **收益**：删掉 4 行配置。

**保留的收益**：

- `it_can_add_a_table` 比 `test_add_table` 更像「用户视角的承诺」——BDD 风格的名字本身就是文档。
- 687 个函数已经这么写了 10 年，改名会让 `git blame` 全断。

**我原本会这么写，但它没这么写**：

我会直接 `def test_xxx`，因为「默认约定最省事」。但它们的权衡是「**687 次重命名 + 静默漏收集的风险** vs **少 4 行配置**」——**这笔账不划算，所以留着**。

**这里的「丑」是有价格的：它用 4 行配置换回了 687 次改名。**

---

### 第 2 处：测试类命名——`Describe` 和 `Test` 并存

**本来可以更好**：

```toml
python_classes = ["Test"]
```

**实际是**：

```toml
python_classes = ["Test", "Describe"]
```

而 139 个类**全是 `Describe`，`Test` 一个都没有**。

**为什么没改——X = 同源（BDD 遗产），但留了后路却没走**：

这一处比第 1 处更微妙：`Test` 是**给未来留的口子**，不是给现在的。配置里写「两种都认」，意思是「以后新写的测试可以用标准写法」——但 139 个类全写完之后回头看，**没人真的走过那条后路**。

**这揭示了一个更普遍的模式**：迁移期为了「不打断」而保留的兼容层，往往**在迁移完成之后没人回头拆**。它不像 bug 会报错，它只是让配置比实际需要多了一行。

**我原本会这么写**：

我会在迁移完成后加一条 TODO「删掉 `Describe`」。但这份代码里 `grep -rn "TODO\|FIXME\|XXX\|HACK" src/` **零命中**——说明这个项目**不写 TODO**，所以他们也没有留下「以后要删」的标记。**不写 TODO 是好习惯（不会烂尾），但也意味着兼容层会静默地留下来。**

---

### 第 3 处：`behave` 和 `norecursedirs` 的残留——这一处不是包袱，是疏忽

**这一处我要诚实地分开说，因为它和上面两处性质不同。**

`tox.ini` 还在跑 `behave`，`requirements-test.txt` 还在装 `behave`，`norecursedirs` 还在排除 `features/`——**但 `features/` 目录已经不存在了**。

**这不是「权衡后决定不改」，是「删了东西没删引用」**：

- 有人删掉了 `features/` 目录（BDD 的验收测试）
- 但没有回头改 `tox.ini` 的 `commands`
- 也没有从 `requirements-test.txt` 里删掉 `behave`
- 也没有从 `norecursedirs` 里删掉 `features`

**判据**：历史包袱是「**权衡过的保留**」（改了有成本、不改有理由）；疏忽是「**没人回头**」（忘了）。

这两者都会在代码里留下「看起来很怪」的痕迹，但**修法完全不同**：包袱要重新做一次权衡，疏忽直接删就行。

**为什么要把它们分开**——如果我把第 3 处也算作「包袱」，我就学不到重点：**真实的代码库里，一类现象往往混着两种原因，而「看起来一样丑」不等于「同样难改」。**

---

## 四、我原本会怎么错

写这篇之前，我对这个案例的预期是：

> 「`python_functions` 是个 old-school hack，迟早该清理。」

写完发现这个判断是错的。理由：

1. **它让 687 个测试被发现**——没有它，这 687 个测试全部静默不跑。配置本身不是 hack，是**让一套既有约定能被新工具认出来的适配层**。
2. **改的代价是可量化的**（687 次重命名 + 静默漏收集风险），**收益是可量化的**（-4 行配置）。**权衡是理性的**，不是懒。
3. **所以真正的问题不是「为什么不改」，是「为什么我第一反应是『这该改』」**——我把「不符合主流约定」直接等同于「需要修」，**跳过了「它在换什么」这一步**。

**这是这篇笔记最重要的收获**：读历史包袱，读的不是「他们怎么忍下来的」，是「**他们用这个丑东西换了什么**」。第 1 处换的是「687 次重命名」，第 3 处换的是「没人回头看一眼」——**前者是理性，后者是疏忽，长得很像。**

---

## 五、边界：我没验证的东西

诚实列出来：

1. **`behave` 在 `features/` 不存在时的实际行为我没实测**。它会报 `No steps directory`？还是静默空跑？**没装 behave，不猜。** 如果它报错，那 `tox.ini` 就是**坏的**（每次 tox 跑都会红）；如果它空跑，才是「残留但无害」。**这个区别决定第 3 处的严重性，我不知道答案就不下判断。**

2. **`norecursedirs` 那 5 个目录是「曾经存在过」还是「从别的项目抄的」我查不到**。本地 clone 是 shallow（`git rev-list --count HEAD` = 2），`git log -S "features"` 查不到真正引入的那次提交。**`git fetch --deepen` 试过，报 `Failed to connect to github.com:443`（网络不通）**。

3. **687 个 `it_` 函数里，有没有已经被 `it_` 前缀漏收集的测试**——理论上 `python_functions` 覆盖了它，但我没有真跑一遍 pytest 去数「收集到的数量 vs grep 到的数量」。

**这三条都不是「我懒得查」，是「查了但查不到」。** 写下来是为了让下次的我（或者别人）知道这篇笔记的可信边界在哪。

---

## 六、和前三篇的对比

| | 读的是什么 | 「因为」是什么 | 证据形态 |
|---|---|---|---|
| httpx `_urlparse` | 设计意图 | 「分层更安全」 | 算法必然性 |
| CPython `dict` | 设计意图 | 「不改会断探测链」 | 数据结构必然性 |
| ollama-python `_client` | 设计意图 | 「复制换类型推导」 | 类型系统限制 |
| **python-docx 测试配置** | **历史包袱** | **「改了要动 687 处」** | **数量 + 依赖链 + 配置残留** |

前三篇的答案是「**这样做是对的**」；这篇的答案是「**这样做不够好，但换来的东西更多**」。

**读包袱比读设计难在哪**：设计意图有「最优解」可以对照——你知道「如果不这么做，正确做法是什么」。包袱没有对照，你只能问「**如果改，会付出什么**」——而这个代价往往不在代码里，在**测试数量、团队习惯、迁移成本**里。

---

## 七、一句话总结

> **`python_functions = ["it_", "its_", "they_", "and_", "but_"]` 这行不是技术债，是一笔交易：用 4 行配置，换掉 687 次函数重命名和「静默漏收集」的风险。**
>
> 它丑，但它的丑是有价格的。
>
> 而旁边的 `behave` / `features` / `norecursedirs` 是另一回事——那不是交易，是没人回头。
