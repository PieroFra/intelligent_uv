$ErrorActionPreference = 'Stop'

# Costruisce e valida il pacchetto Blender Extension ufficiale di Intelligent UV Mapping.

$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$blender = "C:\Program Files\Blender Foundation\Blender 5.2\blender.exe"

if (-not (Test-Path -LiteralPath $blender)) {
    throw "Blender non trovato: $blender"
}

$stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$stage = Join-Path ([IO.Path]::GetTempPath()) ("opencode\iuv_ext\{0}_{1}" -f $stamp, [guid]::NewGuid().ToString('N').Substring(0, 8))

try {
    New-Item -ItemType Directory -Path $stage -Force | Out-Null
    New-Item -ItemType Directory -Path (Join-Path $stage 'operators') -Force | Out-Null

    # 31 file .py nella radice
    Get-ChildItem -LiteralPath $root -Filter '*.py' -File | ForEach-Object {
        Copy-Item -LiteralPath $_.FullName -Destination (Join-Path $stage $_.Name) -Force
    }

    # 10 file .py in operators\
    Get-ChildItem -LiteralPath (Join-Path $root 'operators') -Filter '*.py' -File | ForEach-Object {
        Copy-Item -LiteralPath $_.FullName -Destination (Join-Path $stage "operators\$($_.Name)") -Force
    }

    # Documentazione e manifest
    $extraFiles = @('LICENSE', 'README.md', 'CHANGELOG.md', 'THIRD_PARTY.md', 'blender_manifest.toml')
    foreach ($f in $extraFiles) {
        $src = Join-Path $root $f
        if (-not (Test-Path -LiteralPath $src)) {
            throw "File richiesto assente: $src"
        }
        Copy-Item -LiteralPath $src -Destination (Join-Path $stage $f) -Force
    }

    $pyCount = @(Get-ChildItem -LiteralPath $stage -Recurse -Filter '*.py' -File).Count
    if ($pyCount -ne 41) {
        throw "Conteggio file .py inatteso nello staging: $pyCount (attesi 41)"
    }

    $distDir = Join-Path $root 'dist'
    if (-not (Test-Path -LiteralPath $distDir)) {
        New-Item -ItemType Directory -Path $distDir -Force | Out-Null
    }

    $outZip = Join-Path $distDir 'intelligent_uv-0.35.1-extension.zip'
    if (Test-Path -LiteralPath $outZip) {
        Remove-Item -LiteralPath $outZip -Force
    }

    & $blender --background --factory-startup --command extension build --source-dir $stage --output-filepath $outZip
    if ($LASTEXITCODE -ne 0) {
        throw "extension build fallito con exit code $LASTEXITCODE"
    }

    & $blender --background --factory-startup --command extension validate $outZip
    if ($LASTEXITCODE -ne 0) {
        throw "extension validate fallito con exit code $LASTEXITCODE"
    }

    $sha = (Get-FileHash -LiteralPath $outZip -Algorithm SHA256).Hash.ToLowerInvariant()
    Write-Output "EXTENSION_OK | zip=$outZip | sha256=$sha | py=$pyCount"
}
finally {
    if (Test-Path -LiteralPath $stage) {
        Remove-Item -LiteralPath $stage -Recurse -Force
    }
}
