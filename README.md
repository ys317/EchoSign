# EchoSign

> 声过留痕，听到即签 —— 直播课堂实时监控 + 全自动签到

EchoSign 挂机监听直播/网课页面的声音，实时识别老师的话。一旦听到签到相关的话术，
立即通过企业微信提醒你，并自动提取老师口播的 4 位签到码，驱动真实浏览器自动完成签到。

## 完整链路

```
扬声器声音 → 内录(WASAPI环回) → 流式ASR(sherpa-onnx 中文 zipformer)
  → 三级匹配: 强规则/正则 + 弱词组合 + bge 语义匹配
  → 命中签到话术 → 企业微信推送提醒 + 开启监码窗口
  → 听到4位签到码(支持"幺二三四"中文数字归一)
  → AutoSigner 子进程拉起 Playwright 真浏览器
  → 课堂签到页自动填码提交(阿里验证码由真实页面合法生成)
  → 签到结果 → 企业微信推送
```

## 快速开始

```powershell
# 1. 环境 (Windows, Python 3.13)
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m playwright install chromium

# 2. 模型 (约 168MB, 已在 models/ 下则跳过)
#    sherpa-onnx-streaming-zipformer-zh-int8-2025-06-30
#    下载: https://hf-mirror.com/csukuangfj/sherpa-onnx-streaming-zipformer-zh-int8-2025-06-30

# 3. 配置
copy config.example.yaml config.yaml   # 填入企业微信机器人 key
#    编辑 secrets_local.json, 填入学号密码(用于 CAS 自动登录)

# 4. 一次性登录(保留 browser_profile/ 登录态, 过期自动重登)
.venv\Scripts\python.exe -X utf8 browser_login.py

# 5. 挂机
启动监控.bat        # 或: .venv\Scripts\python.exe -X utf8 main.py run
```

## 常用命令

| 命令 | 作用 |
|---|---|
| `main.py run` | 挂机监控 |
| `main.py devices` | 查看输出设备 |
| `main.py code` | 测签到码提取规则 |
| `main.py webhook-test` | 测企业微信推送 |
| `browser_sign.py 2330` | 手动触发自动签到 |
| `sign.py 2330` | 纯 requests 快速签到(备用) |

## 配置要点 (config.yaml)

- `rules.strong` / `weak_groups` / `semantic`: 签到话术规则, 支持正则(`re:` 前缀)
- `code_watch`: 监码窗口/独立短句报码
- `auto_sign.enabled`: 听到码自动签到
- `alert.webhook`: 企业微信机器人推送及级别

## 目录结构

```
automonitor/          核心包
  capture.py          WASAPI 环回采集(独立线程防断流)
  asr.py              流式 ASR 引擎封装
  matcher.py          三级关键词/语义匹配
  watcher.py          监码窗口 + 签到码提取
  autosign.py         自动签到调度
  alert.py            告警 + 企业微信推送
browser_login.py      CAS 登录(Playwright, 保留登录态)
browser_sign.py       真浏览器自动填码签到
sign.py               纯 requests 签到(备用)
main.py               入口
```

## 注意

- 仅用于个人课程的自动化辅助, 请遵守学校相关规定
- `secrets_local.json` / `session_local.json` / `config.yaml` / `browser_profile/`
  含个人凭证, 已被 .gitignore 排除, 不要提交或外传
