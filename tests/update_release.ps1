$ErrorActionPreference = "Stop"
$cred = "url=https://github.com`n" | git credential fill | Select-String "^password="
$tok = $cred.ToString().Substring(9)
$H = @{ Authorization = "token $tok"; "User-Agent" = "EchoSign" }

$rel = Invoke-RestMethod -Uri "https://api.github.com/repos/ys317/EchoSign/releases/tags/v0.3.0" -Headers $H
$body = @{
    name = "EchoSign v0.3.0"
    body = (@"
直播课堂实时监控与自动签到工具 (Windows x64)

- 内录系统声音, 本地离线流式中文语音识别
- 签到话术规则与语义匹配
- 自动提取口播 4 位签到码
- 真实浏览器自动完成签到
- 企业微信机器人实时推送

解压后运行 EchoSign.exe, 填入学号/密码/企微 Webhook, 登录一次即可挂机。
"@)
} | ConvertTo-Json
Invoke-RestMethod -Method Patch -Uri "https://api.github.com/repos/ys317/EchoSign/releases/$($rel.id)" -Headers $H -ContentType "application/json; charset=utf-8" -Body ([System.Text.Encoding]::UTF8.GetBytes($body)) | Out-Null
Write-Output "release 已更新: $($rel.html_url)"
