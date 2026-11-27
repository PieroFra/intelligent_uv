$ErrorActionPreference = 'Stop'

# Build della Blender Extension "edizione nativa" (solo Blender, motore esterno
# disattivato e moduli RizomUV fisicamente assenti). Riutilizza package_release.ps1
# per lo staging con -Edition nativo (capabilities.py gia' pinnato a False), poi
# ricompone l'albero in layout extension (manifest alla radice) e chiama
# `blender --command extension build` + validate.
#
# Non sovrascrive gli artefatti GitHub (intelligent_uv-0.36.0.zip/.sha256/.files.txt):
# l'output e' dist\intelligent_uv-0.36.0-nativo-extension.zip + .sha256.

$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$blender = "C:\Program Files\Blender Foundation\Blender 5.2\blender.exe"
if (-not (Test-Path -LiteralPath $blender)) { throw "Blender non trovato: $blender" }

# Versione letta dal manifest del repo (fonte unica, niente cablaggio).
$manRaw = Get-Content -LiteralPath (Join-Path $root 'blender_manifest.toml') -Raw
if ($manRaw -notmatch '(?m)^version\s*=\s*"(\d+\.\d+\.\d+)"') { throw 'Versione non trovata in blender_manifest.toml.' }
$version = $Matches[1]
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
    # L'edizione per Blender Extensions contiene solo il runtime: nessun test.
    if (Test-Path -LiteralPath (Join-Path $stage 'tests')) {
        Remove-Item -LiteralPath (Join-Path $stage 'tests') -Recurse -Force
    }
    if (Test-Path -LiteralPath (Join-Path $stage 'tests')) { throw 'NATIVO: la cartella tests e presente nello staging extension.' }
    # Il manifest dell'edizione nativa e' riscritto a partire da quello del repo:
    # tolta solo la chiave network (RizomUV e' assente), resta [permissions] files;
    # tagline senza riferimento al motore esterno. Il manifest del repo resta invariato.
    $manifestSrc = Get-Content -LiteralPath (Join-Path $root 'blender_manifest.toml') -Raw
    $manifestNative = $manifestSrc -replace '(?m)^tagline[^\r\n]*\r?$',
        'tagline = "Curvature and shape-clustering UV unwrapping, Blender-only"'
    if ($manifestNative -notmatch 'Blender-only"') {
        throw 'Tagline nativa non applicata al manifest di staging.'
    }
    $manifestNative = $manifestNative -replace '(?m)^network\s*=\s*"[^"]*"\r?\n?', ''
    $manifestNative = $manifestNative.TrimEnd() + "`r`n"
    if ($manifestNative -match 'RizomUV' -or $manifestNative -match '(?m)^network\s*=') {
        throw 'NATIVO: il manifest riscritto contiene ancora network o riferimenti a RizomUV.'
    }
    [IO.File]::WriteAllText((Join-Path $stage 'blender_manifest.toml'), $manifestNative,
        (New-Object System.Text.UTF8Encoding($false)))

    # 2b. Pulizia completa di ogni residuo RizomUV / ExternalEngine nello staging nativo
    #     (requisito Blender Extensions: nessun EXE picker, nessun ExternalEngine, nessun import
    #     a rizomuv_bridge / rizomuv_link / rizomuv_script). Il sorgente del repo resta intatto.
    $extOp = Join-Path $stage 'operators\external.py'
    if (Test-Path -LiteralPath $extOp) { Remove-Item -LiteralPath $extOp -Force }

    # operators/run.py: rimuove import e base class ExternalEngineMixin, stub _start_external -> None
    $runPath = Join-Path $stage 'operators\run.py'
    $runTxt = [IO.File]::ReadAllText($runPath)
    $runTxt = $runTxt -replace '(?m)^from \.external import ExternalEngineMixin\r?\n', ''
    $runTxt = $runTxt -replace '(?m)^\s*ExternalEngineMixin,\r?\n', ''
    $runTxt = $runTxt -replace '(?m)^(\s*# Modal state for the external engine\r?\n)', "    def _start_external(self, context, state, already_modal=False):`r`n        return None`r`n`r`n`$1"
    [IO.File]::WriteAllText($runPath, $runTxt, (New-Object System.Text.UTF8Encoding($false)))

    # manual_io.py: rimosso completamente (usa subprocess e apre il programma
    # esterno). Gli operatori Export/Import FBX non esistono nell'edizione
    # nativa: le referenze in __init__.py e ui.py sono rimosse qui sotto, quindi
    # l'import del modulo non puo' piu' sollevare ImportError.
    $mioStage = Join-Path $stage 'manual_io.py'
    if (Test-Path -LiteralPath $mioStage) { Remove-Item -LiteralPath $mioStage -Force }

    # properties.py: rimuove proprieta' RizomUV (incluso rizomuv_path EXE picker)
    $propPath = Join-Path $stage 'properties.py'
    $propTxt = [IO.File]::ReadAllText($propPath)
    $propTxt = $propTxt -replace '(?s)\r?\n    use_rizomuv: bpy\.props\.BoolProperty\(.*?\r?\n    \)', ''
    $propTxt = $propTxt -replace '(?s)\r?\n    rizomuv_engine_mode: bpy\.props\.EnumProperty\(.*?\r?\n    \)', ''
    $propTxt = $propTxt -replace '(?s)\r?\n    link_optimize: bpy\.props\.BoolProperty\(.*?\r?\n    \)', ''
    $propTxt = $propTxt -replace '(?s)\r?\n    link_keep_open: bpy\.props\.BoolProperty\(.*?\r?\n    \)', ''
    $propTxt = $propTxt -replace '(?s)\r?\n    rizomuv_path: bpy\.props\.StringProperty\(.*?\r?\n    \)', ''
    $propTxt = $propTxt -replace '(?s)\r?\n    rizomuv_args: bpy\.props\.StringProperty\(.*?\r?\n    \)', ''
    $propTxt = $propTxt -replace '(?s)\r?\n    rizomuv_timeout: bpy\.props\.IntProperty\(.*?\r?\n    \)', ''
    $propTxt = $propTxt -replace '(?s)\r?\n    keep_temp_files: bpy\.props\.BoolProperty\(.*?\r?\n    \)', ''
    [IO.File]::WriteAllText($propPath, $propTxt, (New-Object System.Text.UTF8Encoding($false)))

    # ui.py: rimuove box External Editor (rizomuv_path), blocco use_rizomuv /
    # rizomuv_link, le tre righe guida RizomUV e l'import di manual_io (modulo
    # rimosso). Gli usi degli operatori Export/Import FBX stanno tutti dentro
    # il box External Editor, rimosso qui sotto.
    $uiPath = Join-Path $stage 'ui.py'
    $uiTxt = [IO.File]::ReadAllText($uiPath)
    $uiTxt = $uiTxt -replace '(?s)\r?\n        # RizomUV round trip: export, work by hand, import\..*?icon=''FILEBROWSER'',\r?\n        \)', ''
    $uiTxt = $uiTxt -replace '(?s)\r?\n        col\.separator\(\)\r?\n        col\.prop\(settings, "use_rizomuv"\).*$', "`r`n"
    $uiTxt = $uiTxt -replace '(?s)\r?\n    "RizomUV Auto - batch hand-off, waits for the islands to come back\.",\r?\n    "RizomUV Live Link - keeps the session open and syncs both ways\.",\r?\n    "RizomUV Lua Script - drives RizomUV headless, no GUI needed\.",', ''
    $uiTxt = $uiTxt -replace '(?s)\r?\nfrom \.manual_io import \(.*?\r?\n\)\r?\n', "`r`n"
    if ($uiTxt -match 'rizom|manual_io') { throw 'NATIVO: ui.py contiene ancora riferimenti a RizomUV o manual_io.' }
    [IO.File]::WriteAllText($uiPath, $uiTxt, (New-Object System.Text.UTF8Encoding($false)))

    # Commenti e docstring con riferimenti RizomUV nei moduli runtime.
    $marPath = Join-Path $stage 'margins.py'
    $marTxt = [IO.File]::ReadAllText($marPath)
    $marTxt = $marTxt -replace '(?m)^\s*- RizomUV MarginPX / SpacingPX \(pixels\)\r?\n', ''
    [IO.File]::WriteAllText($marPath, $marTxt, (New-Object System.Text.UTF8Encoding($false)))

    $prePath = Join-Path $stage 'presets.py'
    $preTxt = [IO.File]::ReadAllText($prePath)
    $preTxt = $preTxt -replace 'presets should not be able to set the RizomUV executable\r?\n# path or the temp-file debug flags\.', 'presets cannot set the temp-file debug flags.'
    [IO.File]::WriteAllText($prePath, $preTxt, (New-Object System.Text.UTF8Encoding($false)))

    $propPath = Join-Path $stage 'properties.py'
    $propTxt = [IO.File]::ReadAllText($propPath)
    $propTxt = $propTxt -replace ' \(shared by native engine and RizomUV\)', ' (shared by the native engine)'
    $propTxt = $propTxt -replace '(?m)^\s*# RizomUV Engine Settings\r?\n', ''
    [IO.File]::WriteAllText($propPath, $propTxt, (New-Object System.Text.UTF8Encoding($false)))

    $baseOpPath = Join-Path $stage 'operators\base.py'
    $baseOpTxt = [IO.File]::ReadAllText($baseOpPath)
    $baseOpTxt = $baseOpTxt -replace 'downstream \(RizomUV reports them as\r?\n        # BijectionFailedIslandIDs and keeps the pre-computed UVs\), so warn', 'downstream, so warn'
    [IO.File]::WriteAllText($baseOpPath, $baseOpTxt, (New-Object System.Text.UTF8Encoding($false)))

    $natOpPath = Join-Path $stage 'operators\native.py'
    $natOpTxt = [IO.File]::ReadAllText($natOpPath)
    $natOpTxt = $natOpTxt -replace '# Region ids are per-face and survive the RizomUV round trip, so the\r?\n        # planner partition is a valid hint regardless of the native flag\. The', '# Region ids are per-face, so the planner partition is a valid hint. The'
    [IO.File]::WriteAllText($natOpPath, $natOpTxt, (New-Object System.Text.UTF8Encoding($false)))

    # __init__.py: docstring senza il ponte esterno, nessun import di manual_io
    # (modulo rimosso) e CLASSES senza MANUAL_IO_CLASSES.
    $initPath = Join-Path $stage '__init__.py'
    $initTxt = [IO.File]::ReadAllText($initPath)
    $initTxt = $initTxt -replace 'texel density normalization and an optional RizomUV bridge\.', 'texel density normalization.'
    $initTxt = $initTxt -replace '(?m)^.*rizomuv_bridge.*\r?\n', ''
    $initTxt = $initTxt -replace '(?m)^from \.manual_io import MANUAL_IO_CLASSES\r?\n', ''
    $initTxt = $initTxt -replace ' \+ MANUAL_IO_CLASSES', ''
    if ($initTxt -match 'manual_io') { throw 'NATIVO: __init__.py referenzia ancora manual_io.' }
    [IO.File]::WriteAllText($initPath, $initTxt, (New-Object System.Text.UTF8Encoding($false)))

    # Autoverifica del layout nativo nello staging.
    $excluded = @('rizomuv_bridge.py', 'rizomuv_link.py', 'rizomuv_script.py', 'external.py', 'manual_io.py')
    foreach ($m in $excluded) {
        if (Test-Path -LiteralPath (Join-Path $stage $m)) { throw "NATIVO: $m presente nello staging extension." }
    }
    $capText = [IO.File]::ReadAllText((Join-Path $stage 'capabilities.py'))
    if ($capText -notmatch '(?m)^\s*EXTERNAL_ENGINE_ENABLED\s*=\s*False\s*$') {
        throw 'NATIVO: capabilities.py nello staging non ha EXTERNAL_ENGINE_ENABLED = False.'
    }

    # 3. Build + validate via CLI Extensions di Blender.
    New-Item -ItemType Directory -Path (Split-Path -Parent $outZip) -Force | Out-Null
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
        $testsLeaks = @($names | Where-Object { $_ -match '(?i)(^|/)tests/' })
        if ($testsLeaks.Count -gt 0) { throw 'tests/ nello ZIP: ' + ($testsLeaks -join ', ') }
        $leaks = @($names | Where-Object { $excluded -contains [IO.Path]::GetFileName($_) })
        if ($leaks.Count -gt 0) { throw 'RizomUV nello ZIP: ' + ($leaks -join ', ') }
        $capEntry = $zip.GetEntry('capabilities.py')
        $reader = New-Object IO.StreamReader($capEntry.Open(), [Text.Encoding]::UTF8)
        try { $capZip = $reader.ReadToEnd() } finally { $reader.Dispose() }
        if ($capZip -notmatch '(?m)^\s*EXTERNAL_ENGINE_ENABLED\s*=\s*False\s*$') {
            throw 'capabilities.py nello ZIP non ha EXTERNAL_ENGINE_ENABLED = False.'
        }
        $manEntry = $zip.GetEntry('blender_manifest.toml')
        $reader2 = New-Object IO.StreamReader($manEntry.Open(), [Text.Encoding]::UTF8)
        try { $manZip = $reader2.ReadToEnd() } finally { $reader2.Dispose() }
        if ($manZip -match 'RizomUV' -or $manZip -match '(?m)^network\s*=') {
            throw 'Manifest nello ZIP contiene network o riferimenti a RizomUV.'
        }
        if ($manZip -notmatch '(?m)^files = "Save presets and export or import FBX files for UV editing"\r?$') {
            throw 'Manifest nello ZIP: permission files mancante.'
        }
        if ($manZip -notmatch 'Curvature and shape-clustering UV unwrapping, Blender-only') {
            # Diagnostica: senza il contenuto reale non si distingue riscrittura
            # del manifest da differenze di quoting tra versioni di Blender.
            $head = $manZip.Substring(0, [Math]::Min(800, $manZip.Length))
            Write-Output "MANIFEST_ZIP_HEAD: $head"
            throw 'Manifest nello ZIP: tagline nativa mancante.'
        }
        if ($manZip -notmatch ('(?m)^version = "' + [regex]::Escape($version) + '"')) {
            throw "Manifest nello ZIP: versione non $version."
        }
        # Audit forense su TUTTI i .py e .toml nello ZIP: zero occorrenze dei
        # pattern del reviewer (RizomUV, subprocess, editor esterno, exe picker,
        # API di lancio manuale). Qualsiasi hit boccia la build.
        $forbiddenPattern = 'rizom|subprocess|external editor|\.exe\b|open_in_rizom|use_rizom'
        $badHits = @()
        foreach ($e in $zip.Entries) {
            if ($e.FullName -notlike '*.py' -and $e.FullName -notlike '*.toml') { continue }
            $sr = New-Object IO.StreamReader($e.Open(), [Text.Encoding]::UTF8)
            try { $pyContent = $sr.ReadToEnd() } finally { $sr.Dispose() }
            if ($pyContent -match $forbiddenPattern) {
                $badHits += "$($e.FullName): matched '$($Matches[0])'"
            }
        }
        if ($badHits.Count -gt 0) {
            throw ('NATIVO AUDIT FAIL — residui RizomUV/ExternalEngine nello ZIP: ' + ($badHits -join '; '))
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
