"""届いたリクエストを記録する、偽の OpenAI 互換サーバー（B-2、B-3）。標準ライブラリだけで書く。

返事の決め方：
- 最後の「台本」のユーザーのメッセージ（`CALL {"name": …, "arguments": {…}}` の行を持つもの）を探す。
- そのメッセージより後に返したツールの呼び出しの数を k とし、台本の k+1 番目の呼び出しを返す。
- 台本を使い切ったとき、台本がないときは、`done` の1語を返す。
"""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MARK = "CALL "


def text_of(content):
    """メッセージの content（文字列か、部品のリスト）から、文字の部分をつないで返す。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(p.get("text", "") for p in content if isinstance(p, dict))
    return ""


def script_of(message):
    """メッセージの台本（呼び出しのリスト）を返す。台本でなければ空のリスト。"""
    calls = []
    for line in text_of(message.get("content")).splitlines():
        line = line.strip()
        if line.startswith(MARK):
            calls.append(json.loads(line[len(MARK):]))
    return calls


def next_reply(body):
    """リクエストの本文から、次に返すもの（呼び出しの辞書か、None）を決める。"""
    messages = body.get("messages", [])
    start = None
    for i in range(len(messages) - 1, -1, -1):
        if messages[i].get("role") == "user" and script_of(messages[i]):
            start = i
            break
    if start is None:
        return None
    calls = script_of(messages[start])
    k = sum(len(m.get("tool_calls") or []) for m in messages[start + 1:] if m.get("role") == "assistant")
    return calls[k] if k < len(calls) else None


class FakeServer:
    """with の間、127.0.0.1 の空いたポートで動く。requests に、届いたリクエストの本文を届いた順に持つ。"""

    def __init__(self):
        self.requests = []
        self._lock = threading.Lock()
        self._count = 0
        server = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _send(self, code, data, ctype="application/json"):
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                self._send(200, json.dumps({"object": "list", "data": []}).encode("utf-8"))

            def do_POST(self):
                size = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(size).decode("utf-8") or "{}")
                with server._lock:
                    server.requests.append(body)
                    server._count += 1
                    call_id = "call_%04d" % server._count
                call = next_reply(body)
                if call is None:
                    message = {"role": "assistant", "content": "done"}
                    finish = "stop"
                else:
                    message = {"role": "assistant", "content": None, "tool_calls": [{
                        "id": call_id, "type": "function",
                        "function": {"name": call["name"], "arguments": json.dumps(call["arguments"])}}]}
                    finish = "tool_calls"
                if body.get("stream"):
                    self._send(200, self._sse(message, finish), "text/event-stream")
                else:
                    self._send(200, json.dumps({
                        "id": "chatcmpl-" + call_id, "object": "chat.completion", "model": body.get("model", ""),
                        "choices": [{"index": 0, "message": message, "finish_reason": finish}],
                        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}).encode("utf-8"))

            def _sse(self, message, finish):
                delta = dict(message)
                if "tool_calls" in delta:
                    delta["tool_calls"] = [dict(c, index=0) for c in delta["tool_calls"]]
                chunks = [
                    {"choices": [{"index": 0, "delta": delta, "finish_reason": None}]},
                    {"choices": [{"index": 0, "delta": {}, "finish_reason": finish}],
                     "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}},
                ]
                text = "".join("data: %s\n\n" % json.dumps(dict(c, id="chatcmpl-x", object="chat.completion.chunk"))
                               for c in chunks)
                return (text + "data: [DONE]\n\n").encode("utf-8")

        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = "http://127.0.0.1:%d/v1" % self._httpd.server_address[1]

    def __enter__(self):
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._httpd.shutdown()
        self._httpd.server_close()
        return False
