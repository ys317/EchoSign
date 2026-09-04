import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import yaml  # noqa: E402

from automonitor.matcher import build_matchers  # noqa: E402
from automonitor.watcher import SignInWatcher  # noqa: E402

cfg = yaml.safe_load(open(pathlib.Path(__file__).parents[1] / "config.yaml", encoding="utf-8"))
matchers = build_matchers(cfg)

cases = [
    ("那我们先呃先点个到啊先点个到然后因为大家来都来了嘛是吧领到然后我们开始做作业了二十分钟做作业", "high"),
    ("二三三零", None),
    ("我们三点到五点再开始写作业", None),          # 时间表述不能误报
    ("从两点到四点都是自习课", None),
    ("现在开始点名了啊", "high"),
    ("今天我们讲第二章第三节", None),
]
ok = True
for text, want in cases:
    hits = [h for m in matchers if (h := m.match(text))]
    got = hits[0][0] if hits else None
    mark = "OK " if got == want else "FAIL"
    if got != want:
        ok = False
    print(f"{mark} want={want} got={got}  {text[:28]}")
    if hits:
        print(f"     -> {hits[0][1]}")

w = SignInWatcher(standalone_code=True, log_file=str(pathlib.Path(__file__).parent / "w_test.jsonl"))
r1 = w.feed("二三三零", final=True)      # 未触发, 独立短句 -> 应报
r2 = w.feed("今天我们讲第二章第三节的内容然后二十分钟做作业", final=True)  # 长句 -> 不报
w.trigger("好的同学们现在开始签到", "强关键词:签到")
r3 = w.feed("好的现在开始签到签到码四五六七", final=True)  # 触发后同句带码
r4 = w.feed("五六七八", final=True)       # 触发后窗口内的码
print(f"{'OK ' if r1 and r1[0][0] == '2330' else 'FAIL'} 独立短句报码: {r1}")
print(f"{'OK ' if not r2 else 'FAIL'} 长句不报: {r2}")
print(f"{'OK ' if r3 and r3[0][0] == '4567' else 'FAIL'} 触发句带码: {r3}")
print(f"{'OK ' if r4 and r4[0][0] == '5678' else 'FAIL'} 窗口内报码: {r4}")
print("PASS" if ok and r1 and not r2 and r3 and r4 else "FAIL")
