"""lab cdp —— 通过 Chrome DevTools Protocol 操作已经开着的浏览器。

为什么需要它（治 P3「有眼无手」）：我能看见网页（web_fetch 拿 HTML），却点不了。
2026-11-04 实测「点标签失败 5 次」，而 Edge 一直开着 remote debugging 端口，
连上去执行 JS 是通的——缺的只是把它包成一条命令。

边界（写死，不靠自觉）：
  * 只操作 --port 指定端口上 type=page 的标签，不碰 background_page / worker；
  * 不扫描浏览历史、不枚举非目标页面内容、不自动点击任何东西；
  * 有登录态的页面（平台后台、邮箱等）只在被明确要求的那一刻操作，
    eval 不读 cookie / localStorage / 表单值，除非命令里点名。
"""
import argparse
import base64
import json
import os
import socket
import struct
import sys
import time
import urllib.request
from pathlib import Path

DEFAULT_PORT = 9222


def http_json(port, path):
    with urllib.request.urlopen(f'http://127.0.0.1:{port}{path}', timeout=5) as r:
        return json.load(r)


class WS:
    """最小 WebSocket 客户端（纯标准库）：只够说 CDP 这一种协议。"""

    def __init__(self, url, timeout=15):
        if not url.startswith('ws://'):
            raise ValueError(f'只支持 ws://，拿到的是 {url!r}')
        rest = url[5:]
        hostport, _, path = rest.partition('/')
        host, _, port = hostport.partition(':')
        self.sock = socket.create_connection((host, int(port or 80)), timeout=timeout)
        key = base64.b64encode(os.urandom(16)).decode()
        req = (f'GET /{path} HTTP/1.1\r\nHost: {hostport}\r\n'
               f'Upgrade: websocket\r\nConnection: Upgrade\r\n'
               f'Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n')
        self.sock.sendall(req.encode())
        buf = b''
        while b'\r\n\r\n' not in buf:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise ConnectionError('握手时连接被关闭')
            buf += chunk
        head, _, self.buf = buf.partition(b'\r\n\r\n')
        if b'101' not in head.split(b'\r\n')[0]:
            raise ConnectionError(f'握手失败: {head[:300]!r}')
        self.next_id = 0

    def _read_exact(self, n):
        while len(self.buf) < n:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise ConnectionError('连接被关闭')
            self.buf += chunk
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def _mask(self, data, mask):
        return bytes(b ^ mask[i % 4] for i, b in enumerate(data))

    def _send_frame(self, first_byte, data):
        mask = os.urandom(4)
        n = len(data)
        hdr = bytearray([first_byte])
        if n < 126:
            hdr.append(0x80 | n)
        elif n < 65536:
            hdr.append(0x80 | 126)
            hdr += struct.pack('>H', n)
        else:
            hdr.append(0x80 | 127)
            hdr += struct.pack('>Q', n)
        hdr += mask
        self.sock.sendall(bytes(hdr) + self._mask(data, mask))

    def recv_text(self):
        chunks = []
        while True:
            raw = self._read_exact(2)
            b1, b2 = raw[0], raw[1]
            fin = b1 & 0x80
            opcode = b1 & 0x0f
            masked = b2 & 0x80
            n = b2 & 0x7f
            if n == 126:
                n = struct.unpack('>H', self._read_exact(2))[0]
            elif n == 127:
                n = struct.unpack('>Q', self._read_exact(8))[0]
            mask = self._read_exact(4) if masked else b''
            payload = self._read_exact(n)
            if masked:
                payload = self._mask(payload, mask)
            if opcode == 0x8:
                raise ConnectionError('服务端关闭')
            if opcode == 0x9:
                self._send_frame(0x8a, payload)
                continue
            if opcode == 0xA:
                continue
            if opcode in (0x1, 0x2, 0x0):
                chunks.append(payload)
                if fin:
                    return b''.join(chunks).decode('utf-8', 'replace')

    def call(self, method, params=None):
        self.next_id += 1
        mid = self.next_id
        self._send_frame(0x81, json.dumps({'id': mid, 'method': method,
                                           'params': params or {}}).encode())
        while True:
            try:
                msg = json.loads(self.recv_text())
            except ConnectionResetError:
                raise ConnectionError('连接被浏览器重置（标签可能已关闭）')
            if msg.get('id') == mid:
                if 'error' in msg:
                    raise RuntimeError(f'CDP {method} 失败: {msg["error"]}')
                return msg.get('result', {})


def list_pages(port):
    return [t for t in http_json(port, '/json/list') if t.get('type') == 'page']


def pick_page(port, index):
    pages = list_pages(port)
    if not pages:
        raise SystemExit('[FAIL] 端口上没有任何 page 标签（浏览器没开？或者没带 --remote-debugging-port）')
    if index < 0 or index >= len(pages):
        raise SystemExit(f'[FAIL] --tab {index} 越界，当前只有 {len(pages)} 个 page 标签')
    return pages[index]


def do_eval(ws, expr, await_promise=False):
    r = ws.call('Runtime.evaluate', {
        'expression': expr,
        'returnByValue': True,
        'awaitPromise': await_promise,
        'userGesture': True,
    })
    if 'exceptionDetails' in r:
        d = r['exceptionDetails']
        text = d.get('text', '')
        desc = (d.get('exception') or {}).get('description', '')
        raise SystemExit(f'[FAIL] JS 抛异常: {text} {desc}'.strip())
    return r.get('result', {}).get('value')


