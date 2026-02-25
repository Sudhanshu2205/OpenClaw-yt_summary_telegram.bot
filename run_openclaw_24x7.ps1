$ErrorActionPreference = "Continue"

Set-Location "c:\Users\avish\Yt-Telegram_bot"

$logDir = "c:\Users\avish\Yt-Telegram_bot\data"
if (-not (Test-Path $logDir)) {
    New-Item -ItemType Directory -Path $logDir | Out-Null
}
$logFile = Join-Path $logDir "openclaw_gateway.log"

while ($true) {
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -Path $logFile -Value "[$ts] Starting openclaw gateway run"
    try {
        openclaw gateway run *>> $logFile
    } catch {
        $tsErr = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
        Add-Content -Path $logFile -Value "[$tsErr] Gateway crashed: $($_.Exception.Message)"
    }

    Start-Sleep -Seconds 5
}

