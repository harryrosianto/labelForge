<#
.SYNOPSIS
  Menarik folder dataset harian dari perangkat edge ke laptop, lalu membuat ZIP per hari
  yang siap diimport di LabelForge (Upload -> Import dataset, centang tandai untuk review).

.EXAMPLE
  .\tarik-dataset.ps1 -Device sysedge@192.168.110.243 -Tujuan D:\dataset-edge
  .\tarik-dataset.ps1 -Device sysedge@192.168.110.243 -Tujuan D:\dataset-edge -Site mondelez-cikarang

  Hasil: <Tujuan>\<site>\<site>-ppe-YYYYMMDD.zip. Tanpa -Site semua site ditarik. Folder yang
  sudah pernah ditarik dilewati, kecuali folder hari ini (masih bertambah) atau bila -Ulang
  dipakai. Data di perangkat tidak dihapus; setelah ZIP diperiksa, hapus di perangkat dengan
  `lfc clean <site> --older-than <hari>`.
#>
param(
    [Parameter(Mandatory = $true)][string]$Device,
    [Parameter(Mandatory = $true)][string]$Tujuan,
    [string]$Site,
    [string]$Sumber = "dataset",
    [switch]$Ulang
)
$ErrorActionPreference = "Stop"
# Koneksi gagal/putus terdeteksi dalam ~1 menit, bukan menggantung (Wi-Fi perangkat bisa naik-turun).
$sshOpt = @("-o", "BatchMode=yes", "-o", "ConnectTimeout=30", "-o", "ServerAliveInterval=15", "-o", "ServerAliveCountMax=4")

if ($Site) {
    $sites = @($Site)
} else {
    $sites = ssh @sshOpt $Device "find $Sumber -mindepth 1 -maxdepth 1 -type d -printf '%f\n' | sort"
    if ($LASTEXITCODE -ne 0 -or -not $sites) { throw "Tidak ada site di ${Device}:$Sumber" }
}
$hariIni = (Get-Date).ToUniversalTime().ToString("yyyyMMdd")   # nama folder memakai UTC

foreach ($s in $sites) {
    if ($s -notmatch '^[a-z0-9][a-z0-9-]{0,39}$') { Write-Host "lewati '$s' (bukan nama site)"; continue }
    $hari = ssh @sshOpt $Device "cd $Sumber/$s 2>/dev/null && ls -d *-[0-9]*[0-9] 2>/dev/null"
    if (-not $hari) { Write-Host "site ${s}: belum ada data"; continue }
    $dirSite = Join-Path $Tujuan $s
    New-Item -ItemType Directory -Force $dirSite | Out-Null

    foreach ($nama in $hari) {
        $lokal = Join-Path $dirSite $nama
        $zip = Join-Path $dirSite "$s-$nama.zip"
        $masihBerjalan = $nama.EndsWith($hariIni)
        if ((Test-Path $zip) -and -not $Ulang -and -not $masihBerjalan) {
            Write-Host "lewati $s/$nama (sudah ada)"
            continue
        }
        Write-Host "menarik $s/$nama ..."
        if (Test-Path $lokal) { Remove-Item -Recurse -Force $lokal }
        # Satu aliran tar per hari (jauh lebih cepat dari salin per file). Pipa PowerShell 5.1
        # merusak data biner, jadi aliran ditulis ke file lewat cmd, lalu dibuka tar.exe Windows.
        $tar = Join-Path $dirSite "$nama.tar"
        # GNU tar keluar 1 bila ada file yang berubah saat dibaca (folder hari ini masih ditulis
        # perekam); itu wajar, frame yang belum lengkap dibuang di bawah.
        $remote = "tar --warning=no-file-changed -C $Sumber/$s -cf - $nama; rc=`$?; [ `$rc -le 1 ]"
        cmd /c "ssh $($sshOpt -join ' ') $Device `"$remote`" > `"$tar`""
        if ($LASTEXITCODE -ne 0) { Remove-Item -Force $tar -ErrorAction SilentlyContinue; throw "menarik $s/$nama gagal" }
        # tar.exe bawaan Windows; GNU tar (mis. dari Git) membaca "C:\..." sebagai host remote.
        & (Join-Path $env:SystemRoot "System32\tar.exe") -xf $tar -C $dirSite
        if ($LASTEXITCODE -ne 0) { throw "membuka $tar gagal" }
        Remove-Item -Force $tar
        # File .tmp dari penulisan yang sedang berlangsung tidak ikut ke ZIP.
        Get-ChildItem $lokal -Recurse -Filter *.tmp | Remove-Item -Force
        # Folder hari ini masih ditulis saat disalin: frame yang tersalin tanpa pasangannya
        # dibuang (gambar tanpa label terbaca sebagai contoh negatif). Lengkap di tarikan berikutnya.
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
        $jumlah = (Get-ChildItem $img -File).Count
        $catatan = if ($masihBerjalan) { " (hari ini, masih bertambah)" } else { "" }
        Write-Host ("  {0} gambar -> {1}{2}" -f $jumlah, $zip, $catatan)
    }
}
