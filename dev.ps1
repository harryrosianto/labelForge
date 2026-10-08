<#
.SYNOPSIS
  Menjalankan LabelForge untuk development dengan satu perintah (Windows).

.DESCRIPTION
  Memastikan Redis (Docker) berjalan, menjalankan migrasi DB, lalu membuka tiga jendela:
  API (port 8000), worker Celery, dan frontend Vite (port 5173). Browser dibuka setelah
  API siap. Tutup jendela atau jalankan `.\dev.ps1 -Stop` untuk mematikan.

.EXAMPLE
  .\dev.ps1              # jalankan semua
  .\dev.ps1 -NoWorker    # tanpa worker (auto-label tidak jalan, hemat RAM)
  .\dev.ps1 -Stop        # matikan API, worker, dan frontend
#>
param(
    [switch]$NoWorker,
    [switch]$Stop
)

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$backend = Join-Path $root 'backend'
$frontend = Join-Path $root 'frontend'
$venv = Join-Path $backend '.venv\Scripts'

function Stop-LabelForge {
    foreach ($port in 8000, 5173) {
        Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
            ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
    }
    Get-CimInstance Win32_Process |
        Where-Object { $_.CommandLine -match 'labelforge\.worker\.celery_app|uvicorn.*labelforge|vite' } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    Write-Host 'API, worker, dan frontend dimatikan. Redis tetap berjalan.' -ForegroundColor Yellow
}

if ($Stop) { Stop-LabelForge; return }

# --- prasyarat ---------------------------------------------------------------
if (-not (Test-Path (Join-Path $venv 'python.exe'))) {
    throw "Virtualenv backend belum ada ($venv). Ikuti bagian 'Menjalankan untuk development' di README."
}
if (-not (Test-Path (Join-Path $frontend 'node_modules'))) {
    Write-Host 'Memasang dependency frontend (npm install)...' -ForegroundColor Cyan
    Push-Location $frontend; npm install; Pop-Location
}

$busy = 8000, 5173 | Where-Object { Get-NetTCPConnection -LocalPort $_ -State Listen -ErrorAction SilentlyContinue }
if ($busy) {
    throw "Port $($busy -join ', ') sudah dipakai. Tutup terminal LabelForge yang masih berjalan, atau jalankan .\dev.ps1 -Stop"
}

# --- Redis --------------------------------------------------------------------
docker info *> $null
if ($LASTEXITCODE -ne 0) {
    throw 'Docker Desktop belum berjalan atau sedang di-pause. Buka Docker Desktop (Resume bila di-pause), tunggu sampai siap, lalu jalankan ulang.'
}
$redis = docker ps -a --filter 'name=^labelforge-redis$' --format '{{.Names}}'
if ($redis) {
    docker start labelforge-redis | Out-Null
} else {
    Write-Host 'Membuat container Redis...' -ForegroundColor Cyan
    docker run -d --name labelforge-redis -p 6379:6379 --restart unless-stopped redis:7-alpine | Out-Null
}
Write-Host 'Redis siap.' -ForegroundColor Green

# --- migrasi DB ---------------------------------------------------------------
Push-Location $backend
& (Join-Path $venv 'python.exe') -m labelforge.cli migrate
Pop-Location

# --- jalankan tiap layanan di jendela sendiri ----------------------------------
function Start-Window([string]$title, [string]$dir, [string]$command) {
    $script = "`$Host.UI.RawUI.WindowTitle = '$title'; Set-Location '$dir'; $command"
    Start-Process powershell -WorkingDirectory $dir -ArgumentList @(
        '-NoExit', '-ExecutionPolicy', 'Bypass', '-Command', $script
    )
}

Start-Window 'LabelForge API' $backend "& '$venv\uvicorn.exe' labelforge.api.main:app --reload --port 8000"
if (-not $NoWorker) {
    Start-Window 'LabelForge Worker' $backend `
        "& '$venv\celery.exe' -A labelforge.worker.celery_app worker --pool=solo --concurrency=1 -Q inference,io --loglevel=INFO"
}
Start-Window 'LabelForge Frontend' $frontend 'npm run dev -- --port 5173 --strictPort'

# --- tunggu API lalu buka browser ----------------------------------------------
Write-Host 'Menunggu API siap...' -ForegroundColor Cyan
$ready = $false
foreach ($i in 1..60) {
    try {
        Invoke-WebRequest -UseBasicParsing 'http://localhost:8000/api/health' -TimeoutSec 3 | Out-Null
        $ready = $true; break
    } catch { Start-Sleep -Seconds 1 }
}
if ($ready) {
    Start-Process 'http://localhost:5173'
    Write-Host 'LabelForge berjalan di http://localhost:5173' -ForegroundColor Green
    if (-not $NoWorker) { Write-Host 'Worker butuh sekitar 20 detik untuk memuat model AI.' }
} else {
    Write-Warning 'API belum merespons setelah 60 detik. Cek jendela "LabelForge API".'
}
