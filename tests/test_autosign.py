"""Wire test: AutoSigner -> subprocess browser_sign -> result callback."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from automonitor.autosign import AutoSigner  # noqa: E402

results = []
s = AutoSigner(notify=lambda reason, text: results.append((reason, text)), timeout_s=180)
s._pending.append("0000")  # 直接入队, 避免 submit 的后台线程竞态
s._run()  # 同步执行便于测试
assert results, "没有收到回调"
for r in results:
    print("回调:", r)
print("PASS" if any("0000" in t for _, t in results) else "FAIL")
