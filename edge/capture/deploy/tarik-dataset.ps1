<#
.SYNOPSIS
  Menarik folder dataset harian dari perangkat edge ke laptop, lalu membuat ZIP per hari
  yang siap diimport di LabelForge (Upload -> Import dataset, centang tandai untuk review).

.EXAMPLE
  .\tarik-dataset.ps1 -Device sysedge@192.168.110.243 -Tujuan D:\dataset-mondelez

  Folder yang sudah pernah ditarik dilewati, kecuali folder hari ini (masih bertambah) atau
  bila -Ulang dipakai. Data di perangkat tidak dihapus.
#>
param(
    [Parameter(Mandatory = $true)][string]$Device,
    [Parameter(Mandatory = $true)][string]$Tujuan,
    [string]$Sumber = "dataset",
    [switch]$Ulang
)
$ErrorActionPreference = "Stop"

New-Item -ItemType Directory -Force $Tujuan | Out-Null
$hari = ssh -o BatchMode=yes $Device "cd $Sumber && ls -d *-[0-9]*[0-9] 2>/dev/null"
if ($LASTEXITCODE -ne 0 -or -not $hari) { throw "Tidak ada folder dataset di ${Device}:$Sumber" }
$hariIni = (Get-Date).ToUniversalTime().ToString("yyyyMMdd")   # nama folder memakai UTC

foreach ($nama in $hari) {
    $lokal = Join-Path $Tujuan $nama
    $zip = "$lokal.zip"
    $masihBerjalan = $nama.EndsWith($hariIni)
    if ((Test-Path $zip) -and -not $Ulang -and -not $masihBerjalan) {
        Write-Host "lewati $nama (sudah ada)"
        continue
    }
    Write-Host "menarik $nama ..."
    if (Test-Path $lokal) { Remove-Item -Recurse -Force $lokal }
    scp -q -r -o BatchMode=yes "${Device}:$Sumber/$nama" $Tujuan
    if ($LASTEXITCODE -ne 0) { throw "scp $nama gagal" }
    # File .tmp dari penulisan yang sedang berlangsung tidak ikut ke ZIP.
    Get-ChildItem $lokal -Recurse -Filter *.tmp | Remove-Item -Force
    # Folder hari ini masih ditulis saat disalin: frame yang tersalin tanpa pasangannya dibuang
    # (gambar tanpa label akan terbaca sebagai contoh negatif). Ikut lengkap di tarikan berikutnya.
    $img = Join-Path $lokal "images"; $lbl = Join-Path $lokal "labels"
    $tidakLengkap = 0
    foreach ($f in Get-ChildItem $img -File) {
        if (-not (Test-Path (Join-Path $lbl "$($f.BaseName).txt"))) { Remove-Item -Force $f.FullName; $tidakLengkap++ }
    }
    foreach ($f in Get-ChildItem $lbl -File) {
        if (-not (Test-Path (Join-Path $img "$($f.BaseName).jpg"))) { Remove-Item -Force $f.FullName; $tidakLengkap++ }
    }
    if ($tidakLengkap) { Write-Host "  $tidakLengkap file tanpa pasangan dilewati (masih ditulis)" }
    if (Test-Path $zip) { Remove-Item -Force $zip }
    Compress-Archive -Path (Join-Path $lokal "*") -DestinationPath $zip
    $jumlah = (Get-ChildItem (Join-Path $lokal "images") -File).Count
    $catatan = if ($masihBerjalan) { " (hari ini, masih bertambah)" } else { "" }
    Write-Host ("  {0} gambar -> {1}{2}" -f $jumlah, $zip, $catatan)
}
