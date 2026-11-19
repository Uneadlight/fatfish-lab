#!/usr/bin/env python3
"""候选路线库编辑：把「加路线 + 补触发词」从手工改 Python 变成一条命令。

为什么要有它（2026-11-18）：
  最近 6 天往 tier_domains.py 手工补路线 20+ 次，同一个位置反复出三类错：
  ① 只加 routes 不补 words → 新路线永远命不中（11-14/11-15/11-16 至少四次实锤）；
  ② words 元组折行，按「行尾」替换把右括号切掉 → 文件语法错误；
  ③ 全角引号/长缩进让字符串锚点匹配失败 → 改错位置。

  这个工具用 AST 找域和列表边界，不靠字符串锚点；一次写入五元组 + 触发词；
  写前 py_compile + 载入校验 + path_options 读回，任何一步不过就一个字不写。

用法：
  lab route add --domain "长期机制" --code M --title "..." \
      --strength "..." --cost "..." --check "..." \
      --word "路线库维护" --word "加路线"
  lab route add ... --no-words          # 明确表示「现有触发词够用」
  lab route add ... --dry               # 只预览，不落盘
  lab route list [--domain 长期机制]
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import re
import shutil
import time
from pathlib import Path

LAB_DIR = Path(__file__).resolve().parent
TIER_DOMAINS = LAB_DIR / "tier_domains.py"


class RouteError(Exception):
    """参数/校验失败。CLI 打印成 [FAIL:...]，不写文件。"""


def _read_text(path: Path) -> str:
    # newline='' 保原样：tier_domains.py 是 LF，不要因为读一遍就变成 CRLF。
    with open(path, "r", encoding="utf-8", newline="") as f:
        return f.read()


def _write_text(path: Path, text: str) -> None:
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)


def _char_col(line: str, byte_col: int) -> int:
    """AST 的 col_offset 是 UTF-8 字节偏移，不是字符偏移；中文行必须转一次。"""
    raw = line.encode("utf-8")
    raw = raw[: max(0, min(byte_col, len(raw)))]
    return len(raw.decode("utf-8", errors="ignore"))


def _find_path_options(tree: ast.AST) -> ast.List:
    for node in getattr(tree, "body", []):
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "PATH_OPTIONS" for t in node.targets
        ):
            if isinstance(node.value, ast.List):
                return node.value
    raise RouteError("tier_domains.py 里找不到 PATH_OPTIONS = [...]")


def _dict_value(d: ast.Dict, key: str) -> ast.AST | None:
    for k, v in zip(d.keys, d.values):
        if isinstance(k, ast.Constant) and k.value == key:
            return v
    return None


def _domain_nodes(tree: ast.AST) -> list[tuple[str, ast.Dict]]:
    out = []
    for elt in _find_path_options(tree).elts:
        if not isinstance(elt, ast.Dict):
            continue
        d = _dict_value(elt, "domain")
        if isinstance(d, ast.Constant) and isinstance(d.value, str):
            out.append((d.value, elt))
    return out


def resolve_domain(domains: list[str], needle: str) -> str:
    """精确 → 前缀 → 子串；必须唯一，否则报候选让人自己选。"""
    needle = (needle or "").strip()
    if not needle:
        raise RouteError("--domain 不能为空")
    exact = [d for d in domains if d == needle]
    if len(exact) == 1:
        return exact[0]
    pref = [d for d in domains if d.startswith(needle)]
    if len(pref) == 1:
        return pref[0]
    sub = [d for d in domains if needle in d]
    if len(sub) == 1:
        return sub[0]
    pool = pref or sub or exact
    if not pool:
        raise RouteError(f"找不到域「{needle}」；现有域：\n  " + "\n  ".join(domains))
    raise RouteError(f"「{needle}」命中 {len(pool)} 个域，请写更精确：\n  " + "\n  ".join(pool))


def _line_starts(text: str) -> list[int]:
    starts = [0]
    for i, ch in enumerate(text):
        if ch == "\n":
            starts.append(i + 1)
    return starts


def _line_indent(lines: list[str], lineno: int) -> str:
    """第 lineno（1-based）行开头的空白；该行不是以元组开头时返回空串。"""
    if not (1 <= lineno <= len(lines)):
        return ""
    return re.match(r"^[ \t]*", lines[lineno - 1]).group(0) or ""


def _insert_into_sequence(
    text: str,
    node: ast.AST,
    new_items: list[str],
    *,
    element_indent: str,
    force_trailing_comma: bool,
) -> str:
    """在 AST 列表/元组的右括号前插入若干元素，保留 LF 与缩进。

    new_items 是已经格式化好的字面量（不含分隔逗号）。
    """
    lines = text.splitlines(keepends=True)
    idx = node.end_lineno - 1
    if idx < 0 or idx >= len(lines):
        raise RouteError("AST 结束行超出文件范围")
    raw_line = lines[idx]
    content = raw_line.rstrip("\r\n")
    end_char = _char_col(content, node.end_col_offset)
    if end_char <= 0:
        raise RouteError("AST 结束列无效")
    closing = content[end_char - 1]
    if closing not in ")]":
        raise RouteError(f"AST 结束位置不是右括号，而是 {closing!r}")
    before = content[: end_char - 1]
    own_line = not before.strip()

    if own_line:
        # 右括号独占一行：在它前面插新行，缩进用同层元素。
        prev_idx = idx - 1
        while prev_idx >= 0 and not lines[prev_idx].strip():
            prev_idx -= 1
        if prev_idx < 0:
            raise RouteError("右括号前没有内容，结构异常")
        prev_content = lines[prev_idx].rstrip("\r\n")
        prev_nl = lines[prev_idx][len(prev_content):]
        if not prev_content.rstrip().endswith(","):
            # 给上一行补逗号，保证新元素接得上。
            lines[prev_idx] = prev_content + "," + prev_nl
        block = ""
        for item in new_items:
            block += f"{element_indent}{item},\n"
        lines.insert(idx, block)
        return "".join(lines)

    # 右括号与最后一个元素同一行：在右括号前换行插入。
    abs_pos = sum(len(x) for x in lines[:idx]) + end_char - 1
    last_nonspace = before.rstrip()
    leading = "" if last_nonspace.endswith(",") else ","
    joined = (",\n" + element_indent).join(new_items)
    if force_trailing_comma:
        joined += ","
    inserted = leading + "\n" + element_indent + joined
    return text[:abs_pos] + inserted + text[abs_pos:]


def _fmt_route(indent: str, code: str, title: str, strength: str, cost: str, check: str) -> str:
    cont = indent + " "
    q = lambda s: json.dumps(s, ensure_ascii=False)  # noqa: E731
    return (
        f"{indent}({q(code)}, {q(title)},\n"
        f"{cont}{q(strength)},\n"
        f"{cont}{q(cost)},\n"
        f"{cont}{q(check)}),"
    )


def _fmt_word(word: str) -> str:
    return json.dumps(word, ensure_ascii=False)


def _domains_from_text(text: str, filename: str) -> list[dict]:
    """把候选文本当模块执行一遍，拿 PATH_OPTIONS（不生成 __pycache__）。"""
    ns: dict = {"__name__": "tier_domains_route_check", "__file__": filename}
    exec(compile(text, filename, "exec"), ns)  # noqa: S102 —— 执行的是自己的数据文件
    domains = ns.get("PATH_OPTIONS")
    if not isinstance(domains, list):
        raise RouteError("候选文本里没有 PATH_OPTIONS 列表")
    return domains


def _path_options_with(domains: list[dict], query: str) -> list[str]:
    """用候选数据跑一次真实选路，不落盘。返回命中的域名列表。"""
    try:
        import tier  # 延迟导入：只有校验时才需要
    except Exception as exc:  # noqa: BLE001
        raise RouteError(f"读回校验需要 tier.py，但导入失败：{exc}") from exc
    old = getattr(tier, "PATH_OPTIONS", None)
    tier.PATH_OPTIONS = domains
    try:
        opts = tier.path_options(query)
    finally:
        if old is not None:
            tier.PATH_OPTIONS = old
    return [o.get("domain") for o in opts]


def add_route(
    *,
    path: Path = TIER_DOMAINS,
    domain: str,
    code: str,
    title: str,
    strength: str,
    cost: str,
    check: str,
    words: list[str] | None = None,
    no_words: bool = False,
    queries: list[str] | None = None,
    dry: bool = False,
) -> dict:
    """加一条路线 + 触发词。失败抛 RouteError，原文件不动。"""
    words = [w.strip() for w in (words or []) if w.strip()]
    code = (code or "").strip()
    if not re.fullmatch(r"[A-Z]{1,3}", code):
        raise RouteError("--code 只能是 1–3 个大写字母（如 M / AA）")
    for label, val in (("--title", title), ("--strength", strength), ("--cost", cost), ("--check", check)):
        if not (val or "").strip():
            raise RouteError(f"{label} 不能为空")
    if no_words and words:
        raise RouteError("--no-words 和 --word 不能同时给：要么补词，要么明确说不补")
    if not no_words and not words:
        raise RouteError(
            "必须至少给一个 --word（只加 routes 不补 words，新路线永远命不中）；"
            "确认现有触发词够用，就加 --no-words"
        )

    path = Path(path)
    if not path.is_file():
        raise RouteError(f"找不到 {path}")
    text = _read_text(path)
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        raise RouteError(f"原文件语法已坏，先修它：{exc}") from exc

    nodes = _domain_nodes(tree)
    domain_names = [d for d, _ in nodes]
    real_domain = resolve_domain(domain_names, domain)
    dnode = next(n for name, n in nodes if name == real_domain)
    routes_node = _dict_value(dnode, "routes")
    words_node = _dict_value(dnode, "words")
    if not isinstance(routes_node, ast.List):
        raise RouteError(f"域「{real_domain}」没有 routes 列表")
    if not isinstance(words_node, (ast.Tuple, ast.List)):
        raise RouteError(f"域「{real_domain}」没有 words 元组/列表")

    old_routes = ast.literal_eval(routes_node)
    old_words = ast.literal_eval(words_node)
    if not isinstance(old_routes, list) or not isinstance(old_words, (list, tuple)):
        raise RouteError("routes/words 不是可读的字面量结构")
    if any(r[0] == code for r in old_routes if isinstance(r, (list, tuple)) and r):
        raise RouteError(f"域「{real_domain}」已经有代号 {code}，不覆盖")
    if len(old_routes) and not (isinstance(old_routes[-1], (list, tuple)) and len(old_routes[-1]) == 5):
        raise RouteError("现有 routes 不是五元组结构，先修数据")
    old_words = list(old_words)
    new_words = []
    for w in words:
        if w in old_words or w in new_words:
            continue
        new_words.append(w)
    if words and not new_words:
        raise RouteError("给的触发词都已在 words 里；不重复写。确认够用就加 --no-words")

    # 统一成两段：先插 words，再插 route。两次插入的行号会变，所以每次重新 parse。
    work = text
    if new_words:
        tree2 = ast.parse(work)
        nodes2 = {name: n for name, n in _domain_nodes(tree2)}
        dnode2 = nodes2[real_domain]
        words_node2 = _dict_value(dnode2, "words")
        assert isinstance(words_node2, (ast.Tuple, ast.List))
        lines2 = work.splitlines()
        tuple_line = lines2[words_node2.lineno - 1]
        tuple_col = _char_col(tuple_line, words_node2.col_offset)
        word_indent = " " * (tuple_col + 1)
        work = _insert_into_sequence(
            work,
            words_node2,
            [_fmt_word(w) for w in new_words],
            element_indent=word_indent,
            force_trailing_comma=True,
        )

    tree3 = ast.parse(work)
    nodes3 = {name: n for name, n in _domain_nodes(tree3)}
    dnode3 = nodes3[real_domain]
    routes_node3 = _dict_value(dnode3, "routes")
    assert isinstance(routes_node3, ast.List)
    lines3 = work.splitlines()
    if routes_node3.elts:
        first = routes_node3.elts[0]
        first_line = lines3[first.lineno - 1]
        route_indent = _line_indent(lines3, first.lineno)
        # 元组和 "routes": [ 在同一行时不能拿整行缩进，退回 12 空格。
        if first_line[: _char_col(first_line, first.col_offset)].strip():
            route_indent = " " * 12
    else:
        route_indent = " " * 12
    route_text = _fmt_route(route_indent, code, title.strip(), strength.strip(), cost.strip(), check.strip())
    work = _insert_into_sequence(
        work,
        routes_node3,
        [route_text.strip().rstrip(",")],
        element_indent=route_indent,
        force_trailing_comma=True,
    )

    # 写临时文件 → py_compile → 载入校验 → 读回，全过才落盘。
    tmp = path.with_name(path.name + f".tmp-{os.getpid()}-{int(time.time())}")
    try:
        _write_text(tmp, work)
        import py_compile

        py_compile.compile(str(tmp), cfile=str(tmp) + ".pyc", doraise=True)
        new_domains = _domains_from_text(work, str(tmp))
        if len(new_domains) != len(nodes):
            raise RouteError(f"域数变了：{len(nodes)} → {len(new_domains)}")
        target = next((d for d in new_domains if d.get("domain") == real_domain), None)
        if target is None:
            raise RouteError("写入后找不到目标域")
        if len(target["routes"]) != len(old_routes) + 1:
            raise RouteError(f"路线数不是 +1：{len(old_routes)} → {len(target['routes'])}")
        last = target["routes"][-1]
        if tuple(last) != (code, title.strip(), strength.strip(), cost.strip(), check.strip()):
            raise RouteError("写入后的五元组和输入不一致")
        if any(len(r) != 5 for r in target["routes"]):
            raise RouteError("目标域出现非五元组路线")
        for w in new_words:
            if w not in target["words"]:
                raise RouteError(f"触发词没进 words：{w}")

        queries = [q for q in (queries or []) if q.strip()] or new_words[:1]
        for q in queries:
            hit = _path_options_with(new_domains, q)
            if real_domain not in hit:
                raise RouteError(
                    f'读回失败：path_options("{q}") 没命中「{real_domain}」'
                    f"（命中：{hit or '无'}）。新路线会看不见，已放弃写入。"
                )
        try:
            Path(str(tmp) + ".pyc").unlink(missing_ok=True)
        except OSError:
            pass
    except Exception:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        try:
            Path(str(tmp) + ".pyc").unlink(missing_ok=True)
        except OSError:
            pass
        raise

    backup = None
    if not dry:
        stamp = time.strftime("%Y%m%d-%H%M%S")
        backup = path.with_name(path.name + f".bak-{stamp}-route")
        n = 1
        while backup.exists():
            backup = path.with_name(path.name + f".bak-{stamp}-route-{n}")
            n += 1
        shutil.copy2(path, backup)
        os.replace(tmp, path)
        # 只留最新一份同类备份（章程硬要求；不动 11-13 那些历史 .bak）
        for old in path.parent.glob(path.name + ".bak-*-route*"):
            if old != backup and old.is_file():
                try:
                    old.unlink()
                except OSError:
                    pass
    else:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass

    return {
        "domain": real_domain,
        "routes_before": len(old_routes),
        "routes_after": len(old_routes) + 1,
        "words_before": len(old_words),
        "words_after": len(old_words) + len(new_words),
        "words_added": new_words,
        "backup": str(backup) if backup else "",
        "dry": dry,
        "queries": queries if "queries" in locals() else [],
    }


# ---------------------------------------------------------------- CLI
def cmd_add(a: argparse.Namespace) -> int:
    try:
        r = add_route(
            path=Path(a.file),
            domain=a.domain,
            code=a.code,
            title=a.title,
            strength=a.strength,
            cost=a.cost,
            check=a.check,
            words=a.word or [],
            no_words=a.no_words,
            queries=a.query or [],
            dry=a.dry,
        )
    except RouteError as exc:
        print(f"[FAIL:参数/校验] {exc}")
        return 2
    except Exception as exc:  # noqa: BLE001
        print(f"[FAIL:未预期] {type(exc).__name__}: {exc}")
        return 2
    tag = "[DRY]" if r["dry"] else "[OK]"
    print(f"{tag} 域「{r['domain']}」：路线 {r['routes_before']} → {r['routes_after']}")
    if r["words_added"]:
        print(f"     触发词 {r['words_before']} → {r['words_after']}：+{'、'.join(r['words_added'])}")
    else:
        print("     触发词：未改（--no-words 或没有新词）")
    if r["backup"]:
        print(f"     备份：{r['backup']}")
    if r["queries"]:
        print(f"     读回：path_options 已命中域「{r['domain']}」（查询：{r['queries'][0]}）")
    if not r["dry"]:
        print("     下一步：lab test → 重建 .tmp/tier-baseline.py 基线 → lab selfcheck")
    else:
        print("     这是 --dry：没有写文件、没有备份")
    return 0


def cmd_list(a: argparse.Namespace) -> int:
    path = Path(a.file)
    if not path.is_file():
        print(f"[FAIL:参数] 找不到 {path}")
        return 2
    tree = ast.parse(_read_text(path))
    rows = []
    for name, dnode in _domain_nodes(tree):
        if a.domain and a.domain not in name:
            continue
        routes = _dict_value(dnode, "routes")
        words = _dict_value(dnode, "words")
        nr = len(ast.literal_eval(routes)) if isinstance(routes, (ast.List, ast.Tuple)) else -1
        nw = len(ast.literal_eval(words)) if isinstance(words, (ast.Tuple, ast.List)) else -1
        codes = []
        if isinstance(routes, (ast.List, ast.Tuple)):
            codes = [r[0] for r in ast.literal_eval(routes) if isinstance(r, (list, tuple)) and r]
        rows.append((name, nr, nw, codes[-1] if codes else ""))
    if not rows:
        print("没有匹配的域")
        return 0
    for name, nr, nw, last in rows:
        print(f"- {name}：{nr} 条路线 / {nw} 个触发词（最后一个代号 {last or '—'}）")
    print(f"共 {len(rows)} 个域")
    return 0


def register(sub) -> None:
    p = sub.add_parser(
        "route",
        help="候选路线库编辑：加路线 + 补触发词一次做完（AST 定位 / 备份 / 读回校验）",
    )
    s = p.add_subparsers(dest="route_cmd", required=True)

    a = s.add_parser("add", help="加一条路线（默认必须同时补 --word）")
    a.add_argument("--domain", required=True, help="域名，可写前缀/子串，必须唯一命中")
    a.add_argument("--code", required=True, help="路线代号，1–3 个大写字母")
    a.add_argument("--title", required=True, help="路线名（一句话）")
    a.add_argument("--strength", required=True, help="长处")
    a.add_argument("--cost", required=True, help="代价")
    a.add_argument("--check", required=True, help="怎么验")
    a.add_argument("--word", action="append", default=[], help="触发词，可重复；至少一个")
    a.add_argument("--no-words", action="store_true", help="明确表示现有触发词够用，不补词")
    a.add_argument("--query", action="append", default=[], help="读回查询，可重复；默认用第一个新词")
    a.add_argument("--file", default=str(TIER_DOMAINS), help="目标文件（测试用，默认 tier_domains.py）")
    a.add_argument("--dry", action="store_true", help="只校验和预览，不写文件")
    a.set_defaults(func=cmd_add)

    ls = s.add_parser("list", help="列出现有域 / 路线数 / 触发词数")
    ls.add_argument("--domain", default="", help="只看名字含这个子串的域")
    ls.add_argument("--file", default=str(TIER_DOMAINS), help="目标文件（测试用）")
    ls.set_defaults(func=cmd_list)

    p.set_defaults(route_parser=p)
