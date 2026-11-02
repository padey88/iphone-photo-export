# End-to-end check of the FROZEN app (no iPhone needed).
#   .\build\verify_frozen.ps1
# Builds a fake /DCIM tree, runs the installed exe against it, and drives the
# real HTTP API: connect -> filter -> export -> verify manifest.
param(
    [string]$Exe = "C:\build\ipe\src\payload\iPhonePhotoExport\iPhonePhotoExport.exe",
    [string]$Port = "8791"
)
$ErrorActionPreference = "Stop"
function Step($m) { Write-Host "`n=== $m ===" -ForegroundColor Cyan }
function Fail($m) { Write-Host "FAIL: $m" -ForegroundColor Red; exit 1 }
function Ok($m) { Write-Host "  ok  $m" -ForegroundColor Green }

if (-not (Test-Path $Exe)) { Fail "exe not found: $Exe" }

$work = Join-Path $env:TEMP ("ipeverify-" + [guid]::NewGuid().ToString("N").Substring(0, 8))
$fake = Join-Path $work "phone"
$dest = Join-Path $work "out"
New-Item -ItemType Directory -Force -Path (Join-Path $fake "DCIM\100APPLE"), $dest | Out-Null

Step "1/5 building a fake camera roll"
# a real JPEG and a Live Photo pair, so the pairing + thumbnail paths run
Add-Type -AssemblyName System.Drawing
$img = New-Object System.Drawing.Bitmap 800, 600
$g = [System.Drawing.Graphics]::FromImage($img)
$g.Clear([System.Drawing.Color]::FromArgb(40, 120, 220))
$g.DrawString("A", (New-Object System.Drawing.Font("Arial", 200)), [System.Drawing.Brushes]::White, 300, 150)
$img.Save((Join-Path $fake "DCIM\100APPLE\IMG_0001.JPG"), [System.Drawing.Imaging.ImageFormat]::Jpeg)
$g.Dispose(); $img.Dispose()
Copy-Item (Join-Path $fake "DCIM\100APPLE\IMG_0001.JPG") (Join-Path $fake "DCIM\100APPLE\IMG_0002.JPG")
# a fake Live Photo: still + .MOV sibling sharing the stem
New-Item -ItemType File -Path (Join-Path $fake "DCIM\100APPLE\IMG_0003.HEIC") -Force |
    ForEach-Object { [IO.File]::WriteAllBytes($_.FullName, [byte[]](0..255)) }
[IO.File]::WriteAllBytes((Join-Path $fake "DCIM\100APPLE\IMG_0003.MOV"), [byte[]](0..255))
[IO.File]::WriteAllBytes((Join-Path $fake "DCIM\100APPLE\RPReplay_Final1.MP4"), [byte[]](0..200))
$phoneBytes = (Get-ChildItem -Recurse -File $fake | Measure-Object Length -Sum).Sum
$phoneCount = (Get-ChildItem -Recurse -File $fake).Count
Ok ("{0} files, {1:N0} bytes" -f $phoneCount, $phoneBytes)

Step "2/5 starting the frozen app against the fake device"
$env:IPHONE_EXPORT_FAKE = $fake
$env:IPHONE_EXPORT_DEST = $dest
$p = Start-Process -FilePath $Exe -ArgumentList "--serve", "--port", $Port -PassThru -WindowStyle Hidden
try {
    $base = "http://127.0.0.1:$Port"
    $ready = $false
    foreach ($i in 1..60) {
        Start-Sleep -Milliseconds 500
        try { Invoke-WebRequest -UseBasicParsing -Uri "$base/api/state" -TimeoutSec 3 | Out-Null; $ready = $true; break } catch {}
    }
    if (-not $ready) { Fail "app did not start serving on $Port" }
    Ok "server up on $Port"

    Step "3/5 connect + inventory"
    $conn = Invoke-RestMethod -Uri "$base/api/connect" -Method Post -Body "{}" -ContentType "application/json"
    $n = $conn.items.Count
    if ($n -ne $phoneCount) { Fail "inventory $n != $phoneCount" }
    Ok "$n files inventoried"
    $kinds = ($conn.items | Group-Object kind | ForEach-Object { "$($_.Name)=$($_.Count)" }) -join " "
    Ok "kinds: $kinds"
    if ($conn.items | Where-Object { $_.kind -eq "live" }) { Ok "Live Photo still detected" } else { Fail "no live photo still detected" }

    Step "4/5 filter (videos only) and sanity-check the API"
    $filt = Invoke-RestMethod -Uri "$base/api/filter" -Method Post -ContentType "application/json" `
        -Body '{"date_mode":"all","kinds":["video","live_mov","recording"]}'
    Ok "$($filt.items.Count) video-kind items matched"
    $thumb = Invoke-WebRequest -UseBasicParsing -Uri ("$base/api/thumb?path=" + [uri]::EscapeDataString($conn.items[0].path))
    Ok "thumbnail endpoint -> HTTP $($thumb.StatusCode) ($($thumb.RawContentLength) bytes)"

    Step "5/5 export + verification"
    $paths = @($conn.items | Select-Object -ExpandProperty path)
    $body = @{ paths = $paths } | ConvertTo-Json -Depth 4
    Invoke-RestMethod -Uri "$base/api/export" -Method Post -Body $body -ContentType "application/json" | Out-Null
    $job = $null
    foreach ($i in 1..120) {
        Start-Sleep -Milliseconds 700
        $job = Invoke-RestMethod -Uri "$base/api/export/status"
        if ($job.state -ne "running") { break }
    }
    if ($job.state -ne "done") { Fail "export state=$($job.state) err=$($job.error)" }
    Ok ("copied=$($job.copied) resumed=$($job.resumed) failed=$($job.failed) missing=$($job.missing) mismatch=$($job.mismatch) safe=$($job.safe_to_delete)")
    if (-not $job.safe_to_delete) { Fail "export not verified safe" }

    $manifest = Get-ChildItem -Recurse -Filter manifest.csv $dest | Select-Object -First 1
    if (-not $manifest) { Fail "no manifest.csv written" }
    $rows = Import-Csv $manifest.FullName
    Ok "manifest.csv: $($rows.Count) rows, sha256 present on $((@($rows | Where-Object { $_.sha256 }).Count))"
    $verify = Get-ChildItem -Recurse -Filter VERIFY.txt $dest | Select-Object -First 1
    Ok "VERIFY.txt: $((Get-Content $verify.FullName | Select-Object -First 1))"
    $outBytes = (Get-ChildItem -Recurse -File $dest | Measure-Object Length -Sum).Sum
    if ($outBytes -le 0) { Fail "nothing on disk" }
    Ok ("exported {0:N0} bytes to {1}" -f $outBytes, $dest)

    Write-Host "`nVERIFY: PASS" -ForegroundColor Green
    exit 0
}
finally {
    if ($p -and -not $p.HasExited) { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue }
    Remove-Item Env:IPHONE_EXPORT_FAKE -ErrorAction SilentlyContinue
    Remove-Item Env:IPHONE_EXPORT_DEST -ErrorAction SilentlyContinue
}
