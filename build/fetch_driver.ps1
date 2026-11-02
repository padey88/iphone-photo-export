# Fetch and stage Apple's device driver (usbmuxd) so the installer can carry it.
# Apple does not publish the MSI on its own: we download the official iTunes
# setup from Apple's CDN and pull AppleMobileDeviceSupport64.msi out of it.
param(
    [string]$OutDir = "C:\build\ipe\driver",
    [string]$CacheDir = "C:\build\dl"
)
$ErrorActionPreference = "Stop"
$msi = Join-Path $OutDir "AppleMobileDeviceSupport64.msi"
if (Test-Path $msi) { Write-Host "driver already staged: $msi"; exit 0 }

New-Item -ItemType Directory -Force -Path $OutDir, $CacheDir | Out-Null

$setup = Join-Path $CacheDir "iTunes64Setup.exe"
if (-not (Test-Path $setup)) {
    Write-Host "resolving the current iTunes 64-bit URL from Apple..."
    $url = $null
    try {
        $html = (Invoke-WebRequest -UseBasicParsing -Uri "https://www.apple.com/itunes/download/win64" -TimeoutSec 60).Content
        $m = [regex]::Match($html, 'https://[^"'']*iTunes64Setup\.exe')
        if ($m.Success) { $url = $m.Value }
    } catch { Write-Host "apple landing page failed: $($_.Exception.Message)" }
    if (-not $url) {
        # winged fallback: ask winget where the package lives, then download it
        $dl = Join-Path $CacheDir "winget-itunes"
        winget download --id Apple.iTunes --download-directory $dl `
            --accept-package-agreements --accept-source-agreements --disable-interactivity | Out-Null
        $found = Get-ChildItem $dl -Filter "iTunes*.exe" | Select-Object -First 1
        if (-not $found) { throw "could not obtain iTunes setup" }
        Copy-Item $found.FullName $setup -Force
    } else {
        Write-Host "downloading $url"
        Invoke-WebRequest -UseBasicParsing -Uri $url -OutFile $setup -TimeoutSec 900
    }
}
Write-Host ("itunes setup: {0:N1} MB" -f ((Get-Item $setup).Length / 1MB))

$sevenZip = @("C:\Program Files\7-Zip\7z.exe", "C:\Program Files (x86)\7-Zip\7z.exe") |
    Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $sevenZip) { throw "7-Zip is required to unpack the iTunes setup (winget install 7zip.7zip)" }

& $sevenZip e -y "-o$OutDir" $setup "AppleMobileDeviceSupport64.msi" | Out-Null
if (-not (Test-Path $msi)) { throw "AppleMobileDeviceSupport64.msi not found inside the iTunes setup" }
Write-Host ("staged driver: {0}  ({1:N1} MB)" -f $msi, ((Get-Item $msi).Length / 1MB))
