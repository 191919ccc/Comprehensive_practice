param(
    [string]$ProjectRoot = "",
    [string]$KafkaHome = "E:\software\kafka_2.13-3.7.1",
    [string]$SparkHome = "E:\software\spark-3.5.2-bin-hadoop3",
    [string]$HadoopHome = "E:\hadoop\hadoop-3.2.0",
    [string]$PythonExe = "D:\anaconda3\envs\MachineLearn\python.exe",
    [int]$ZooKeeperPort = 2181,
    [int]$KafkaPort = 9092,
    [int]$HdfsPort = 9000,
    [int]$DataNodePort = 9866,
    [int]$BackendPort = 8080,
    [int]$FrontendPort = 5500,
    [switch]$UseRealCrawler
)

$ErrorActionPreference = "Continue"
$pathValue = [System.Environment]::GetEnvironmentVariable("Path", "Process")
if ([string]::IsNullOrWhiteSpace($pathValue)) {
    $pathValue = [System.Environment]::GetEnvironmentVariable("PATH", "Process")
}
[System.Environment]::SetEnvironmentVariable("PATH", $null, "Process")
if (-not [string]::IsNullOrWhiteSpace($pathValue)) {
    [System.Environment]::SetEnvironmentVariable("Path", $pathValue, "Process")
}

if ([string]::IsNullOrWhiteSpace($env:DEEPSEEK_API_KEY)) {
    $userDeepSeekKey = [System.Environment]::GetEnvironmentVariable("DEEPSEEK_API_KEY", "User")
    if (-not [string]::IsNullOrWhiteSpace($userDeepSeekKey)) {
        $env:DEEPSEEK_API_KEY = $userDeepSeekKey
    }
}

if ([string]::IsNullOrWhiteSpace($env:SERPER_API_KEY)) {
    $userSerperKey = [System.Environment]::GetEnvironmentVariable("SERPER_API_KEY", "User")
    if (-not [string]::IsNullOrWhiteSpace($userSerperKey)) {
        $env:SERPER_API_KEY = $userSerperKey
    }
}

if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = Split-Path -Parent $PSScriptRoot
}

