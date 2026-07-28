# dev-stack.ps1 - 统一启动 PaddleOCR 容器 + 主后端（Windows 本地开发）。
# 统一课程建设九步实施计划 Step 2：OCR 服务随主后端同步启动/关闭。
#
# 流程：检查 Docker -> 启 paddleocr 容器 -> 轮询 /health -> 启动后端 uvicorn
#       -> 捕获 Ctrl+C/后端退出 -> 停止本地 OCR 容器。
#
# 用法：
#   .\scripts\dev-stack.ps1                 # 启动 OCR + 后端（默认）
#   .\scripts\dev-stack.ps1 -SkipBackend    # 仅启动 OCR 容器
#   .\scripts\dev-stack.ps1 -SkipOcr        # 跳过 OCR（OCR 已在别处运行）
#   .\scripts\dev-stack.ps1 -SkipBackend -SkipOcr  # no-op
#
# 主后端通过 PADDLEOCR_URL（默认 http://127.0.0.1:8090）调用 OCR 服务。
# OCR 不可用时，PDF/图片型 PPT/图片/DOC-DOCX 任务以 OCR_SERVICE_UNAVAILABLE 失败可重试，
# 普通问答不受影响，不伪造 OCR 输出。
[CmdletBinding()]
param(
    [switch]$SkipBackend,
    [switch]$SkipOcr,
    [string]$BackendHost = "127.0.0.1",
    [int]$BackendPort = 8000,
    [int]$HealthTimeoutS = 120
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$ocrCompose = Join-Path $repoRoot "deploy\paddleocr\compose.yml"

function Write-Step($msg) { Write-Host "[dev-stack] $msg" -ForegroundColor Cyan }
function Write-Ok($msg)   { Write-Host "[dev-stack] $msg" -ForegroundColor Green }
function Write-Warn($msg) { Write-Host "[dev-stack] $msg" -ForegroundColor Yellow }

# --- 1. 检查 Docker ---
if (-not $SkipOcr) {
    Write-Step "Checking Docker..."
    try {
        $dockerVersion = & docker --version 2>&1
        if ($LASTEXITCODE -ne 0) { throw "docker not available" }
        Write-Ok "Docker: $dockerVersion"
    } catch {
        Write-Warn "Docker 不可用。OCR 服务将不会启动；OCR 相关任务会以 OCR_SERVICE_UNAVAILABLE 失败。"
        Write-Warn "如需 OCR，请先启动 Docker Desktop 再运行本脚本。"
        if (-not $SkipBackend) {
            Write-Step "继续仅启动后端（OCR 端口 fail-closed）..."
        }
        $SkipOcr = $true
    }
}

# --- 2. 启动 PaddleOCR 容器 ---
if (-not $SkipOcr) {
    Write-Step "Starting PaddleOCR container (deploy/paddleocr/compose.yml)..."
    & docker compose -f $ocrCompose up -d --build
    if ($LASTEXITCODE -ne 0) {
        Write-Warn "OCR 容器启动失败。继续仅启动后端（OCR 端口 fail-closed）。"
        $SkipOcr = $true
    } else {
        Write-Ok "OCR 容器已启动（127.0.0.1:8090）"
    }
}

# --- 3. 轮询 /health ---
if (-not $SkipOcr) {
    Write-Step "Waiting for OCR /health (最多 ${HealthTimeoutS}s)..."
    $deadline = (Get-Date).AddSeconds($HealthTimeoutS)
    $healthy = $false
    while ((Get-Date) -lt $deadline) {
        try {
            $resp = Invoke-RestMethod -Uri "http://127.0.0.1:8090/health" -TimeoutSec 4 -ErrorAction Stop
            if ($resp.status -eq "ok") {
                $healthy = $true
                Write-Ok "OCR healthy: $($resp.provider_version) gpu=$($resp.gpu)"
                break
            }
        } catch {
            Start-Sleep -Seconds 2
        }
        Start-Sleep -Seconds 2
    }
    if (-not $healthy) {
        Write-Warn "OCR /health 未就绪（超时）。后端仍会启动；OCR 端口会 fail-closed 直到服务就绪。"
    }
}

# --- 4. 启动后端 ---
if (-not $SkipBackend) {
    Write-Step "Starting backend uvicorn ($BackendHost`:$BackendPort)..."
    Push-Location (Join-Path $repoRoot "backend")
    try {
        # 设置 OCR URL 环境变量（与 config 默认一致，显式传递便于覆盖）
        $env:PADDLEOCR_URL = "http://127.0.0.1:8090"
        & python -m uvicorn app.main:app --host $BackendHost --port $BackendPort --reload
        $backendExit = $LASTEXITCODE
    } finally {
        Pop-Location
    }
    Write-Step "Backend exited (code $backendExit)."
} else {
    Write-Step "Skipping backend (-SkipBackend). Press Ctrl+C to stop OCR container."
    # 等待用户中断
    try { Wait-Event -Timeout -1 } catch {}
}

# --- 5. 退出时停止本地 OCR 容器 ---
if (-not $SkipOcr) {
    Write-Step "Stopping local OCR container..."
    & docker compose -f $ocrCompose down 2>&1 | Out-Null
    Write-Ok "OCR container stopped."
}
Write-Ok "dev-stack done."
