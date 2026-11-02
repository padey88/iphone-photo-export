# Build (run on Windows): produces ONE installable .exe.
#   .\build\build.ps1
# Pipeline: stage ffmpeg + Apple driver -> icon -> PyInstaller -> selftest -> Inno Setup
param(
    [string]$BuildRoot = "C:\build\ipe",
    [string]$Version = "",
    [switch]$SkipFetch
)
$ErrorActionPreference = "Stop"
function Step($m) { Write-Host "`n=== $m ===" -ForegroundColor Cyan }

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $Root
$Venv = Join-Path $BuildRoot "venv"
$Py = Join-Path $Venv "Scripts\python.exe"
if (-not (Test-Path $Py)) { throw "venv missing: $Py (run setup.ps1 first)" }
if (-not $Version) {
    $Version = (Get-Content (Join-Path $Root "VERSION") -ErrorAction SilentlyContinue)
    if (-not $Version) { $Version = "1.0.0" }
}
$Version = $Version.Trim()

Step "1/6 staging ffmpeg"
$Bin = Join-Path $Root "bin"
New-Item -ItemType Directory -Force -Path $Bin | Out-Null
if (-not $SkipFetch -and -not (Test-Path (Join-Path $Bin "ffmpeg.exe"))) {
    $Zip = Join-Path $BuildRoot "ffmpeg-essentials.zip"
    if (-not (Test-Path $Zip)) {
        Invoke-WebRequest -UseBasicParsing -Uri "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip" -OutFile $Zip -TimeoutSec 900
    }
    $Tmp = Join-Path $BuildRoot "ffmpeg-extract"
    if (Test-Path $Tmp) { Remove-Item -Recurse -Force $Tmp }
    Expand-Archive -Path $Zip -DestinationPath $Tmp -Force
    $src = Get-ChildItem -Recurse $Tmp -Filter ffmpeg.exe | Select-Object -First 1
    Copy-Item $src.FullName (Join-Path $Bin "ffmpeg.exe") -Force
    $prb = Get-ChildItem -Recurse $Tmp -Filter ffprobe.exe | Select-Object -First 1
    # ffprobe is not used by the app: shipping it would add ~100 MB for nothing.
    if ($prb) { Write-Host "  (skipping ffprobe: not used by the app)" }
}
foreach ($f in @("ffmpeg.exe", "ffprobe.exe")) {
    $p = Join-Path $Bin $f
    if (Test-Path $p) { Write-Host ("  {0}  {1:N1} MB" -f $f, ((Get-Item $p).Length / 1MB)) }
}

Step "2/6 staging Apple device driver"
$DriverDir = Join-Path $Root "drivers"
New-Item -ItemType Directory -Force -Path $DriverDir | Out-Null
if (-not $SkipFetch) {
    & (Join-Path $PSScriptRoot "fetch_driver.ps1") -OutDir $DriverDir -CacheDir (Join-Path $BuildRoot "dl")
}
$Msi = Join-Path $DriverDir "AppleMobileDeviceSupport64.msi"
if (-not (Test-Path $Msi)) { throw "Apple driver MSI missing: $Msi" }

Step "3/6 making the app icon"
& $Py (Join-Path $PSScriptRoot "make_icon.py")

Step "4/6 PyInstaller"
& $Py -m PyInstaller --noconfirm --clean `
    --distpath (Join-Path $Root "payload") --workpath (Join-Path $BuildRoot "pybuild") `
    (Join-Path $PSScriptRoot "pyinstaller.spec")
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }
$Payload = Join-Path $Root "payload\iPhonePhotoExport"
if (-not (Test-Path (Join-Path $Payload "iPhonePhotoExport.exe"))) { throw "no exe produced" }
# the driver travels inside the payload so the installer is a single file
New-Item -ItemType Directory -Force -Path (Join-Path $Payload "drivers") | Out-Null
Copy-Item $Msi (Join-Path $Payload "drivers") -Force

Step "5/6 smoke-testing the frozen app"
# Windowed exe: no stdout reaches the parent, so the app writes its report to
# %LOCALAPPDATA%\iPhonePhotoExport\selftest.txt and returns an exit code.
$reportFile = Join-Path $env:LOCALAPPDATA "iPhonePhotoExport\selftest.txt"
if (Test-Path $reportFile) { Remove-Item $reportFile -Force }
$proc = Start-Process -FilePath (Join-Path $Payload "iPhonePhotoExport.exe") `
    -ArgumentList "--selftest" -PassThru -Wait -WindowStyle Hidden
if (Test-Path $reportFile) { Get-Content $reportFile | ForEach-Object { Write-Host "  $_" } }
if ($proc.ExitCode -ne 0) { throw "selftest failed (exit $($proc.ExitCode)) - see $reportFile" }
Write-Host "  selftest: PASS" -ForegroundColor Green

Step "6/6 Inno Setup"
$Iscc = @(
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
    "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    "C:\Program Files\Inno Setup 6\ISCC.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $Iscc) { throw "ISCC.exe not found - winget install JRSoftware.InnoSetup" }

$Out = Join-Path $Root "installer"
New-Item -ItemType Directory -Force -Path $Out | Out-Null
& $Iscc "/DAppVersion=$Version" "/DSourceDir=$Payload" "/O$Out" (Join-Path $PSScriptRoot "installer.iss")
if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed" }

$exe = Get-ChildItem $Out -Filter "*Setup*.exe" | Sort-Object LastWriteTime -Descending | Select-Object -First 1
Write-Host "`nBUILT: $($exe.FullName)  ($([math]::Round($exe.Length/1MB,1)) MB)" -ForegroundColor Green
