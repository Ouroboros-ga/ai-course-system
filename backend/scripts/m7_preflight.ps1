param(
    [switch]$SkipTests,
    [switch]$SkipBuild,
    [switch]$CheckLive,
    [string]$BackendUrl = "http://127.0.0.1:8000",
    [string]$FrontendUrl = "http://127.0.0.1:5173"
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "../..")).Path
$python = Join-Path $repoRoot "backend/.venv/Scripts/python.exe"
$failures = [System.Collections.Generic.List[string]]::new()
$warnings = [System.Collections.Generic.List[string]]::new()

function Write-CheckResult {
    param([string]$Label, [bool]$Passed, [string]$Detail)
    $prefix = if ($Passed) { "PASS" } else { "FAIL" }
    $color = if ($Passed) { "Green" } else { "Red" }
    Write-Host "[$prefix] $Label - $Detail" -ForegroundColor $color
    if (-not $Passed) { $failures.Add("${Label}: $Detail") }
}

function Test-LocalUrl {
    param([string]$Url)
    $uri = [Uri]$Url
    if ($uri.Host -notin @("localhost", "127.0.0.1", "::1")) {
        throw "M7 preflight only permits localhost live checks: $Url"
    }
}

Push-Location $repoRoot
try {
    Write-Host "M7 final demo preflight" -ForegroundColor Cyan
    Write-Host "Repository: $repoRoot"

    Write-CheckResult "Backend virtualenv" (Test-Path $python) $python
    Write-CheckResult "Frontend package" (Test-Path "frontend/package.json") "frontend/package.json"
    Write-CheckResult "M7 demo seed" (Test-Path "backend/scripts/prepare_m7_demo.py") "prepare_m7_demo.py"
    $demoSamples = @(Get-ChildItem "docs/phase1/demo" -Filter "*.md" -File -ErrorAction SilentlyContinue)
    Write-CheckResult "M7 upload sample" ($demoSamples.Count -eq 1) "docs/phase1/demo/*.md"

    git diff --check
    Write-CheckResult "Git whitespace" ($LASTEXITCODE -eq 0) "git diff --check"

    $status = git status --short
    if ($status) {
        $warnings.Add("Working tree is not clean; review git status before the final demo.")
        Write-Host "[WARN] Working tree is not clean" -ForegroundColor Yellow
    } else {
        Write-Host "[PASS] Working tree is clean" -ForegroundColor Green
    }

    if (-not $env:AI_COURSE_DATABASE_URL) {
        $warnings.Add("AI_COURSE_DATABASE_URL is not set; startup will use the normal smart_class.db path.")
        Write-Host "[WARN] AI_COURSE_DATABASE_URL is not set" -ForegroundColor Yellow
    } else {
        Write-Host "[PASS] AI_COURSE_DATABASE_URL is explicitly set" -ForegroundColor Green
    }

    if (-not $SkipTests -and (Test-Path $python)) {
        $demoDatabaseUrl = $env:AI_COURSE_DATABASE_URL
        $testExitCode = 1
        try {
            Remove-Item Env:AI_COURSE_DATABASE_URL -ErrorAction SilentlyContinue
            & $python -m pytest `
                backend/tests/test_m7_demo_flow.py `
                backend/tests/test_m4a_isolation.py `
                backend/tests/test_m4a_route_contract.py `
                backend/tests/test_m4b_fakes.py `
                backend/tests/test_m4b_main_flows.py `
                backend/tests/test_r1_adapters.py `
                backend/tests/test_r1_adapter_migration.py `
                backend/tests/test_r1d_duix_avatar_provider.py `
                backend/tests/test_r2_task_runtime.py `
                backend/tests/test_r2b_video_task.py `
                backend/tests/test_r2b_ppt_task.py `
                backend/tests/test_r2c_tts_batch_task.py -q
            $testExitCode = $LASTEXITCODE
        } finally {
            if ($null -ne $demoDatabaseUrl) {
                $env:AI_COURSE_DATABASE_URL = $demoDatabaseUrl
            }
        }
        Write-CheckResult "Offline regression" ($testExitCode -eq 0) "M4A/M4B/R1/R1D/R2/M7"
    }
    if (-not $SkipBuild) {
        Push-Location (Join-Path $repoRoot "frontend")
        try {
            npm.cmd run build
            Write-CheckResult "Frontend build" ($LASTEXITCODE -eq 0) "npm.cmd run build"
        } finally {
            Pop-Location
        }
    }

    if ($CheckLive) {
        Test-LocalUrl $BackendUrl
        Test-LocalUrl $FrontendUrl
        $backendResponse = Invoke-WebRequest "$BackendUrl/openapi.json" -UseBasicParsing -TimeoutSec 10
        Write-CheckResult "Backend live" ($backendResponse.StatusCode -eq 200) "$BackendUrl/openapi.json"
        $frontendResponse = Invoke-WebRequest $FrontendUrl -UseBasicParsing -TimeoutSec 10
        Write-CheckResult "Frontend live" ($frontendResponse.StatusCode -eq 200) $FrontendUrl
    }
} catch {
    $failures.Add($_.Exception.Message)
    Write-Host "[FAIL] $($_.Exception.Message)" -ForegroundColor Red
} finally {
    Pop-Location
}

foreach ($warning in $warnings) {
    Write-Host "[WARN] $warning" -ForegroundColor Yellow
}

if ($failures.Count -gt 0) {
    Write-Host "M7 preflight failed with $($failures.Count) blocking issue(s)." -ForegroundColor Red
    exit 1
}

Write-Host "M7 preflight passed." -ForegroundColor Green
exit 0
