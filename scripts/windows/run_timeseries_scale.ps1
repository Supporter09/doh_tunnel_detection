[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$DatasetDir,

    [string]$OutputRoot = "artifacts/windows-scale",
    [string]$Python = ".venv\Scripts\python.exe",
    [ValidateSet("25", "50", "100", "250")]
    [string[]]$Stages = @("25", "50", "100", "250"),
    [switch]$IncludeFull
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$Runner = Join-Path $RepoRoot "experiments\kaggle\timeseries_clump_lstm\train_timeseries.py"

if (-not [System.IO.Path]::IsPathRooted($Python)) {
    $Python = Join-Path $RepoRoot $Python
}
if (-not [System.IO.Path]::IsPathRooted($OutputRoot)) {
    $OutputRoot = Join-Path $RepoRoot $OutputRoot
}
$DatasetDir = (Resolve-Path $DatasetDir).Path

if (-not (Test-Path $Python -PathType Leaf)) {
    throw "Python executable not found: $Python"
}
if (-not (Test-Path $Runner -PathType Leaf)) {
    throw "Time-series runner not found: $Runner"
}

& $Python -c "import torch; assert torch.cuda.is_available(), 'CUDA unavailable'; print('CUDA:', torch.version.cuda, '| GPU:', torch.cuda.get_device_name(0))"
if ($LASTEXITCODE -ne 0) {
    throw "CUDA PyTorch verification failed. Install a CUDA build from pytorch.org before training."
}

$StageDefinitions = @{
    "25"  = @{ FlowsPerCapture = 25;  FlowsPerClass = 500;  WindowsPerClass = 10000 }
    "50"  = @{ FlowsPerCapture = 50;  FlowsPerClass = 1000; WindowsPerClass = 20000 }
    "100" = @{ FlowsPerCapture = 100; FlowsPerClass = 2500; WindowsPerClass = 50000 }
    "250" = @{ FlowsPerCapture = 250; FlowsPerClass = 5000; WindowsPerClass = 100000 }
    "full" = @{ FlowsPerCapture = $null; FlowsPerClass = $null; WindowsPerClass = $null }
}

$RequestedStages = [System.Collections.Generic.List[string]]::new()
foreach ($Stage in $Stages) {
    if (-not $RequestedStages.Contains($Stage)) {
        $RequestedStages.Add($Stage)
    }
}
if ($IncludeFull) {
    $RequestedStages.Add("full")
}

$Tasks = @(
    @{ Name = "l1"; Windows = @(5, 7) },
    @{ Name = "l2"; Windows = @(9, 10) }
)

New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null
$ConfigRoot = Join-Path $OutputRoot "configs"
New-Item -ItemType Directory -Force -Path $ConfigRoot | Out-Null

foreach ($Stage in $RequestedStages) {
    $Limits = $StageDefinitions[$Stage]
    foreach ($Task in $Tasks) {
        $RunId = "stage-$Stage-$($Task.Name)"
        $RunOutput = Join-Path $OutputRoot $RunId
        $Manifest = Join-Path $RunOutput "experiment_manifest.json"
        $Latency = Join-Path $RunOutput "latency_benchmarks.json"

        if ((Test-Path $Manifest) -and (Test-Path $Latency)) {
            try {
                $Existing = Get-Content $Manifest -Raw | ConvertFrom-Json
                if ($Existing.status -eq "training_completed") {
                    Write-Host "[SKIP] $RunId already completed."
                    continue
                }
            }
            catch {
                Write-Warning "Existing manifest for $RunId is unreadable; rerunning this unit."
            }
        }

        $Config = [ordered]@{
            mode = "train"
            dataset_dir = $DatasetDir
            dataset_slug = "local-cicdohbrw2020-raw-pcaps"
            dataset_version = "windows-external-disk"
            task = $Task.Name
            split_protocol = "session_scenario_disjoint"
            window_sizes = $Task.Windows
            models = @("paper_v4", "improved_bidi_gru")
            seed = 42
            max_capture_members = 20000
            max_flows_per_class = $Limits.FlowsPerClass
            max_flows_per_capture = $Limits.FlowsPerCapture
            max_raw_packets = 1000000
            max_raw_bytes = 1073741824
            max_capture_packets = 200000
            max_capture_bytes = 536870912
            max_flow_packets = 10000
            max_flow_bytes = 52428800
            max_windows_per_flow = 1000
            max_windows_per_class = $Limits.WindowsPerClass
            max_standalone_capture_bytes = 21474836480
            max_member_bytes = 10737418240
            max_nested_archive_bytes = 26843545600
            max_total_uncompressed_bytes = 214748364800
            max_compression_ratio = 100.0
            target_false_positive_rate = 0.001
            epochs = 15
            batch_size = 64
            learning_rate = 0.001
            patience = 5
            enable_score_calibration = $true
            enable_latency_benchmark = $true
            latency_warmup_iterations = 50
            latency_max_samples = 1000
            description = "Windows RTX 2060-class staged run $RunId; session/scenario-disjoint evaluation."
        }

        $ConfigPath = Join-Path $ConfigRoot "$RunId.json"
        [System.IO.File]::WriteAllText(
            $ConfigPath,
            ($Config | ConvertTo-Json -Depth 5),
            [System.Text.UTF8Encoding]::new($false)
        )
        New-Item -ItemType Directory -Force -Path $RunOutput | Out-Null
        $LogPath = Join-Path $RunOutput "console.log"

        Write-Host "[RUN] $RunId"
        Write-Host "      config: $ConfigPath"
        Write-Host "      output: $RunOutput"
        & $Python $Runner --config $ConfigPath --output-dir $RunOutput 2>&1 | Tee-Object -FilePath $LogPath
        $ExitCode = $LASTEXITCODE
        if ($ExitCode -ne 0) {
            throw "$RunId failed with exit code $ExitCode. Fix the cause, then rerun; completed units will be skipped."
        }

        $Completed = Get-Content $Manifest -Raw | ConvertFrom-Json
        if ($Completed.status -ne "training_completed" -or -not (Test-Path $Latency)) {
            throw "$RunId returned success without complete manifest and latency evidence."
        }
        Write-Host "[DONE] $RunId"
    }
}

Write-Host "All requested stage/task units completed. Results: $OutputRoot"
