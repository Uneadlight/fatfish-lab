# D05 多后端抽象

> 出处：B06 `sqlite_db/sqlite_db.py`（Dialect 层）

## 解决什么问题

同一套 CRUD 代码要跑在 SQLite（开发/测试）和 MySQL（生产）上。两者的差异不是"连一下就行"：

| 差异点 | SQLite | MySQL |
|---|---|---|
| 占位符 | `?` | `%s` |
| UPSERT | `ON CONFLICT(x) DO UPDATE SET c=excluded.c` | `ON DUPLICATE KEY UPDATE c=VALUES(c)` |
| 编码设置 | `PRAGMA` | `SET NAMES utf8mb4` |
| 行转 dict | `sqlite3.Row` | 游标 `DictCursor` |

最常见写法是在每个函数里 `if dialect == "sqlite": ... else: ...` —— 分支散落在 10 个函数里，加第三个后端要改 10 处。

## 结构：方言是对象

```python
class Dialect:
    name = ""
    param = "?"
    def connect(self, dsn): ...
    def setup(self, conn): ...
    def placeholders(self, n): return ", ".join([self.param] * n)
    def upsert_sql(self, table, cols, key): ...
    def row_to_dict(self, row): ...

class SQLiteDialect(Dialect):
    name, param = "sqlite", "?"
    def connect(self, dsn):
        return sqlite3.connect(dsn, factory=_factory(self))   # 子类挂 dialect
    def setup(self, conn):
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
    def upsert_sql(self, table, cols, key):
        sets = ", ".join(f"{c}=excluded.{c}" for c in cols if c != key)
        return f"INSERT INTO {table} ({...}) VALUES ({...}) ON CONFLICT({key}) DO UPDATE SET {sets}"
```

## 三个关键决策

**① 方言必须跟着连接走，不能是模块级全局变量**
`query()` 拿到一个 conn 时，得知道"这一行怎么转成 dict"——那是方言的知识。所以方言附着在连接对象上（动态子类挂属性，因为 `sqlite3.Connection` 是 C 类型不能直接 `setattr`），而不是存一个全局 `CURRENT_DIALECT`。

**② 标识符白名单独立于方言**
表名/列名拼进 SQL 是注入面，白名单 `_IDENT = ^[A-Za-z_][A-Za-z0-9_]*$` 是所有方言共用的。它不属于"方言差异"，属于"通用安全"。

**③ 保持旧签名兼容**
`insert_many(conn, table, rows, dialect=None)` —— `dialect` 是可选参数，默认从 conn 取。这样老调用方不用改一行。

## 取舍

- **代价**：为 2 个后端做抽象，代码量约多 30%。**只有当第二个后端确定要来时才划算**
- **抽象层只该包"差异"，不该包"业务"**：事务、参数校验、错误映射放在上层，Dialect 只管 SQL 方言
- **诚实提醒**：本卡片的 MySQL 实现**只有形状、没有接驱动实测**。"切换成本从 1~2 小时降到改一个参数"是架构上的推断，未经真实验证

## 什么时候别用

- **只有一个后端**：别提前抽象。YAGNI 在这里是真的
- **两个后端的差异大到方言表装不下**（如 Mongo vs PostgreSQL）：它们不是"同一个抽象的两个实现"，硬套会变成 `if` 换了个位置写

## 判据

问自己：**"加第三个后端，要改几个文件？"** 一处（只加一个类）就对，十处就说明分支散落了。
