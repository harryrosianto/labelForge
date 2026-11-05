<#
.SYNOPSIS
  Menarik dataset dari perangkat edge ke laptop, lalu membuat ZIP per hari yang siap diimport
  di LabelForge (Upload -> Import dataset, centang tandai untuk review).

.DESCRIPTION
  Hanya dua koneksi SSH, berapa pun jumlah site dan harinya: satu untuk daftar (lfc inventory),
  satu untuk mengirim (lfc export). Frame yang sudah ada di laptop tidak dikirim ulang, jadi
  tarikan berulang di hari yang sama hanya membawa frame baru. Cocok untuk koneksi 4G yang
  lambat; ringkasan ditampilkan sebelum menarik.

.EXAMPLE
  .\tarik-dataset.ps1 -Device sysedge@100.119.125.104 -Tujuan D:\dataset-edge
  .\tarik-dataset.ps1 -Device sysedge@100.119.125.104 -Tujuan D:\dataset-edge -Site prepare-mondelez -Cek

  Hasil: <Tujuan>\<site>\<site>-ppe-YYYYMMDD.zip. -Cek hanya menampilkan ringkasan tanpa menarik.
  -Ulang menarik ulang semua frame. Data di perangkat tidak dihapus; setelah ZIP diperiksa,
  hapus di perangkat dengan `lfc clean <site> --older-than <hari>`.
#>
param(
    [Parameter(Mandatory = $true)][string]$Device,
    [Parameter(Mandatory = $true)][string]$Tujuan,
    [string]$Site,
    [switch]$Cek,
    [switch]$Ulang
)
$ErrorActionPreference = "Stop"
# Koneksi gagal/putus terdeteksi dalam ~1 menit, bukan menggantung.
$sshOpt = "-o BatchMode=yes -o ConnectTimeout=30 -o ServerAliveInterval=15 -o ServerAliveCountMax=4"
$lfc = ".local/bin/lfc"
$tarExe = Join-Path $env:SystemRoot "System32\tar.exe"   # GNU tar (mis. dari Git) salah membaca "C:\..."
$mulai = Get-Date

# --- 1. daftar di perangkat (koneksi SSH pertama) ---------------------------------------------
$inv = cmd /c "ssh $sshOpt $Device $lfc inventory"
if ($LASTEXITCODE -ne 0) { throw "lfc inventory gagal di $Device (sudah versi terbaru?)" }
$hari = @($inv | Where-Object { $_.Trim() } | ForEach-Object { $_ | ConvertFrom-Json })
if ($Site) { $hari = @($hari | Where-Object { $_.site -eq $Site }) }
if (-not $hari) { Write-Host "Tidak ada data di $Device$(if ($Site) { " untuk site $Site" })"; return }

$hariIni = (Get-Date).ToUniversalTime().ToString("yyyyMMdd")   # nama folder memakai UTC
$rencana = @()
foreach ($h in $hari) {
    $lokal = Join-Path (Join-Path $Tujuan $h.site) $h.day
    $zip = Join-Path (Join-Path $Tujuan $h.site) "$($h.site)-$($h.day).zip"
    if ($Ulang -and (Test-Path $lokal)) { Remove-Item -Recurse -Force $lokal }
    $punya = @()
    if (Test-Path (Join-Path $lokal "images")) {
        $punya = @(Get-ChildItem (Join-Path $lokal "images") -Filter *.jpg -File |
            Where-Object { Test-Path (Join-Path $lokal "labels\$($_.BaseName).txt") } |
            ForEach-Object { $_.BaseName })
    }
    $kurang = [Math]::Max($h.frames - $punya.Count, 0)
    $perluZip = $kurang -gt 0 -or -not (Test-Path $zip)
    $kb = if ($h.frames) { [Math]::Round($h.bytes * $kurang / $h.frames / 1KB) } else { 0 }
    $rencana += [pscustomobject]@{
        Site = $h.site; Hari = $h.day; DiPerangkat = $h.frames; SudahAda = $punya.Count
        AkanDitarik = $kurang; PerkiraanKB = $kb; Lokal = $lokal; Zip = $zip; Punya = $punya
        PerluZip = $perluZip; HariIni = $h.day.EndsWith($hariIni)
    }
}
$rencana | Format-Table Site, Hari, DiPerangkat, SudahAda, AkanDitarik, PerkiraanKB -AutoSize | Out-Host
$totalKB = ($rencana | Measure-Object PerkiraanKB -Sum).Sum
Write-Host ("Total akan ditarik: {0} frame, sekitar {1:N1} MB" -f ($rencana | Measure-Object AkanDitarik -Sum).Sum, ($totalKB / 1024))
if ($Cek) { return }

# --- 2. kirim hanya yang belum ada (koneksi SSH kedua) ----------------------------------------
$tarik = @($rencana | Where-Object { $_.AkanDitarik -gt 0 })
New-Item -ItemType Directory -Force $Tujuan | Out-Null
if ($tarik) {
    $req = Join-Path $Tujuan ".tarik-permintaan.txt"
    $tar = Join-Path $Tujuan ".tarik-data.tar"
    $baris = foreach ($r in $tarik) {
        "DAY $($r.Site) $($r.Hari)"
        foreach ($s in $r.Punya) { "HAVE $($r.Site) $($r.Hari) $s" }
    }
    [IO.File]::WriteAllLines($req, [string[]]$baris)   # ASCII/UTF-8 tanpa BOM
    $t0 = Get-Date
    cmd /c "ssh $sshOpt $Device $lfc export < `"$req`" > `"$tar`""
    if ($LASTEXITCODE -ne 0) { Remove-Item -Force $tar -ErrorAction SilentlyContinue; throw "lfc export gagal" }
    $detik = ((Get-Date) - $t0).TotalSeconds
    $mb = (Get-Item $tar).Length / 1MB
    Write-Host ("Diterima {0:N1} MB dalam {1:N0} detik ({2:N2} Mbit/s)" -f $mb, $detik, ($mb * 8 * 1.048576 / [Math]::Max($detik, 0.1)))
    & $tarExe -xf $tar -C $Tujuan
    if ($LASTEXITCODE -ne 0) { throw "membuka $tar gagal" }
    Remove-Item -Force $tar, $req
}

# --- 3. ZIP per hari yang berubah -------------------------------------------------------------
foreach ($r in $rencana | Where-Object { $_.PerluZip }) {
    if (-not (Test-Path $r.Lokal)) { continue }
    Get-ChildItem $r.Lokal -Recurse -Filter *.tmp | Remove-Item -Force
    if (Test-Path $r.Zip) { Remove-Item -Force $r.Zip }
    Compress-Archive -Path (Join-Path $r.Lokal "*") -DestinationPath $r.Zip
    $jumlah = (Get-ChildItem (Join-Path $r.Lokal "images") -File).Count
    $catatan = if ($r.HariIni) { " (hari ini, masih bertambah)" } else { "" }
    Write-Host ("  {0} gambar -> {1}{2}" -f $jumlah, $r.Zip, $catatan)
}
Write-Host ("Selesai dalam {0:N0} detik" -f ((Get-Date) - $mulai).TotalSeconds)
