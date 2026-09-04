import numpy as np
from fastembed import TextEmbedding

m = TextEmbedding(model_name="BAAI/bge-small-zh-v1.5")
tpl = ["请大家现在开始签到", "打开签到二维码扫一下", "老师在点名了"]
cand = ["先签个到再认真听讲", "我们开始今天的签到", "我们开始今天的街道",
        "今天讲第三章线性代数", "把学号发到群里我看一下", "刚才说到上周的作业都交了吗",
        "没签到的同学抓紧时间", "一会下课我把这门课的评分标准说了一下"]

def norm(v):
    return v / (np.linalg.norm(v) + 1e-9)

T = np.array([norm(x) for x in m.embed(tpl)])
C = np.array([norm(x) for x in m.embed(cand)])
for c, v in zip(cand, C):
    print(f"max_sim={float((T @ v).max()):.3f}  {c}")
