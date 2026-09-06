# 开发指南

Windows x64，Python 3.13。

## 本地运行

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m playwright install chromium
.\.venv\Scripts\python.exe -m echosign
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

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

测试使用临时数据，不连接学校服务、发送通知或录制课堂声音。
