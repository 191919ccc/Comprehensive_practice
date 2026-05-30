param(
    [string]$BackendUrl = "http://127.0.0.1:8080"
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$runtimeDir = Join-Path $ProjectRoot ".runtime"
$hadoopLogDir = Join-Path $runtimeDir "hadoop-logs"
New-Item -ItemType Directory -Force -Path $hadoopLogDir | Out-Null

"Ports:"
netstat -ano | Select-String ':2181|:2182|:9000|:9870|:9092|:8080|:5500'

""
"HDFS:"
$env:HADOOP_HOME = "E:\hadoop\hadoop-3.2.0"
$env:HADOOP_CONF_DIR = "E:\hadoop\hadoop-3.2.0\etc\hadoop"
$env:HADOOP_LOG_DIR = $hadoopLogDir
& "$env:HADOOP_HOME\bin\hdfs.cmd" dfs -ls /user/fqy

""
"Backend health:"
try {
    $health = Invoke-RestMethod -Uri "$BackendUrl/api/health" -Method Get
    $health | ConvertTo-Json -Depth 8
} catch {
    "Backend is not ready: $($_.Exception.Message)"
}

""
"Dashboard stream:"
try {
    $dashboard = Invoke-RestMethod -Uri "$BackendUrl/api/dashboard" -Method Get
    $dashboard.stream_status | ConvertTo-Json -Depth 5
} catch {
    "Dashboard API is not ready: $($_.Exception.Message)"
}
