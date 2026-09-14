# 开发指南

Windows x64，Python 3.13。

## 本地运行

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m playwright install chromium
.\.venv\Scripts\pythonw.exe -m echosign
```

将发行包中的 `models/` 复制到项目根目录，即可使用本地识别模型。个人配置沿用根目录中的 `config.yaml` 等文件，不应提交到仓库。

图形界面与命令行共用 `python -m echosign` 入口：

```powershell
python -m echosign --help
python -m echosign devices
python -m echosign run --config config.yaml
python -m echosign test --help
python -m echosign code
```

`demo` 用于检查匹配规则，`--login` 打开登录浏览器。`test` 与 `run` 使用配置中的通知和签到选项；离线调试时应关闭 `auto_sign.enabled` 并清空 Webhook。

## 构建

```powershell
.\.venv\Scripts\python.exe -m pip install pyinstaller==6.22.2
.\.venv\Scripts\python.exe tools/release.py build
```

构建工具准备匹配的浏览器和语义模型，在 `build/releases/<版本>/` 生成独立目录，再打包到 `dist/releases/<版本>/`。语音模型从项目根目录的 `models/` 读取。首次准备缺失依赖时需要联网。

版本号统一维护在 `echosign/__init__.py`，Windows 版本资源由构建工具自动生成。发布前先定稿代码、文档和图片，再构建；工具会校验源码摘要，避免上传与代码不一致的包。

维护者提交代码并推送对应版本标签后，可运行 `python tools/release.py publish --notes <发布说明.md>`，将已构建的 ZIP 发布到 GitHub `origin` 仓库。

## 目录

| 目录 | 内容 |
| --- | --- |
| `echosign/` | 应用代码，按职责划分模块 |
| `tests/` | 自动化测试与音频样本 |
| `tools/` | `release.py` 构建与发布；`assets.py` 资源维护；`EchoSign.spec` 打包配置 |
| `assets/`、`docs/` | 图标、截图与文档 |

应用内部由 `audio.py` 负责采集和转写，`rules.py` 负责匹配与提码，`monitor.py` 连接识别流程；`attendance.py` 管理签到任务与结果，`browser.py` 负责网页操作。`gui.py` 管理界面状态，`ui.py` 集中维护主题和通用控件，`runtime.py` 处理源码与便携版的资源路径。

`location.py` 在用户点击按钮时，通过 Windows 自带 PowerShell 调用系统定位，返回经纬度及可用精度；不使用 IP 定位，也不反查街道地址。请求在工作线程运行，有 20 秒总超时，结果在主线程填入表单，失败保留原值。`processes.py` 统一后台命令的 Windows 无控制台启动参数；源码图形界面使用 `pythonw.exe` 启动，便携版以无控制台方式打包。

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

测试使用临时数据，不连接学校服务、发送通知或录制课堂声音。

## 回放评估

监码支持确认后的中间结果和完整结果两条路径。默认 `code_watch.early_code: true`、`early_stable_seconds: 0.4`：同一位置的四位码至少经过两次实际解码，持续不少于 0.4 秒音频，且有非数字后续话语或完整重复报码，才可提前提交。`StreamingASR.revision` 只在实际解码时增加，重复返回缓存文本不增加确认次数；空白或改写后的结果打断候选稳定期。裸四位尾串、拆开的长数字、小数、单位和截短的重复串不提前提交。`feed(final=False)` 仍无副作用，提前确认统一经过 `feed_partial`。

设置 `early_code: false` 可退回只提交完整结果。回放结束时需先排空识别器的剩余音频，停止监控则不提交剩余转写。中间结果只使用强规则预备页面，不运行语义模型，也不提前发送普通签到提示；已确认的码仍按码去重，整句结束不重复提交同一码。

默认 `auto_sign.prewarm_browser: true`，出现提示或候选码就调用 `AutoSigner.prepare()`，不传入码。每次监控复用一个独立浏览器进程，父子进程以原子写入的 `request-{id}.json`、`result-{id}.json` 交换确认请求和结果；每次使用新文件，避免 Windows 下覆盖正在读取的请求。每轮结束重新打开空白键盘。页面预备失败允许确认码后冷启动；已发请求结果未知时不自动重试；取消时终止正在处理请求的进程树。

网页操作等待元素可用，不使用进入键盘后或每位数字后的固定停顿。签到结果仍只接受匹配当前码、请求方法和签到接口的响应。`timing-{id}.json` 单独记录确认码、页面就绪、输入、点击和响应时间；活动记录显示确认码到页面就绪、点击签到的耗时。计时信息缺失或损坏不改变已确认的签到结果。

`tools/replay_metrics.py` 提供独立于模型和账号的评分函数。每段音频应单独标注是否存在点名过程、明确的四位参考码，以及确认属于普通授课的时间段。`true_codes` 支持同一片段多个参考码，兼容旧的 `true_code`。未列出的码默认待核实，只有显式标为 `invalid_codes`、出现在已标注普通授课时段，或标注明确声明 `code_labels_complete: true` 时才判错。缺少标注或参考转写不清楚时保留未知，不能归为负样本。

评估同时报告是否检出全部已标有码、检出且输出均已核实的片段数、已确认错码、待核实码、已判定报码事件的准确率及判定覆盖率，以及已标注普通授课时段的错误提示和覆盖时长。参考码按整段标注匹配；点名前后的时间窗口只表示时间接近程度，不能当作真假标签，也不能否定同一课堂的另一轮签到。调节热词或语义模板后，应在独立课堂的普通授课时段上验证误报，再决定默认配置。

识别速度应分别从老师说出签到提示、念完完整签到码计时。平台创建签到的时间、音频解码的总耗时和音频块大小都不能代替这两项延迟。可在标注中增加 `speech_events`：每项包含 `kind`（`prompt` 或 `code`）、音频内的 `start`、`end`、`match_until`，码事件还需提供 `code`。`end` 是待识别提示或完整码的结束时间；`match_until` 明确该次事件的匹配范围，避免把后面无关的提示计作成功。重复念同一个码属于同次检测时，只标注第一次完整报码。

评分中的 `speech_latencies` 和汇总的 `prompt_latency`、`code_latency` 单独列出已标注事件、检出、漏检和延迟；错误码与此前已输出的码不能充当本次正确码的检出时间。没有语音时间标注时延迟保持未知。自动语音分段只有句段边界，包含重复报码或后续说话时，应注明实际测量的是整段结束后的等待，不能据此声称逐词延迟；负值保留供检查边界误差。正式比较识别延迟应使用经过核对的提示结束、首次完整报码结束时间，并保留漏检样本。
