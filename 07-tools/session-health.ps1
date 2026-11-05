# DSH 会话体检（每日一次）
# 扫全部会话 JSONL 的结构：坏 JSON / 坏的 inbox.spliced 消息对象。
# 结果最后一段写到 E:\DS公作区\自进化\session-health-last.txt，
# 追加记录由 session_health.py --report 自己写进 ~/.dsh/session-health.log。
# 退出码：0 = 没坏会话；1 = 有坏会话（或扫描出错）。
#
# 2026-11-05 补建。前一晚只写了 session_health.py，包装脚本和计划任务漏做。

$ErrorActionPreference = 'Continue'
$root = 'E:\DS公作区'
$py = Join-Path $env:USERPROFILE '.local\bin\py.cmd'
$script = Join-Path $root 'tools\lab\session_health.py'
$out = Join-Path $root '自进化\session-health-last.txt'
$stamp = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'

if (-not (Test-Path $py)) {
    $res = "找不到 py.cmd: $py"
    $code = 98
} else {
    $res = & $py $script --report 2>&1 | Out-String
    $code = $LASTEXITCODE
}

$text = "[$stamp] exit=$code`r`n$res"
try {
    Set-Content -Path $out -Value $text -Encoding UTF8
} catch {
    Write-Output "[WARN] 写 $out 失败: $_"
}
Write-Output $text

if ($code -ne 0) { exit 1 }
exit 0
