<#
.SYNOPSIS
  Packages the OPCOM Romania Home Assistant integration into a delivery .zip.

.DESCRIPTION
  Builds a clean zip ready to share with users:
    custom_components/opcom_ro/   the integration (no __pycache__ / .pyc)
    README.md, LICENSE, opcom-guide.html   docs at the zip root

  The custom_components/ path is preserved, so a user can extract the zip
  straight into their Home Assistant config folder and the integration lands
  in the right place.

  Output: dist/opcom_ro-<version>.zip   (version read from manifest.json)

.EXAMPLE
  .\build-release.ps1
#>

[CmdletBinding()]
param(
  [string]$OutDir = "dist"
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $repoRoot

# --- read version from manifest -------------------------------------------------
$manifestPath = Join-Path $repoRoot "custom_components\opcom_ro\manifest.json"
if (-not (Test-Path $manifestPath)) { throw "manifest.json not found: $manifestPath" }
$manifest = Get-Content -Raw -Encoding UTF8 $manifestPath | ConvertFrom-Json
$version = $manifest.version
$zipName = "opcom_ro-$version.zip"
$zipPath = Join-Path $repoRoot (Join-Path $OutDir $zipName)

Write-Host "Building release $zipName ..." -ForegroundColor Cyan

# --- clean previous output ------------------------------------------------------
if (Test-Path $zipPath) { Remove-Item $zipPath -Force }
$stage = Join-Path $repoRoot (Join-Path $OutDir "_stage")
if (Test-Path $stage) { Remove-Item $stage -Recurse -Force }
New-Item -ItemType Directory -Force -Path (Join-Path $repoRoot $OutDir) | Out-Null
New-Item -ItemType Directory -Force -Path $stage | Out-Null

# --- copy a folder tree, excluding __pycache__ and .pyc -------------------------
function Copy-Tree {
  param([string]$Src, [string]$Dst)
  if (-not (Test-Path $Src)) { throw "Source not found: $Src" }
  New-Item -ItemType Directory -Force -Path $Dst | Out-Null
  Get-ChildItem -Path $Src -Recurse -Force |
    Where-Object {
      $_.FullName -notmatch '\\__pycache__($|\\)' -and
      $_.Extension -ne '.pyc'
    } |
    ForEach-Object {
      $rel = $_.FullName.Substring($Src.Length + 1)
      $target = Join-Path $Dst $rel
      if ($_.PSIsContainer) {
        New-Item -ItemType Directory -Force -Path $target | Out-Null
      } else {
        Copy-Item $_.FullName -Destination $target -Force
      }
    }
}

# integration -> staging/custom_components/opcom_ro
Copy-Tree `
  (Join-Path $repoRoot "custom_components\opcom_ro") `
  (Join-Path $stage "custom_components\opcom_ro")

# root docs -> staging root
foreach ($doc in @("README.md", "LICENSE", "opcom-guide.html", "ghid-instalare.html")) {
  $src = Join-Path $repoRoot $doc
  if (Test-Path $src) {
    Copy-Item $src -Destination (Join-Path $stage $doc) -Force
  } else {
    Write-Warning "Optional doc missing, skipped: $doc"
  }
}

# --- zip (forward-slash entries, cross-platform safe) ---------------------------
# Compress-Archive writes backslash entry paths on Windows, which break
# extraction on Linux/macOS. Build the archive with .NET so we control the
# separators — Home Assistant users often unzip on Unix.
Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem
if (Test-Path $zipPath) { Remove-Item $zipPath -Force }
$zip = [System.IO.Compression.ZipFile]::Open($zipPath, [System.IO.Compression.ZipArchiveMode]::Create)
try {
  $files = Get-ChildItem -Path $stage -Recurse -File
  foreach ($f in $files) {
    $rel = $f.FullName.Substring($stage.Length + 1) -replace '\\', '/'
    $entry = $zip.CreateEntry($rel, [System.IO.Compression.CompressionLevel]::Optimal)
    $stream = $entry.Open()
    try {
      $bytes = [System.IO.File]::ReadAllBytes($f.FullName)
      $stream.Write($bytes, 0, $bytes.Length)
    } finally {
      $stream.Dispose()
    }
  }
} finally {
  $zip.Dispose()
}
Remove-Item $stage -Recurse -Force

# --- report ----------------------------------------------------------------------
$size = (Get-Item $zipPath).Length
$sizeKb = [math]::Round($size / 1KB, 1)
Write-Host ""
Write-Host "Created: $zipPath ($sizeKb KB)" -ForegroundColor Green
Write-Host "Contents:" -ForegroundColor DarkGray
$arc = [System.IO.Compression.ZipFile]::OpenRead($zipPath)
try {
  $arc.Entries | ForEach-Object { Write-Host ("  {0,-52} {1,8} bytes" -f $_.FullName, $_.Length) }
} finally {
  $arc.Dispose()
}
Write-Host ""
Write-Host "Done. Ship it." -ForegroundColor Cyan