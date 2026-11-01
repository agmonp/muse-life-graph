# Build the downloadable Windows app from a clean copy of the committed code.
#
#   powershell -File packaging\build.ps1 [-Ref HEAD] [-FfmpegDir <folder with ffmpeg.exe, ffprobe.exe and DLLs>]
#
# The code is exported with `git archive`, so nothing that is not committed (data/, .env, faces, films) can get in.
# Output: dist\MuseLifeGraph-windows.zip (+ .sha256). scripts\check_bundle.py must pass before the zip is made.
# Without -FfmpegDir the app uses an ffmpeg on the user's PATH (the release workflow always bundles one).
param([string]$Ref = "HEAD", [string]$FfmpegDir = "", [string]$Python = "")

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$work = Join-Path $env:TEMP "mlg_build"
$src = Join-Path $work "src"
$dist = Join-Path $repo "dist"
if (-not $Python) { $Python = Join-Path $repo ".venv\Scripts\python.exe" }

if (Test-Path $work) { Remove-Item -Recurse -Force $work }
New-Item -ItemType Directory -Force $src | Out-Null
New-Item -ItemType Directory -Force $dist | Out-Null
git -C $repo archive --format=zip -o (Join-Path $work "src.zip") $Ref
Expand-Archive (Join-Path $work "src.zip") $src

& $Python -m PyInstaller (Join-Path $src "packaging\muse_life_graph.spec") --noconfirm `
    --distpath (Join-Path $work "dist") --workpath (Join-Path $work "build")
if ($LASTEXITCODE) { throw "PyInstaller failed" }
$app = Join-Path $work "dist\MuseLifeGraph"

if ($FfmpegDir) {
    $ff = Join-Path $app "ffmpeg"
    New-Item -ItemType Directory -Force $ff | Out-Null
    Copy-Item (Join-Path $FfmpegDir "ffmpeg.exe"), (Join-Path $FfmpegDir "ffprobe.exe") $ff
    Get-ChildItem $FfmpegDir -Filter *.dll | Copy-Item -Destination $ff
    $lic = Join-Path (Split-Path -Parent $FfmpegDir) "LICENSE.txt"
    if (Test-Path $lic) { Copy-Item $lic (Join-Path $ff "LICENSE.txt") }
}
Copy-Item (Join-Path $src "packaging\READ-ME-FIRST.txt") $app

$envFile = Join-Path $repo ".env"
& $Python (Join-Path $repo "scripts\check_bundle.py") $app --env $envFile
if ($LASTEXITCODE) { throw "the build carries something personal - not packaged" }

$zip = Join-Path $dist "MuseLifeGraph-windows.zip"
if (Test-Path $zip) { Remove-Item $zip }
Compress-Archive -Path $app -DestinationPath $zip -CompressionLevel Optimal
$hash = (Get-FileHash $zip -Algorithm SHA256).Hash.ToLower()
"$hash  MuseLifeGraph-windows.zip" | Out-File -Encoding ascii (Join-Path $dist "MuseLifeGraph-windows.zip.sha256")
& $Python (Join-Path $repo "scripts\check_bundle.py") $zip --env $envFile
if ($LASTEXITCODE) { throw "the zip carries something personal" }
"{0:N0} MB  {1}" -f ((Get-Item $zip).Length / 1MB), $zip
