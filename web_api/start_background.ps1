param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("api", "frontend")]
    [string] $Service,

    [Parameter(Mandatory = $true)]
    [string] $ProjectDir,

    [string] $PythonExe = "python",

    [string] $LaunchMode = "live",

    [Parameter(Mandatory = $true)]
    [string] $LogDir
)

$ErrorActionPreference = "Stop"

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

if ($Service -eq "api") {
    $logPath = Join-Path $LogDir "api-watchdog.log"
    $workDir = $ProjectDir
    $command = 'set "PYTHON_EXE={0}"&& set "LAUNCH_MODE={1}"&& set "PROJECT_DIR={2}"&& call web_api\api_watchdog.bat >> "{3}" 2>&1' -f $PythonExe, $LaunchMode, $ProjectDir, $logPath
} else {
    $logPath = Join-Path $LogDir "frontend-vite.log"
    $workDir = Join-Path $ProjectDir "frontend"
    $nodeModules = Join-Path $workDir "node_modules"

    if (Test-Path $nodeModules) {
        $command = 'set "VITE_HOST=0.0.0.0"&& npx vite --host 0.0.0.0 >> "{0}" 2>&1' -f $logPath
    } else {
        $command = 'npm install >> "{0}" 2>&1 && set "VITE_HOST=0.0.0.0"&& npx vite --host 0.0.0.0 >> "{0}" 2>&1' -f $logPath
    }
}

$stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
Add-Content -Path $logPath -Value ""
Add-Content -Path $logPath -Value "===== $stamp starting $Service ====="

$process = Start-Process `
    -FilePath $env:ComSpec `
    -ArgumentList @("/d", "/s", "/c", $command) `
    -WorkingDirectory $workDir `
    -WindowStyle Hidden `
    -PassThru

Write-Host ("[{0}] started hidden PID={1}; log={2}" -f $Service, $process.Id, $logPath)
