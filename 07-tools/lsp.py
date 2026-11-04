"""用语言服务器回答「这个符号在哪定义 / 谁引用它」——治 P11「只能靠 grep 摸黑」。

不自己解析代码，接现成的 LSP 服务。默认 `pyright-langserver --stdio`
（装了就有：`npm i -g pyright`；换语言只需换 `--server`）。
协议是 JSON-RPC over stdio：每个消息 `Content-Length: N\\r\\n\\r\\n` + JSON 正文。

用法：
    lab lsp def <file> <line> <col>       # 跳转定义
    lab lsp refs <file> <line> <col>      # 找引用
    lab lsp symbols <file>                # 文件内符号（类/函数/变量）
    lab lsp hover <file> <line> <col>     # 类型/签名

行和列从 1 开始（跟编辑器一样），内部转 LSP 的 0-based。
第一次请求要等 server 建索引（几百毫秒到几秒），超时 --timeout 秒（默认 30）。

边界：静态分析只认「它看得懂的代码」。动态拼出来的属性、`**kwargs` 传进去再取、
字符串当属性名——LSP 也给不出答案，这时它会返回空而不是错，别把「空」当「不存在」。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import threading
from pathlib import Path

DEFAULT_TIMEOUT = 30.0


def find_server(explicit: str | None = None) -> list[str]:
    """返回启动命令。显式给的直接按空格拆，否则按常见位置找 pyright。"""
    if explicit:
        return explicit.split()
    appdata = os.environ.get('APPDATA', '')
    candidates = [
        Path(appdata) / 'npm' / 'pyright-langserver.cmd',
        Path(appdata) / 'npm' / 'pyright-langserver.ps1',
    ]
    for c in candidates:
        if c.suffix == '.cmd' and c.is_file():
            return [str(c), '--stdio']
    js = Path(appdata) / 'npm' / 'node_modules' / 'pyright' / 'langserver.index.js'
    if js.is_file():
        return ['node', str(js), '--stdio']
    raise FileNotFoundError('找不到 pyright-langserver。先装：npm i -g pyright，或用 --server 指定')


def path_to_uri(p: Path) -> str:
    return 'file:///' + str(p.resolve()).replace('\\', '/')


def uri_to_path(uri: str) -> Path:
    from urllib.parse import unquote, urlparse
    u = urlparse(uri)
    p = unquote(u.path)
    if re.match(r'^/[A-Za-z]:', p):
        p = p[1:]
    return Path(p)


class LSP:
    """最小 LSP 客户端：请求-响应 + 忽略通知，超时杀进程。"""

    def __init__(self, cmd: list[str], root: Path, timeout: float = DEFAULT_TIMEOUT):
        self.timeout = timeout
        self.proc = subprocess.Popen(
            cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            cwd=str(root),
        )
        self.next_id = 1
        self.buf = b''

    def _send(self, payload: dict) -> None:
        body = json.dumps(payload).encode('utf-8')
        self.proc.stdin.write(f'Content-Length: {len(body)}\r\n\r\n'.encode('ascii') + body)
        self.proc.stdin.flush()

    def _read_message(self) -> dict:
        while b'\r\n\r\n' not in self.buf:
            chunk = self.proc.stdout.read1(4096)
            if not chunk:
                err = self.proc.stderr.read(4000).decode('utf-8', 'replace') if self.proc.stderr else ''
                raise EOFError(f'语言服务器提前退出。stderr:\n{err}')
            self.buf += chunk
        head, self.buf = self.buf.split(b'\r\n\r\n', 1)
        m = re.search(rb'Content-Length:\s*(\d+)', head)
        if not m:
            raise ValueError(f'响应头里没有 Content-Length: {head!r}')
        length = int(m.group(1))
        while len(self.buf) < length:
            chunk = self.proc.stdout.read1(length - len(self.buf))
            if not chunk:
                raise EOFError('响应正文没读全就断了')
            self.buf += chunk
        body, self.buf = self.buf[:length], self.buf[length:]
        return json.loads(body)

    def request(self, method: str, params: dict, timeout: float | None = None) -> dict:
        rid = self.next_id
        self.next_id += 1
        self._send({'jsonrpc': '2.0', 'id': rid, 'method': method, 'params': params})
        box: dict = {}

        def _pump():
            try:
                while True:
                    msg = self._read_message()
                    if msg.get('id') == rid:
                        box['msg'] = msg
                        return
            except Exception as exc:  # noqa: BLE001 - 把异常带回主线程
                box['err'] = exc

        t = threading.Thread(target=_pump, daemon=True)
        t.start()
        t.join(timeout if timeout is not None else self.timeout)
        if t.is_alive():
            self.kill()
            raise TimeoutError(f'{method} 等了 {self.timeout:.0f}s 没回（大项目第一次建索引会慢，加 --timeout）')
        if 'err' in box:
            raise box['err']
        return box.get('msg') or {}

    def notify(self, method: str, params: dict) -> None:
        self._send({'jsonrpc': '2.0', 'method': method, 'params': params})

    def initialize(self, root: Path) -> None:
        res = self.request('initialize', {
            'processId': os.getpid(),
            'rootUri': path_to_uri(root),
            'capabilities': {
                'textDocument': {
                    'definition': {'linkSupport': False},
                    'references': {},
                    'hover': {'contentFormat': ['plaintext', 'markdown']},
                    'documentSymbol': {'hierarchicalDocumentSymbolSupport': True},
                    'publishDiagnostics': {},
                },
            },
            'workspaceFolders': [{'uri': path_to_uri(root), 'name': root.name}],
        }, timeout=self.timeout)
        self.server_info = (res.get('result') or {}).get('serverInfo') or {}
        self.notify('initialized', {})

    def open(self, path: Path) -> None:
        text = path.read_text(encoding='utf-8', errors='replace')
        self.notify('textDocument/didOpen', {
            'textDocument': {'uri': path_to_uri(path), 'languageId': lang_id(path),
                             'version': 1, 'text': text},
        })

    def kill(self) -> None:
        try:
            self.proc.kill()
        except Exception:
            pass


def lang_id(p: Path) -> str:
    return {
        '.py': 'python', '.pyi': 'python', '.ts': 'typescript', '.tsx': 'typescriptreact',
        '.js': 'javascript', '.jsx': 'javascriptreact', '.json': 'json',
        '.go': 'go', '.rs': 'rust', '.c': 'c', '.h': 'c', '.cpp': 'cpp', '.hpp': 'cpp',
    }.get(p.suffix.lower(), 'plaintext')


def read_line(path: Path, line0: int) -> str:
    try:
        lines = path.read_text(encoding='utf-8', errors='replace').splitlines()
        return lines[line0].strip() if 0 <= line0 < len(lines) else ''
    except OSError:
        return ''


def fmt_location(uri: str, rng: dict) -> str:
    p = uri_to_path(uri)
    line0 = (rng.get('start') or {}).get('line', 0)
    text = read_line(p, line0)
    return f'{p}:{line0 + 1}  {text[:110]}'


def cmd_def(args) -> int:
    path = Path(args.file).resolve()
    root = Path(args.root).resolve() if args.root else path.parent
    client = LSP(find_server(args.server), root, args.timeout)
    try:
        client.initialize(root)
        client.open(path)
        res = client.request('textDocument/definition', {
            'textDocument': {'uri': path_to_uri(path)},
            'position': {'line': args.line - 1, 'character': args.col - 1},
        })
    finally:
        client.kill()
    result = res.get('result')
    if res.get('error'):
        print(f"[FAIL] {res['error'].get('message')}")
        return 1
    if not result:
        print('[空] 语言服务器没给出定义——可能是动态代码，或光标不在符号上')
        return 0
    items = result if isinstance(result, list) else [result]
    print(f'[OK] 定义 {len(items)} 处')
    for it in items:
        if 'targetUri' in it:  # LocationLink
            print('  ' + fmt_location(it['targetUri'], it.get('targetSelectionRange') or it.get('targetRange') or {}))
        else:
            print('  ' + fmt_location(it['uri'], it.get('range') or {}))
    return 0


def cmd_refs(args) -> int:
    path = Path(args.file).resolve()
    root = Path(args.root).resolve() if args.root else path.parent
    client = LSP(find_server(args.server), root, args.timeout)
    try:
        client.initialize(root)
        client.open(path)
        res = client.request('textDocument/references', {
            'textDocument': {'uri': path_to_uri(path)},
            'position': {'line': args.line - 1, 'character': args.col - 1},
            'context': {'includeDeclaration': True},
        })
    finally:
        client.kill()
    result = res.get('result')
    if res.get('error'):
        print(f"[FAIL] {res['error'].get('message')}")
        return 1
    if not result:
        print('[空] 没找到引用（可能只有定义处，或光标不在符号上）')
        return 0
    print(f'[OK] 引用 {len(result)} 处')
    for it in result:
        print('  ' + fmt_location(it['uri'], it.get('range') or {}))
    return 0


def cmd_hover(args) -> int:
    path = Path(args.file).resolve()
    root = Path(args.root).resolve() if args.root else path.parent
    client = LSP(find_server(args.server), root, args.timeout)
    try:
        client.initialize(root)
        client.open(path)
        res = client.request('textDocument/hover', {
            'textDocument': {'uri': path_to_uri(path)},
            'position': {'line': args.line - 1, 'character': args.col - 1},
        })
    finally:
        client.kill()
    result = res.get('result')
    if res.get('error') or not result:
        print('[空] 没有悬停信息')
        return 0
    contents = result.get('contents') or {}
    if isinstance(contents, dict):
        print(contents.get('value', ''))
    elif isinstance(contents, list):
        for c in contents:
            print(c.get('value', '') if isinstance(c, dict) else str(c))
    else:
        print(str(contents))
    return 0


def _flatten_symbols(syms: list[dict], depth: int = 0) -> None:
    for s in syms:
        kind = s.get('kind')
        rng = s.get('selectionRange') or s.get('range') or {}
        line0 = (rng.get('start') or {}).get('line', 0)
        name = s.get('name', '?')
        detail = s.get('detail', '')
        print(f'{"  " * depth}{name}  [kind={kind}]  L{line0 + 1}' + (f'  {detail}' if detail else ''))
        if s.get('children'):
            _flatten_symbols(s['children'], depth + 1)


def cmd_symbols(args) -> int:
    path = Path(args.file).resolve()
    root = Path(args.root).resolve() if args.root else path.parent
    client = LSP(find_server(args.server), root, args.timeout)
    try:
        client.initialize(root)
        client.open(path)
        res = client.request('textDocument/documentSymbol', {
            'textDocument': {'uri': path_to_uri(path)},
        })
    finally:
        client.kill()
    result = res.get('result')
    if res.get('error'):
        print(f"[FAIL] {res['error'].get('message')}")
        return 1
    if not result:
        print('[空] 没拿到符号表')
        return 0
    print(f'[OK] {len(result)} 个顶层符号')
    _flatten_symbols(result)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='action', required=True)

    def common(p):
        p.add_argument('file')
        p.add_argument('--root', help='项目根（默认文件所在目录），大项目给仓库根更准')
        p.add_argument('--server', help='自定义启动命令，如 "pylsp"')
        p.add_argument('--timeout', type=float, default=DEFAULT_TIMEOUT)

    p = sub.add_parser('def')
    common(p)
    p.add_argument('line', type=int)
    p.add_argument('col', type=int)
    p.set_defaults(func=cmd_def)

    p = sub.add_parser('refs')
    common(p)
    p.add_argument('line', type=int)
    p.add_argument('col', type=int)
    p.set_defaults(func=cmd_refs)

    p = sub.add_parser('hover')
    common(p)
    p.add_argument('line', type=int)
    p.add_argument('col', type=int)
    p.set_defaults(func=cmd_hover)

    p = sub.add_parser('symbols')
    common(p)
    p.set_defaults(func=cmd_symbols)

    a = ap.parse_args()
    if not Path(a.file).is_file():
        print(f'[FAIL] 文件不存在: {a.file}')
        return 2
    try:
        return a.func(a)
    except FileNotFoundError as exc:
        print(f'[FAIL] {exc}')
        return 4
    except TimeoutError as exc:
        print(f'[FAIL] {exc}')
        return 3
    except Exception as exc:  # noqa: BLE001 - 单独跑一次，错误要原样看到
        print(f'[FAIL] {type(exc).__name__}: {exc}')
        return 1


if __name__ == '__main__':
    sys.exit(main())
