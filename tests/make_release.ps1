$ErrorActionPreference = "Stop"
$cred = "url=https://github.com`n" | git credential fill | Select-String "^password="
$tok = $cred.ToString().Substring(9)
$H = @{ Authorization = "token $tok"; "User-Agent" = "EchoSign" }

# 1) 创建 release (tag v0.3.0 指向当前 master)
$body = @{
    tag_name         = "v0.3.0"
    target_commitish = "master"
    name             = "EchoSign v0.3.0 - GUI 版"
    body             = (@"
## EchoSign v0.3.0

直播课堂实时监控 + 全自动签到 (Windows x64)

### 下载
- EchoSign-v0.3.0-win64.zip (336MB, 解压后运行 EchoSign.exe)

### 功能
- 内录系统声音, 实时流式中文语音识别 (离线, 本地推理)
- 签到话术三级匹配 (强规则/正则 + 弱词组合 + 语义匹配)
- 自动提取老师口播的 4 位签到码
- 真浏览器全自动签到 (合法通过阿里验证码)
- 企业微信机器人实时推送提醒与结果
- 图形界面: 配置 / 启停 / 日志 / 登录态管理

### 使用
1. 解压后双击 EchoSign.exe
2. 填写学号/密码/企微 Webhook → 保存配置
3. 点击「登录/刷新登录态」
4. ▶ 启动监控, 挂机即可
"@)
} | ConvertTo-Json

$rel = Invoke-RestMethod -Method Post -Uri "https://api.github.com/repos/ys317/EchoSign/releases" -Headers $H -ContentType "application/json; charset=utf-8" -Body ([System.Text.Encoding]::UTF8.GetBytes($body))
Write-Output "release 创建: id=$($rel.id) url=$($rel.html_url)"

# 2) 上传 zip 资产
$zip = "EchoSign-v0.3.0-win64.zip"
$uploadUrl = "https://uploads.github.com/repos/ys317/EchoSign/releases/$($rel.id)/assets?name=$zip"
curl.exe -sS -X POST -H "Authorization: token $tok" -H "Content-Type: application/zip" --data-binary "@$zip" $uploadUrl -o upload_resp.json -w "upload http=%{http_code}\n"
$resp = Get-Content upload_resp.json -Raw | ConvertFrom-Json
Write-Output "asset: $($resp.name) state=$($resp.state) size=$([Math]::Round($resp.size / 1MB))MB"
Remove-Item upload_resp.json -ErrorAction SilentlyContinue
