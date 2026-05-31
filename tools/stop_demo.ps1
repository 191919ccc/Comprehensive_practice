param(
    [int[]]$Ports = @(2181, 2182, 9092, 8080, 5500),
    [string]$RuntimeDir = ""
)

$ErrorActionPreference = "Continue"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($RuntimeDir)) {
    $RuntimeDir = "E:\stockrt"
}
$processIds = New-Object System.Collections.Generic.HashSet[int]
$pidFile = Join-Path $RuntimeDir "demo_pids_active.txt"
$legacyPidFile = Join-Path $RuntimeDir "demo_pids.txt"

$pidFiles = @($pidFile, $legacyPidFile)
foreach ($file in $pidFiles) {
    if (Test-Path $file) {
        Get-Content $file | ForEach-Object {
            $parts = $_.Split(",")
            if ($parts.Length -eq 2 -and $parts[1] -match "^\d+$") {
                [void]$processIds.Add([int]$parts[1])
            }
        }
    }
}

foreach ($port in $Ports) {
    netstat -ano | Select-String ":$port\s+.*LISTENING" | ForEach-Object {
        $parts = ($_ -split "\s+") | Where-Object { $_ }
        $pidText = $parts[-1]
        if ($pidText -match "^\d+$") {
            [void]$processIds.Add([int]$pidText)
        }
    }
}

$demoCommandPatterns = @(
    "python\\spark\\stock_streaming_job\.py",
    "python\.spark\.stock_streaming_job",
    "python\.producer\.stock_producer",
    "python\.producer\.stock_replay_producer",
    "stock-risk-backend-0\.0\.1-SNAPSHOT\.jar",
    "http\.server.*--directory.*frontend"
)
$runtimePattern = [regex]::Escape($RuntimeDir)
Get-CimInstance Win32_Process | ForEach-Object {
    $commandLine = $_.CommandLine
    if ([string]::IsNullOrWhiteSpace($commandLine)) {
        return
    }
    $isDemoProcess = $false
    foreach ($pattern in $demoCommandPatterns) {
        if ($commandLine -match $pattern) {
            $isDemoProcess = $true
            break
        }
    }
    if (-not $isDemoProcess -and $commandLine -match $runtimePattern) {
        $isDemoProcess = $true
    }
    if ($isDemoProcess -and $_.ProcessId -gt 0) {
        [void]$processIds.Add([int]$_.ProcessId)
    }
}

foreach ($processId in $processIds) {
    if ($processId -le 0) {
        continue
    }
    $process = Get-Process -Id $processId -ErrorAction SilentlyContinue
    if ($null -eq $process) {
        continue
    }
    Stop-Process -Id $processId -Force
    "Stopped pid=$processId name=$($process.ProcessName)"
}

foreach ($file in $pidFiles) {
    if (Test-Path $file) {
        Remove-Item -Path $file -Force -ErrorAction SilentlyContinue
    }
}

"Known ports checked: $($Ports -join ', ')"
"Processes started by tools/start_demo.ps1 were read from: $pidFile"
