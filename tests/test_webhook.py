"""Verify WeChat Work webhook payload format against a local mock server."""
import json
import sys
import threading
import time
import pathlib
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from automonitor.alert import Alerter  # noqa: E402

received = []


class Mock(BaseHTTPRequestHandler):
    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"]))
        received.append(json.loads(body))
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"errcode":0,"errmsg":"ok"}')

    def log_message(self, *a):  # silence
        pass


srv = HTTPServer(("127.0.0.1", 18923), Mock)
threading.Thread(target=srv.serve_forever, daemon=True).start()

al = Alerter(log_file=str(pathlib.Path(__file__).parent / "wh_test.jsonl"),
             dedup_seconds=0, webhook_url="http://127.0.0.1:18923/hook?key=test",
             webhook_levels=("high", "code"))
al.notify("现在开始签到", "high", "强关键词:签到")
time.sleep(0.3)
al.notify("签到码是1234", "code", "签到码: 1234")
time.sleep(0.3)
al.notify("扫一下码", "medium", "弱词组合")  # not in levels -> no webhook
time.sleep(0.5)

assert len(received) == 2, f"期望2条, 实际{len(received)}"
for r in received:
    assert r["msgtype"] == "markdown"
    print("payload ok:", r["markdown"]["content"].replace("\n", " | ")[:80])
print("PASS")
