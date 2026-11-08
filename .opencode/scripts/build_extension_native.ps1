$ErrorActionPreference = 'Stop'

# Build della Blender Extension "edizione nativa" (solo Blender, motore esterno
# disattivato e moduli RizomUV fisicamente assenti). Riutilizza package_release.ps1
# per lo staging con -Edition nativo (capabilities.py gia' pinnato a False), poi
# ricompone l'albero in layout extension (manifest alla radice) e chiama
# `blender --command extension build` + validate.
#
# Non sovrascrive gli artefatti GitHub (intelligent_uv-0.35.1.zip/.sha256/.files.txt):
# l'output e' dist\intelligent_uv-0.35.1-nativo-extension.zip + .sha256.

$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$blender = "C:\Program Files\Blender Foundation\Blender 5.2\blender.exe"
if (-not (Test-Path -LiteralPath $blender)) { throw "Blender non trovato: $blender" }

$version = '0.36.0'
$outZip = Join-Path $root "dist\intelligent_uv-$version-nativo-extension.zip"
$outSha = Join-Path $root "dist\intelligent_uv-$version-nativo-extension.sha256"

$stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$work = Join-Path ([IO.Path]::GetTempPath()) "opencode\iuv_ext_native\$stamp"
New-Item -ItemType Directory -Path $work -Force | Out-Null
$pkgOut = Join-Path $work 'pkgout'
$stage = Join-Path $work 'stage'

try {
    # 1. Staging nativo riusato da package_release.ps1 (non tocca dist\ di GitHub).
    $pr = & (Join-Path $PSScriptRoot 'package_release.ps1') -Edition nativo -OutputDir $pkgOut -KeepStaging
    $pr | ForEach-Object { Write-Output $_ }
    $staging = ($pr | Where-Object { $_ -like 'STAGING *' }) -replace '^STAGING ', ''
    if (-not $staging -or -not (Test-Path -LiteralPath $staging)) {
        throw "Staging nativo non individuato: '$staging'"
    }

    # 2. Ricomposizione in layout extension: __init__.py e i moduli alla radice.
    New-Item -ItemType Directory -Path $stage -Force | Out-Null
    Copy-Item (Join-Path $staging 'intelligent_uv\*') -Destination $stage -Recurse -Force
    Copy-Item -LiteralPath (Join-Path $root 'blender_manifest.toml') -Destination (Join-Path $stage 'blender_manifest.toml') -Force

    # Autoverifica del layout nativo nello staging.
    $excluded = @('rizomuv_bridge.py', 'rizomuv_link.py', 'rizomuv_script.py')
    foreach ($m in $excluded) {
        if (Test-Path -LiteralPath (Join-Path $stage $m)) { throw "NATIVO: $m presente nello staging extension." }
    }
    $capText = [IO.File]::ReadAllText((Join-Path $stage 'capabilities.py'))
    if ($capText -notmatch '(?m)^\s*EXTERNAL_ENGINE_ENABLED\s*=\s*False\s*$') {
        throw 'NATIVO: capabilities.py nello staging non ha EXTERNAL_ENGINE_ENABLED = False.'
    }

    # 3. Build + validate via CLI Extensions di Blender.
    & $blender --background --factory-startup --command extension build --source-dir $stage --output-filepath $outZip
    if ($LASTEXITCODE -ne 0) { throw "extension build fallito ($LASTEXITCODE)" }
    & $blender --background --factory-startup --command extension validate $outZip
    if ($LASTEXITCODE -ne 0) { throw "extension validate fallito ($LASTEXITCODE)" }

    # 4. Verifica dell'artefatto: manifest alla radice, zero moduli RizomUV,
    #    capabilities.py pinnato a False.
    Add-Type -AssemblyName System.IO.Compression.FileSystem | Out-Null
    $zip = [System.IO.Compression.ZipFile]::OpenRead($outZip)
    try {
        $names = @($zip.Entries.FullName)
        if ($names -notcontains 'blender_manifest.toml') {
            throw 'Artefatto non valido: blender_manifest.toml non alla radice.'
        }
        if ($names -notcontains '__init__.py') { throw 'Artefatto non valido: __init__.py non alla radice.' }
        $leaks = @($names | Where-Object { $excluded -contains [IO.Path]::GetFileName($_) })
        if ($leaks.Count -gt 0) { throw 'RizomUV nello ZIP: ' + ($leaks -join ', ') }
        $capEntry = $zip.GetEntry('capabilities.py')
        $reader = New-Object IO.StreamReader($capEntry.Open(), [Text.Encoding]::UTF8)
        try { $capZip = $reader.ReadToEnd() } finally { $reader.Dispose() }
        if ($capZip -notmatch '(?m)^\s*EXTERNAL_ENGINE_ENABLED\s*=\s*False\s*$') {
            throw 'capabilities.py nello ZIP non ha EXTERNAL_ENGINE_ENABLED = False.'
        }
        $entryCount = $names.Count
    }
    finally { $zip.Dispose() }

    $sha = (Get-FileHash -LiteralPath $outZip -Algorithm SHA256).Hash.ToLowerInvariant()
    [IO.File]::WriteAllText($outSha, ("{0}  {1}`n" -f $sha, [IO.Path]::GetFileName($outZip)),
        (New-Object System.Text.UTF8Encoding($false)))

    Write-Output ("EXTENSION_NATIVE_OK | zip={0} | sha256={1} | entries={2}" -f $outZip, $sha, $entryCount)
}
finally {
    if (Test-Path -LiteralPath $work) { Remove-Item -LiteralPath $work -Recurse -Force }
}

exit 0
