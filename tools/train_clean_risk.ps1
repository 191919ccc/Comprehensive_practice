param(
    [string]$PythonExe = "D:\anaconda3\envs\MachineLearn\python.exe",
    [string]$VersionLabel = "clean-risk",
    [int]$PredictionHorizon = 5,
    [string]$HorizonExperiments = "1,3,5",
    [int]$MaxTrainRows = 120000,
    [int]$LstmEpochs = 60,
    [int]$LstmMaxSequences = 80000,
    [switch]$SkipCheck,
    [switch]$AllowQualityGateFail
)

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $repoRoot

if (-not (Test-Path $PythonExe)) {
    throw "Python executable not found: $PythonExe"
}

function Set-TrainingEnv {
    param(
        [int]$Rows,
        [int]$Epochs,
        [int]$Sequences
    )
    $env:ML_MAX_TRAIN_ROWS = [string]$Rows
    $env:ML_LSTM_EPOCHS = [string]$Epochs
    $env:ML_LSTM_MAX_SEQUENCES = [string]$Sequences
    $env:ML_LSTM_AUX_MAX_WEIGHT = "0.10"
    $env:ML_LIGHTGBM_MIN_WEIGHT = "0.85"
}

Write-Host "[train-clean-risk] repo=$repoRoot"
Write-Host "[train-clean-risk] python=$PythonExe"

if (-not $SkipCheck) {
    Write-Host "[train-clean-risk] running lightweight no-write quality check..."
    Set-TrainingEnv -Rows 15000 -Epochs 5 -Sequences 30000
    & $PythonExe -m python.ml.train_daily_predict `
        --version-label "$VersionLabel-check" `
        --models lightgbm,lstm `
        --prediction-horizon $PredictionHorizon `
        --horizon-experiments $HorizonExperiments `
        --no-write
    if ($LASTEXITCODE -ne 0) {
        throw "lightweight no-write training check failed with exit code $LASTEXITCODE"
    }
}

Write-Host "[train-clean-risk] running formal training..."
Set-TrainingEnv -Rows $MaxTrainRows -Epochs $LstmEpochs -Sequences $LstmMaxSequences
$trainArgs = @(
    "-m", "python.ml.train_daily_predict",
    "--version-label", $VersionLabel,
    "--models", "lightgbm,lstm",
    "--prediction-horizon", [string]$PredictionHorizon,
    "--horizon-experiments", $HorizonExperiments
)
if ($AllowQualityGateFail) {
    $trainArgs += "--allow-quality-gate-fail"
}
& $PythonExe @trainArgs
if ($LASTEXITCODE -ne 0) {
    throw "formal training failed with exit code $LASTEXITCODE"
}

Write-Host "[train-clean-risk] verifying latest formal training quality..."
& $PythonExe -m python.ml.verify_training_quality --version-prefix $VersionLabel
if ($LASTEXITCODE -ne 0) {
    throw "formal training quality verification failed with exit code $LASTEXITCODE"
}

Write-Host "[train-clean-risk] done: formal clean-risk model passed quality verification."