$runtimeDir = "E:\stockrt"
New-Item -ItemType Directory -Force -Path $runtimeDir | Out-Null
$kafkaAppLogDir = Join-Path $runtimeDir "kafka-app-logs"
$ivyCacheDir = Join-Path $runtimeDir "ivy2"
$sparkLocalDir = Join-Path $runtimeDir "spark-local"
$tempDir = Join-Path $runtimeDir "tmp"
New-Item -ItemType Directory -Force -Path $kafkaAppLogDir | Out-Null
New-Item -ItemType Directory -Force -Path $ivyCacheDir | Out-Null
New-Item -ItemType Directory -Force -Path $sparkLocalDir | Out-Null
New-Item -ItemType Directory -Force -Path $tempDir | Out-Null
$env:LOG_DIR = $kafkaAppLogDir
$env:KAFKA_LOG4J_OPTS = "-Dkafka.logs.dir=$($kafkaAppLogDir.Replace('\', '/'))"
$env:SPARK_SUBMIT_OPTS = "-Divy.home=$($ivyCacheDir.Replace('\', '/')) -Divy.cache.dir=$($ivyCacheDir.Replace('\', '/'))"
$env:SPARK_LOCAL_DIRS = $sparkLocalDir
$env:SPARK_LOCAL_IP = "127.0.0.1"
$env:SPARK_LOCAL_HOSTNAME = "localhost"
$env:TEMP = $tempDir
$env:TMP = $tempDir
$hadoopLogDir = Join-Path $ProjectRoot ".runtime\hadoop-logs"
New-Item -ItemType Directory -Force -Path $hadoopLogDir | Out-Null
$pidFile = Join-Path $runtimeDir "demo_pids_active.txt"
Set-Content -Path $pidFile -Value "" -Encoding UTF8
$runId = Get-Date -Format "yyyyMMddHHmmss"
$zookeeperRuntimeConfig = Join-Path $runtimeDir "zookeeper-demo.properties"
$zookeeperRuntimeData = (Join-Path $runtimeDir "zookeeper-demo-$runId").Replace("\", "/")
$kafkaRuntimeConfig = Join-Path $runtimeDir "server-demo.properties"
$kafkaRuntimeLogs = (Join-Path $runtimeDir "kafka-logs-demo-$runId").Replace("\", "/")
New-Item -ItemType Directory -Force -Path $zookeeperRuntimeData | Out-Null
New-Item -ItemType Directory -Force -Path $kafkaRuntimeLogs | Out-Null

(Get-Content "$KafkaHome\config\zookeeper.properties") |
    ForEach-Object {
        if ($_ -match "^dataDir=") {
            "dataDir=$zookeeperRuntimeData"
        } elseif ($_ -match "^clientPort=") {
            "clientPort=$ZooKeeperPort"
        } else {
            $_
        }
    } |
    Set-Content -Path $zookeeperRuntimeConfig -Encoding UTF8

$kafkaConfigLines = New-Object System.Collections.Generic.List[string]
$wroteKafkaListeners = $false
$wroteKafkaAdvertisedListeners = $false
$wroteKafkaLogDirs = $false
$wroteKafkaZookeeper = $false
$wroteKafkaZookeeperTimeout = $false
Get-Content "$KafkaHome\config\server.properties" | ForEach-Object {
    if ($_ -match "^\s*#?\s*listeners=") {
        if (-not $wroteKafkaListeners) {
            $kafkaConfigLines.Add("listeners=PLAINTEXT://127.0.0.1:$KafkaPort")
            $wroteKafkaListeners = $true
        }
    } elseif ($_ -match "^\s*#?\s*advertised\.listeners=") {
        if (-not $wroteKafkaAdvertisedListeners) {
            $kafkaConfigLines.Add("advertised.listeners=PLAINTEXT://127.0.0.1:$KafkaPort")
            $wroteKafkaAdvertisedListeners = $true
        }
    } elseif ($_ -match "^log\.dirs=") {
        $kafkaConfigLines.Add("log.dirs=$kafkaRuntimeLogs")
        $wroteKafkaLogDirs = $true
    } elseif ($_ -match "^zookeeper\.connect=") {
        $kafkaConfigLines.Add("zookeeper.connect=127.0.0.1:$ZooKeeperPort")
        $wroteKafkaZookeeper = $true
    } elseif ($_ -match "^zookeeper\.connection\.timeout\.ms=") {
        $kafkaConfigLines.Add("zookeeper.connection.timeout.ms=30000")
        $wroteKafkaZookeeperTimeout = $true
    } else {
        $kafkaConfigLines.Add($_)
    }
}
if (-not $wroteKafkaListeners) {
    $kafkaConfigLines.Add("listeners=PLAINTEXT://127.0.0.1:$KafkaPort")
}
if (-not $wroteKafkaAdvertisedListeners) {
    $kafkaConfigLines.Add("advertised.listeners=PLAINTEXT://127.0.0.1:$KafkaPort")
}
if (-not $wroteKafkaLogDirs) {
    $kafkaConfigLines.Add("log.dirs=$kafkaRuntimeLogs")
}
if (-not $wroteKafkaZookeeper) {
    $kafkaConfigLines.Add("zookeeper.connect=127.0.0.1:$ZooKeeperPort")
}
if (-not $wroteKafkaZookeeperTimeout) {
    $kafkaConfigLines.Add("zookeeper.connection.timeout.ms=30000")
}
$kafkaConfigLines | Set-Content -Path $kafkaRuntimeConfig -Encoding UTF8

function Test-PortListening([int]$Port) {
    $line = netstat -ano | Select-String ":$Port\s+.*LISTENING"
    return $null -ne $line
}

function Get-ListeningPid([int]$Port) {
    $line = netstat -ano | Select-String ":$Port\s+.*LISTENING" | Select-Object -First 1
    if ($null -eq $line) {
        return $null
    }
    $parts = ($line.Line -split "\s+") | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
    if ($parts.Count -lt 5) {
        return $null
    }
    $pidValue = 0
    if ([int]::TryParse($parts[-1], [ref]$pidValue)) {
        return $pidValue
    }
    return $null
}

function Stop-ListeningProcess([int]$Port, [string]$Name) {
    $pidValue = Get-ListeningPid $Port
    if ($null -eq $pidValue) {
        return
    }
    try {
        $process = Get-Process -Id $pidValue -ErrorAction Stop
        Write-Host "[info] Stop existing $Name on port $Port pid=$pidValue before restart"
        Stop-Process -Id $pidValue -Force -ErrorAction Stop
        Start-Sleep -Seconds 2
    } catch {
        Write-Host "[warn] Failed to stop existing $Name pid=$pidValue on port ${Port}: $_"
    }
}

function Wait-KafkaReady([string]$KafkaHome, [int]$Port, [int]$MaxWait = 45) {
    $elapsed = 0
    while ($elapsed -lt $MaxWait) {
        & "$KafkaHome\bin\windows\kafka-broker-api-versions.bat" --bootstrap-server "127.0.0.1:$Port" *> $null
        if ($LASTEXITCODE -eq 0) {
            Write-Host "[ok] Kafka ready on 127.0.0.1:$Port"
            return $true
        }
        Start-Sleep -Seconds 2
        $elapsed += 2
    }
    Write-Host "[warn] Kafka not ready after $MaxWait seconds on 127.0.0.1:$Port"
    return $false
}

function Start-HiddenProcess([string]$Name, [string]$FilePath, [string[]]$Arguments, [string]$WorkingDirectory) {
    $stdout = Join-Path $runtimeDir "$Name.stdout.log"
    $stderr = Join-Path $runtimeDir "$Name.stderr.log"
    $startArgs = @{
        FilePath = $FilePath
        WorkingDirectory = $WorkingDirectory
        WindowStyle = "Hidden"
        RedirectStandardOutput = $stdout
        RedirectStandardError = $stderr
        PassThru = $true
    }
    if ($null -ne $Arguments -and $Arguments.Count -gt 0) {
        $startArgs.ArgumentList = $Arguments
    }
    $process = Start-Process @startArgs
    Add-Content -Path $pidFile -Value "$Name,$($process.Id)" -Encoding UTF8
    "$Name pid=$($process.Id)"
}

Set-Location $ProjectRoot

$env:HADOOP_HOME = $HadoopHome
$env:HADOOP_CONF_DIR = "$HadoopHome\etc\hadoop"
$env:HADOOP_LOG_DIR = $hadoopLogDir

if (-not (Test-PortListening $HdfsPort)) {
    Start-HiddenProcess "hdfs" "$HadoopHome\sbin\start-dfs.cmd" @() $HadoopHome
    Start-Sleep -Seconds 15
}

if (-not (Test-PortListening $DataNodePort)) {
    Start-HiddenProcess "hdfs-datanode" "$HadoopHome\bin\hdfs.cmd" @("datanode") $HadoopHome
    Start-Sleep -Seconds 12
}

try {
    & "$HadoopHome\bin\hdfs.cmd" dfsadmin -safemode leave | Out-Host
    if ($LASTEXITCODE -ne 0) {
        "[warn] safemode leave returned exit code $LASTEXITCODE, continuing"
    }
} catch {
    "[warn] safemode leave failed, continuing: $_"
}
try {
    & "$HadoopHome\bin\hdfs.cmd" dfs -mkdir -p /user/fqy/stock_output /user/fqy/stock_checkpoint | Out-Host
    if ($LASTEXITCODE -ne 0) {
        "[warn] HDFS mkdir returned exit code $LASTEXITCODE, continuing"
    }
} catch {
    "[warn] HDFS mkdir failed, continuing: $_"
}

if (-not (Test-PortListening $ZooKeeperPort)) {
    Start-HiddenProcess "zookeeper" "$KafkaHome\bin\windows\zookeeper-server-start.bat" @($zookeeperRuntimeConfig) $KafkaHome
    Start-Sleep -Seconds 15
}

if (-not (Test-PortListening $KafkaPort)) {
    Start-HiddenProcess "kafka" "$KafkaHome\bin\windows\kafka-server-start.bat" @($kafkaRuntimeConfig) $KafkaHome
    Start-Sleep -Seconds 12
}

$kafkaReady = Wait-KafkaReady $KafkaHome $KafkaPort
try {
    & "$KafkaHome\bin\windows\kafka-topics.bat" --bootstrap-server "127.0.0.1:$KafkaPort" --create --if-not-exists --topic stock_realtime_topic --partitions 1 --replication-factor 1 | Out-Host
    if ($LASTEXITCODE -ne 0) {
        "[warn] kafka-topics returned exit code $LASTEXITCODE, continuing"
    }
} catch {
    "[warn] kafka topic creation failed, continuing: $_"
}
$kafkaReady = Wait-KafkaReady $KafkaHome $KafkaPort

$localSparkJars = Get-ChildItem -Path (Join-Path $ivyCacheDir "jars") -Filter "*.jar" -ErrorAction SilentlyContinue
if ($localSparkJars -and $localSparkJars.Count -gt 0) {
    $sparkArgs = @(
        "--master",
        "local[2]",
        "--conf",
        "spark.local.dir=$($sparkLocalDir.Replace('\', '/'))",
        "--conf",
        "spark.driver.host=127.0.0.1",
        "--conf",
        "spark.driver.bindAddress=127.0.0.1",
        "--jars",
        (($localSparkJars | ForEach-Object { "file:///" + $_.FullName.Replace("\", "/") }) -join ","),
        "python\spark\stock_streaming_job.py"
    )
} else {
    $sparkArgs = @(
        "--master",
        "local[2]",
        "--packages",
        "org.apache.spark:spark-sql-kafka-0-10_2.12:3.5.2,mysql:mysql-connector-java:8.0.33",
        "--conf",
        "spark.jars.ivy=$($ivyCacheDir.Replace('\', '/'))",
        "--conf",
        "spark.local.dir=$($sparkLocalDir.Replace('\', '/'))",
        "--conf",
        "spark.driver.host=127.0.0.1",
        "--conf",
        "spark.driver.bindAddress=127.0.0.1",
        "python\spark\stock_streaming_job.py"
    )
}
$env:HDFS_OUTPUT_PATH = "hdfs://localhost:9000/user/fqy/stock_output"
$env:HDFS_CHECKPOINT_PATH = "hdfs://localhost:9000/user/fqy/stock_checkpoint/run-$runId"
if ($kafkaReady) {
    Start-HiddenProcess "spark-streaming" "$SparkHome\bin\spark-submit.cmd" $sparkArgs $ProjectRoot
} else {
    "[warn] Skip spark-streaming because Kafka did not become ready; check Kafka logs under $runtimeDir"
}

Push-Location "$ProjectRoot\java-backend"
try {
    Stop-ListeningProcess $BackendPort "backend"
    & mvn.cmd -q -DskipTests package
} finally {
    Pop-Location
}

$backendJar = Join-Path $ProjectRoot "java-backend\target\stock-risk-backend-0.0.1-SNAPSHOT.jar"
if (-not (Test-Path -LiteralPath $backendJar)) {
    throw "Backend jar not found after package: $backendJar"
}
$backendJarInfo = Get-Item -LiteralPath $backendJar
if ($backendJarInfo.Length -lt 1MB) {
    throw "Backend jar is unexpectedly small, refusing to start possibly wrong artifact: $backendJar ($($backendJarInfo.Length) bytes)"
}

if (-not (Test-PortListening $BackendPort)) {
    Start-HiddenProcess "backend" "java" @("-jar", $backendJar) "$ProjectRoot\java-backend"
}

if (-not (Test-PortListening $FrontendPort)) {
    Start-HiddenProcess "frontend" $PythonExe @("-m", "http.server", "$FrontendPort", "--directory", "$ProjectRoot\frontend") $ProjectRoot
}

if ($UseRealCrawler) {
    Start-HiddenProcess "stock-producer" $PythonExe @("-m", "python.producer.stock_producer") $ProjectRoot
} else {
    Start-HiddenProcess "stock-replay" $PythonExe @("-m", "python.producer.stock_replay_producer", "--interval", "3", "--volatility", "1.2") $ProjectRoot
}

"Demo started. Frontend: http://127.0.0.1:$FrontendPort/index.html"
"Logs: $runtimeDir"
