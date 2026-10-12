<#
.SYNOPSIS
  Pemasangan pertama LabelForge di laptop/PC Windows baru (setelah git clone).

.DESCRIPTION
  Memeriksa prasyarat (Python, Node, Docker), membuat virtualenv backend dan memasang
  dependency (PyTorch CPU atau GPU), memasang dependency frontend, membuat .env beserta
  SECRET_KEY, dan opsional memulihkan data dari folder backup laptop lama.
  Aman dijalankan ulang: langkah yang sudah selesai dilewati.

.EXAMPLE
  .\setup.ps1                                        # instalasi baru, data kosong
  .\setup.ps1 -Restore "E:\labelforge-backup-20261012-1500"   # sekaligus pulihkan data lama
  .\setup.ps1 -Gpu                                   # PyTorch CUDA (PC dengan GPU NVIDIA)
#>
param(
    [string]$Restore,
    [switch]$Gpu
)

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$backend = Join-Path $root 'backend'
$frontend = Join-Path $root 'frontend'
$venvPy = Join-Path $backend '.venv\Scripts\python.exe'

function Step([string]$text) { Write-Host "`n== $text" -ForegroundColor Cyan }
function Has([string]$cmd) { [bool](Get-Command $cmd -ErrorAction SilentlyContinue) }
# Cek perintah native tanpa menghentikan script bila gagal (PowerShell 5.1 menganggap stderr error).
function Test-Native([string]$exe, [string[]]$arguments) {
    $prev = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try { & $exe @arguments *> $null; return $LASTEXITCODE -eq 0 } catch { return $false }
    finally { $ErrorActionPreference = $prev }
}
function Run([string]$exe, [string[]]$arguments) {
    & $exe @arguments
    if ($LASTEXITCODE -ne 0) { throw "Gagal: $exe $($arguments -join ' ')" }
}

# --- prasyarat ---------------------------------------------------------------
Step 'Memeriksa prasyarat'
$python = $null
if (Has 'py') {
    foreach ($v in '3.12', '3.13', '3.14', '3.11') {
        if (Test-Native 'py' @("-$v", '-c', 'import sys')) { $python = @('py', "-$v"); break }
    }
}
if (-not $python -and (Has 'python')) { $python = @('python') }
if (-not $python) { throw 'Python 3.11+ belum terpasang. Pasang dari https://www.python.org (centang "Add to PATH").' }
$pyExe, $pyArgs = $python[0], @($python | Select-Object -Skip 1)
# Tanpa tanda kutip ganda: PowerShell 5.1 membuangnya saat meneruskan argumen ke program lain.
$version = & $pyExe @pyArgs -c 'import sys; print(''%d.%d'' % sys.version_info[:2])'
if ([version]$version -lt [version]'3.11') { throw "Python $version terlalu lama; butuh 3.11 atau lebih baru." }
Write-Host "Python $version"

if (-not (Has 'node')) { throw 'Node.js belum terpasang. Pasang versi LTS dari https://nodejs.org' }
Write-Host "Node $(node --version)"
if (Has 'docker') { Write-Host 'Docker terpasang (dipakai untuk Redis).' }
else { Write-Warning 'Docker Desktop belum terpasang. Dibutuhkan untuk Redis saat menjalankan dev.ps1.' }

# --- backend --------------------------------------------------------------------
Step 'Backend: virtualenv dan dependency'
if (-not (Test-Path $venvPy)) {
    Run $pyExe ($pyArgs + @('-m', 'venv', (Join-Path $backend '.venv')))
}
Run $venvPy @('-m', 'pip', 'install', '--upgrade', 'pip', '--quiet')
if (-not (Test-Native $venvPy @('-c', 'import torch'))) {
    $index = if ($Gpu) { 'https://download.pytorch.org/whl/cu126' } else { 'https://download.pytorch.org/whl/cpu' }
    Write-Host "Memasang PyTorch ($(if ($Gpu) { 'GPU CUDA' } else { 'CPU' }))... ini bisa beberapa menit."
    Run $venvPy @('-m', 'pip', 'install', 'torch', 'torchvision', '--index-url', $index)
}
Push-Location $backend
try { Run $venvPy @('-m', 'pip', 'install', '-e', '.[ml,dev]', '--quiet') } finally { Pop-Location }

# --- frontend -------------------------------------------------------------------
Step 'Frontend: dependency'
Push-Location $frontend
try { Run 'npm' @('install', '--no-fund', '--no-audit') } finally { Pop-Location }

# --- restore data ---------------------------------------------------------------
if ($Restore) {
    Step "Memulihkan data dari $Restore"
    Push-Location $backend
    try { Run $venvPy @('-m', 'labelforge.cli', 'restore', '--input', $Restore) } finally { Pop-Location }
}

# --- .env -----------------------------------------------------------------------
Step 'Konfigurasi .env'
$envFile = Join-Path $root '.env'
if (-not (Test-Path $envFile)) {
    Copy-Item (Join-Path $root '.env.example') $envFile
    Write-Host '.env dibuat dari .env.example'
}
$hasKey = Select-String -Path $envFile -Pattern '^\s*SECRET_KEY\s*=\s*\S' -Quiet
if (-not $hasKey) {
    $key = & $venvPy -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'
    Add-Content -Path $envFile -Value "SECRET_KEY=$key" -Encoding utf8
    Write-Host 'SECRET_KEY baru dibuat (untuk enkripsi URL kamera RTSP).'
}

# --- database -------------------------------------------------------------------
Step 'Database'
Push-Location $backend
try { Run $venvPy @('-m', 'labelforge.cli', 'migrate') } finally { Pop-Location }

Write-Host "`nSelesai. Jalankan LabelForge dengan: .\dev.ps1" -ForegroundColor Green
Write-Host 'Model AI (sekitar 1,5 GB) diunduh otomatis saat worker pertama kali berjalan, kecuali ikut dipulihkan dari backup.'
