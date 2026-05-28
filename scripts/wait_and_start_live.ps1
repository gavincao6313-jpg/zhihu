# wait_and_start_live.ps1 — 等待直播开始后启动转录
# 不传 --name，让 Python 自动从页面标题生成名称
param(
    [string]$URL,
    [string]$Provider = "qwen",
    [switch]$BestAB
)

$python = 'd:\zhihu\zhihu_file\.venv-sensevoice\Scripts\python.exe'
$script = 'd:\zhihu\zhihu_url\zhihuTTS_stream.py'
$auth = 'd:\zhihu\zhihu_url\zhihu_auth_state.json'
$workDir = 'd:\zhihu\zhihu_url\Videos\.stream'

# 使用临时 marker 路径，Python 会把自动生成的实际名称写进去
$tempName = "live-temp-$(Get-Date -Format 'HHmmss')"
$baseMarker = "d:\zhihu\zhihu_url\runs\stream-base-${tempName}.txt"
$authSave = "d:\zhihu\zhihu_url\zhihu_auth_state-${tempName}.save.json"
$logFile = "d:\zhihu\zhihu_url\logs\run-${tempName}.log"

$maxWaitMin = 180
$checkSec = 10

$env:SENSEVOICE_MERGE_VAD = 'true'
New-Item -ItemType Directory -Force -Path 'd:\zhihu\zhihu_url\logs' | Out-Null

$startTime = Get-Date
$deadline = $startTime.AddMinutes($maxWaitMin)

Write-Output "=== Wait for live stream ==="
Write-Output "URL: $URL"
Write-Output "Started: $($startTime.ToString('HH:mm:ss')) | Deadline: $($deadline.ToString('HH:mm:ss'))"

$attempt = 0
while ((Get-Date) -lt $deadline) {
    $attempt++
    $ts = (Get-Date).ToString('HH:mm:ss')
    Write-Output "[$ts] Attempt #$attempt ..."

    $proc = Start-Process -FilePath $python -ArgumentList @(
        '-u', $script,
        '--playwright-keepalive',
        '--continuous-hls',
        '--page-url', $URL,
        '--playwright-storage-state', $auth,
        '--playwright-save-storage-state', $authSave,
        '--duration', '0',
        '--chunk-duration', '60',
        '--stream-work-dir', $workDir,
        '--base-marker', $baseMarker,
        '--extractor-wait-s', '15'
    ) -RedirectStandardOutput $logFile -RedirectStandardError "$logFile.err" -PassThru -WindowStyle Minimized

    # Wait and check if process survived
    Start-Sleep -Seconds $checkSec
    $stillAlive = $null -ne (Get-Process -Id $proc.Id -ErrorAction SilentlyContinue)

    if ($stillAlive -and -not $proc.HasExited) {
        # Read auto-generated name from base marker
        $actualName = ''
        if (Test-Path $baseMarker) {
            $actualName = (Get-Content $baseMarker -Raw).Trim()
            # Rename marker and log to match actual name
            if ($actualName -and $actualName -ne $tempName) {
                $newMarker = "d:\zhihu\zhihu_url\runs\stream-base-${actualName}.txt"
                $newLog = "d:\zhihu\zhihu_url\logs\run-${actualName}.log"
                Move-Item $baseMarker $newMarker -Force -ErrorAction SilentlyContinue
                # log will be renamed after stream ends (still being written)
                Set-Content "d:\zhihu\zhihu_url\runs\stream-base-name.txt" -Value $actualName -Encoding UTF8
            }
        }
        Write-Output "SUCCESS! PID $($proc.Id), name: '$actualName'"
        Write-Output "Monitor: Get-Content -Wait -Tail 20 '$logFile'"
        exit 0
    }

    $sleep = if ($attempt -le 5) { 20 } elseif ($attempt -le 20) { 30 } else { 60 }
    Write-Output "  Exited (no stream yet), retry in ${sleep}s..."
    Start-Sleep -Seconds $sleep
}

Write-Output "TIMEOUT after ${maxWaitMin}min"
exit 1
