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

命令行入口为 `python -m echosign.cli`，支持 `devices`、`run`、`code`、`demo` 等子命令。

## 构建

```powershell
.\.venv\Scripts\python.exe -m pip install pyinstaller==6.22.2
.\.venv\Scripts\python.exe tools/build_release.py
```

构建工具准备匹配的浏览器和语义模型，生成独立目录，再打包到 `dist/releases/`。语音模型从项目根目录的 `models/` 读取。首次准备缺失依赖时需要联网。

维护者提交代码并推送对应版本标签后，可运行 `python tools/publish_release.py --notes <发布说明.md>`，将已构建的 ZIP 发布到 GitHub `origin` 仓库。

## 目录

| 目录 | 内容 |
| --- | --- |
| `echosign/` | 界面、声音识别、规则及浏览器功能 |
| `tests/` | 自动化测试与音频样本 |
| `tools/` | 构建与维护工具 |
| `packaging/` | Windows 打包配置与版本资源 |
| `assets/`、`docs/` | 图标、截图与文档 |

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

测试使用临时数据，不连接学校服务、发送通知或录制课堂声音。