def cmd_tabs(a):
    pages = list_pages(a.port)
    if a.json:
        print(json.dumps(pages, ensure_ascii=False, indent=2))
        return 0
    if not pages:
        print(f'[FAIL] 127.0.0.1:{a.port} 上没有 page 标签')
        return 2
    for i, t in enumerate(pages):
        print(f'[{i}] {t.get("title", "")[:60]}')
        print(f'     {t.get("url", "")[:120]}')
    return 0


def cmd_eval(a):
    if a.file:
        expr = Path(a.file).read_text(encoding='utf-8')
    elif a.js is not None:
        expr = a.js
    else:
        expr = sys.stdin.read()
    if not expr.strip():
        print('[FAIL] 没有要执行的 JS')
        return 3
    page = pick_page(a.port, a.tab)
    ws = WS(page['webSocketDebuggerUrl'])
    try:
        val = do_eval(ws, expr, a.await_promise)
    finally:
        ws.sock.close()
    if a.json:
        print(json.dumps(val, ensure_ascii=False, indent=2))
    elif isinstance(val, (dict, list)):
        print(json.dumps(val, ensure_ascii=False, indent=2))
    else:
        print(val)
    return 0


def cmd_click(a):
    sel = json.dumps(a.selector)
    js = f"""(() => {{
      const el = document.querySelector({sel});
      if (!el) return {{ok: false, err: 'selector 没有匹配到元素'}};
      el.scrollIntoView({{block: 'center', inline: 'center'}});
      el.click();
      return {{ok: true, tag: el.tagName, text: (el.innerText || el.value || '').slice(0, 80)}};
    }})()"""
    page = pick_page(a.port, a.tab)
    ws = WS(page['webSocketDebuggerUrl'])
    try:
        res = do_eval(ws, js)
    finally:
        ws.sock.close()
    if not isinstance(res, dict) or not res.get('ok'):
        print(f'[FAIL] {res}')
        return 4
    print(f'[OK] 点击了 <{res.get("tag")}> {res.get("text", "")!r}')
    if a.wait_ms:
        time.sleep(a.wait_ms / 1000.0)
        print(f'     已等待 {a.wait_ms}ms')
    return 0


def cmd_goto(a):
    page = pick_page(a.port, a.tab)
    ws = WS(page['webSocketDebuggerUrl'])
    try:
        r = ws.call('Page.navigate', {'url': a.url})
        deadline = time.time() + a.wait
        while time.time() < deadline:
            time.sleep(0.3)
            try:
                state = do_eval(ws, 'document.readyState')
            except SystemExit:
                continue
            if state == 'complete':
                break
        title = do_eval(ws, 'document.title')
        href = do_eval(ws, 'location.href')
        print(f'[OK] {r.get("frameId", "")}')
        print(f'     标题: {title}')
        print(f'     地址: {href}')
        if r.get('errorText'):
            print(f'[WARN] {r["errorText"]}')
            return 5
    finally:
        ws.sock.close()
    return 0


def cmd_shot(a):
    page = pick_page(a.port, a.tab)
    ws = WS(page['webSocketDebuggerUrl'])
    try:
        r = ws.call('Page.captureScreenshot', {'format': 'png'})
        data = r.get('data')
    finally:
        ws.sock.close()
    if not data:
        print('[FAIL] 截图返回为空')
        return 6
    out = Path(a.path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(base64.b64decode(data))
    print(f'[OK] {out} ({out.stat().st_size:,} B)')
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(
        prog='lab cdp',
        description='通过 CDP 操作已经开着的浏览器（Edge/Chrome 需要带 --remote-debugging-port=9222）')
    p.add_argument('--port', type=int, default=DEFAULT_PORT)
    sub = p.add_subparsers(dest='cmd', required=True)

    t = sub.add_parser('tabs', help='列 page 标签')
    t.add_argument('--json', action='store_true')
    t.set_defaults(func=cmd_tabs)

    e = sub.add_parser('eval', help='在页面里执行 JS（不传 js 就读 stdin，--file 读文件）')
    e.add_argument('js', nargs='?')
    e.add_argument('--file')
    e.add_argument('--tab', type=int, default=0)
    e.add_argument('--await-promise', action='store_true')
    e.add_argument('--json', action='store_true')
    e.set_defaults(func=cmd_eval)

    c = sub.add_parser('click', help='点击 CSS 选择器匹配到的元素')
    c.add_argument('selector')
    c.add_argument('--tab', type=int, default=0)
    c.add_argument('--wait-ms', type=int, default=0)
    c.set_defaults(func=cmd_click)

    g = sub.add_parser('goto', help='导航到 URL 并等 readyState=complete')
    g.add_argument('url')
    g.add_argument('--tab', type=int, default=0)
    g.add_argument('--wait', type=float, default=15.0)
    g.set_defaults(func=cmd_goto)

    s = sub.add_parser('shot', help='页面截图存成 PNG')
    s.add_argument('path')
    s.add_argument('--tab', type=int, default=0)
    s.set_defaults(func=cmd_shot)

    a = p.parse_args(argv)
    try:
        return a.func(a)
    except (ConnectionError, urllib.error.URLError, TimeoutError) as exc:
        print(f'[FAIL] 连不上 CDP（127.0.0.1:{a.port}）: {exc}')
        print('       浏览器要用 --remote-debugging-port=9222 启动；Edge 默认不带这个参数。')
        return 2


if __name__ == '__main__':
    sys.exit(main())
