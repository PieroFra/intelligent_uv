param(
    [string]$OutputDir = 'dist',
    [switch]$DryRun,
    [switch]$KeepStaging,
    # Edizione: 'completo' (default, comportamento storico), 'nativo' (solo
    # Blender-only, senza moduli RizomUV) o 'entrambi' (entrambi i pacchetti).
    [ValidateSet('completo', 'nativo', 'entrambi')]
    [string]$Edition = 'completo'
)

# Packaging di rilascio di Intelligent UV Mapping (fase ZIP della roadmap).
#
# Legge la versione da bl_info in __init__.py con un parsing testuale (nessun
# import, Blender non serve), mette in staging la sola struttura runtime
# intelligent_uv/ con __init__.py alla radice, e produce:
#   - intelligent_uv-<versione>.zip
#   - intelligent_uv-<versione>.sha256     (formato sha256sum)
#   - intelligent_uv-<versione>.files.txt  (file list confrontabile)
#
# -DryRun  fa tutto (staging + ZIP + hash + lista) in una cartella temporanea e
#          non scrive nulla in dist\; gli artefatti restano li' per ispezione.
# -KeepStaging  conserva la cartella di staging anche in un rilascio reale.
#
# Uscita attesa: righe "PACKAGE ...", "ZIP ...", "SHA256 ...", "FILELIST ...".
# Nessuna dipendenza esterna: solo .NET gia' presente in Windows PowerShell 5.1.

$ErrorActionPreference = 'Stop'

# Zona oraria fissa sugli entry dello ZIP: stesso contenuto -> stesso SHA-256.
$ZipEpoch = [DateTimeOffset]::new(2000, 1, 1, 0, 0, 0, [TimeSpan]::Zero)

# Solo runtime. Nessun file di sviluppo entra nel pacchetto.
$ExcludeDirs = @(
    '.git', '.opencode', '.github', '.idea', '.vscode',
    '__pycache__', '_esperimenti', 'dist', 'venv', '.venv', 'build', 'tests'
)
$ExcludeNames = @(
    'agents.md', 'opencode.json', 'roadmap.md', '.gitignore', '.gitattributes',
    'thumbs.db', 'desktop.ini'
)
# Pattern a wildcard sul nome file: script di debug temporanei non devono
# finire nel pacchetto (caso reale: tmp_inspect.py finito nello ZIP 0.36.0).
$ExcludePatterns = @('tmp_*.py')

$ExcludeExt = @(
    '.pyc', '.pyo', '.log', '.txt', '.ps1', '.png', '.jpg', '.jpeg', '.gif',
    '.blend', '.blend1', '.zip', '.rar', '.7z', '.tmp'
)

# Documentazione utente e attribuzione: le uniche non-.py che viaggiano.
$IncludeDocs = @('LICENSE', 'README.md', 'CHANGELOG.md', 'THIRD_PARTY.md')

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

function Get-BlInfoVersion {
    param([string]$InitPath)

    $text = [IO.File]::ReadAllText($InitPath)
    $pattern = '(?m)^\s*bl_info\s*=\s*\{[\s\S]*?"version"\s*:\s*\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)'
    $m = [regex]::Match($text, $pattern)
    if (-not $m.Success) {
        throw "bl_info.version non trovato in $InitPath (parsing testuale fallito)."
    }

    $parts = $m.Groups[1].Value, $m.Groups[2].Value, $m.Groups[3].Value
    [pscustomobject]@{
        Version = ($parts -join '.')
        Tuple   = '(' + ($parts -join ', ') + ')'
    }
}

function Get-ChangelogVersion {
    param([string]$ChangelogPath)

    if (-not (Test-Path -LiteralPath $ChangelogPath)) { return $null }
    $text = [IO.File]::ReadAllText($ChangelogPath)
    $m = [regex]::Match($text, '(?m)^##\s+(\d+\.\d+\.\d+)')
    if ($m.Success) { return $m.Groups[1].Value }
    return $null
}

function Test-ExcludedRelPath {
    param([string]$RelPath)

    $segments = $RelPath -split '[\\/]'

    for ($i = 0; $i -lt ($segments.Count - 1); $i++) {
        if ($ExcludeDirs -contains $segments[$i].ToLowerInvariant()) { return $true }
    }

    $leaf = $segments[$segments.Count - 1]
    if ($ExcludeNames -contains $leaf.ToLowerInvariant()) { return $true }

    foreach ($pat in $ExcludePatterns) {
        if ($leaf -like $pat) { return $true }
    }

    $ext = [IO.Path]::GetExtension($leaf).ToLowerInvariant()
    if ($ExcludeExt -contains $ext) { return $true }

    return $false
}

function Get-ProjectFiles {
    param([string]$Dir, [string]$RelBase = '')

    $out = @()
    foreach ($item in Get-ChildItem -LiteralPath $Dir -Force) {
        $rel = if ($RelBase) { "$RelBase/$($item.Name)" } else { $item.Name }
        if ($item.PSIsContainer) {
            if ($ExcludeDirs -contains $item.Name.ToLowerInvariant()) { continue }
            $out += Get-ProjectFiles -Dir $item.FullName -RelBase $rel
        }
        else {
            $out += [pscustomobject]@{
                Rel  = $rel
                Full = $item.FullName
                Name = $item.Name
            }
        }
    }
    $out
}

function Get-Sha256 {
    param([string]$Path)
    (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

# ---------------------------------------------------------------------------
# 1. Radice e versione
# ---------------------------------------------------------------------------

$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$initPath = Join-Path $root '__init__.py'

if (-not (Test-Path -LiteralPath $initPath)) { throw "Add-on non trovato: $initPath" }

$blInfo = Get-BlInfoVersion -InitPath $initPath
$version = $blInfo.Version

$missingDocs = @()
foreach ($doc in $IncludeDocs) {
    if (-not (Test-Path -LiteralPath (Join-Path $root $doc))) { $missingDocs += $doc }
}
if ($missingDocs.Count -gt 0) {
    throw ("Documenti richiesti assenti: " + ($missingDocs -join ', '))
}

$changelogVersion = Get-ChangelogVersion -ChangelogPath (Join-Path $root 'CHANGELOG.md')
if ($changelogVersion -and ($changelogVersion -ne $version)) {
    Write-Output ("AVVISO changelog {0} != bl_info {1}" -f $changelogVersion, $version)
}

# ---------------------------------------------------------------------------
# 2. Selezione dei file
# ---------------------------------------------------------------------------

$allFiles = Get-ProjectFiles -Dir $root

# Edizione nativa: moduli fisicamente esclusi dal pacchetto (ponti verso
# programmi esterni e launcher). Non basta nascondere la UI: i file .py non
# devono proprio esistere dentro lo ZIP.
$NativeExcludedModules = @('rizomuv_bridge.py', 'rizomuv_link.py', 'rizomuv_script.py')

function Select-PackageFiles {
    param([string]$ForEdition)

    $out = @()
    $out += @($allFiles | Where-Object {
        ($_.Name -like '*.py') -and (-not (Test-ExcludedRelPath $_.Rel))
    })
    $out += @($allFiles | Where-Object {
        ($_.Rel -notmatch '[\\/]') -and ($IncludeDocs -contains $_.Name)
    })
    if ($ForEdition -eq 'nativo') {
        $out = @($out | Where-Object { $NativeExcludedModules -notcontains $_.Name })
    }
    @($out | Sort-Object -Property Rel -CaseSensitive)
}

$editions = switch ($Edition) {
    'completo' { @('completo') }
    'nativo'   { @('nativo') }
    'entrambi' { @('completo', 'nativo') }
}

foreach ($edition in $editions) {

$selected = Select-PackageFiles -ForEdition $edition
if ($selected.Count -eq 0) { throw "Nessun file selezionato per l'edizione $edition." }

# Suffisso artefatti: nativo = -nativo, completo = nessun suffisso (nomi storici).
$suffix = if ($edition -eq 'nativo') { '-nativo' } else { '' }

# ---------------------------------------------------------------------------
# 3. Staging in intelligent_uv/
# ---------------------------------------------------------------------------

$stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$stagingRoot = Join-Path ([IO.Path]::GetTempPath()) ("opencode\iuv_pkg\{0}_{1}_{2}" -f $edition, $stamp, [guid]::NewGuid().ToString('N').Substring(0, 8))
$pkgDir = Join-Path $stagingRoot 'intelligent_uv'

try {
    New-Item -ItemType Directory -Path $pkgDir -Force | Out-Null

    foreach ($f in $selected) {
        $parts = $f.Rel -split '/'
        $destDir = $pkgDir
        for ($i = 0; $i -lt ($parts.Count - 1); $i++) {
            $destDir = Join-Path $destDir $parts[$i]
        }
        if (-not (Test-Path -LiteralPath $destDir)) {
            New-Item -ItemType Directory -Path $destDir -Force | Out-Null
        }
        Copy-Item -LiteralPath $f.Full -Destination (Join-Path $destDir $parts[$parts.Count - 1]) -Force
    }

    # Struttura: __init__.py alla radice del package, operators/ accanto.
    if (-not (Test-Path -LiteralPath (Join-Path $pkgDir '__init__.py'))) {
        throw 'Staging non valido: __init__.py non e alla radice di intelligent_uv/.'
    }
    if (-not (Test-Path -LiteralPath (Join-Path $pkgDir 'operators\__init__.py'))) {
        throw 'Staging non valido: operators\__init__.py assente.'
    }

    # Edizione nativa: pin del capability flag solo nell'artefatto. Il sorgente
    # del repo resta True; qui la copia in staging passa a False in modo che la
    # build nativa nasconda il motore esterno via flag, oltre che per assenza
    # fisica dei moduli RizomUV.
    $capPath = Join-Path $pkgDir 'capabilities.py'
    if ($edition -eq 'nativo') {
        if (-not (Test-Path -LiteralPath $capPath)) {
            throw 'NATIVO: capabilities.py assente nello staging.'
        }
        $capText = [IO.File]::ReadAllText($capPath)
        $capPattern = '(?m)^(\s*EXTERNAL_ENGINE_ENABLED\s*=\s*)True(\s*(?:#.*)?)$'
        if (-not [regex]::IsMatch($capText, $capPattern)) {
            throw 'NATIVO: riga "EXTERNAL_ENGINE_ENABLED = True" non trovata in capabilities.py.'
        }
        $capText = [regex]::Replace($capText, $capPattern, '${1}False${2}')
        $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
        [IO.File]::WriteAllText($capPath, $capText, $utf8NoBom)
    }

    $staged = @(Get-ChildItem -LiteralPath $pkgDir -Recurse -File | ForEach-Object {
        [pscustomobject]@{
            Rel  = $_.FullName.Substring($pkgDir.Length + 1).Replace('\', '/')
            Full = $_.FullName
        }
    } | Sort-Object -Property Rel -CaseSensitive)

    # Autoverifica esclusioni: nessun file di sviluppo puo' essere finito dentro.
    $leaks = @($staged | Where-Object { Test-ExcludedRelPath $_.Rel } | ForEach-Object { $_.Rel })
    if ($leaks.Count -gt 0) {
        throw ('Esclusione violata, file di sviluppo nello staging: ' + ($leaks -join ', '))
    }

    # Edizione nativa: i moduli RizomUV non devono esistere neppure nello staging.
    if ($edition -eq 'nativo') {
        $nativeLeaks = @($staged | Where-Object {
            $NativeExcludedModules -contains $_.Rel.Split('/')[-1].ToLowerInvariant()
        } | ForEach-Object { $_.Rel })
        if ($nativeLeaks.Count -gt 0) {
            throw ('NATIVO: moduli RizomUV presenti nello staging: ' + ($nativeLeaks -join ', '))
        }
    }

    # -----------------------------------------------------------------------
    # 4. File list
    # -----------------------------------------------------------------------

    $pyCount = @($staged | Where-Object { $_.Rel -like '*.py' }).Count
    $docCount = @($staged | Where-Object { $_.Rel -notmatch '[\\/]' -and $_.Rel -notlike '*.py' }).Count
    $zipName = "intelligent_uv-$version$suffix.zip"
    $listName = "intelligent_uv-$version$suffix.files.txt"

    $lines = New-Object System.Collections.Generic.List[string]
    $lines.Add("# intelligent_uv $version - release file list")
    $lines.Add("# bl_info.version $($blInfo.Tuple)")
    $lines.Add("# generated $((Get-Date).ToString('yyyy-MM-ddTHH:mm:ssK')) deterministic build")
    $lines.Add("# files $($staged.Count) (py $pyCount, docs $docCount)")
    $lines.Add("# columns: sha256  bytes  relative-path")

    foreach ($s in $staged) {
        $hash = Get-Sha256 -Path $s.Full
        $size = (Get-Item -LiteralPath $s.Full).Length
        $lines.Add(('{0}  {1}  {2}' -f $hash, $size, $s.Rel))
    }

    # -----------------------------------------------------------------------
    # 5. ZIP deterministico (ordine ordinale, timestamp fisso, slash in avanti)
    # -----------------------------------------------------------------------

    Add-Type -AssemblyName System.IO.Compression | Out-Null
    Add-Type -AssemblyName System.IO.Compression.FileSystem | Out-Null

    $targetDir = if ($DryRun) { $stagingRoot } else {
        if ([IO.Path]::IsPathRooted($OutputDir)) { $OutputDir } else { Join-Path $root $OutputDir }
    }
    if (-not (Test-Path -LiteralPath $targetDir)) {
        New-Item -ItemType Directory -Path $targetDir -Force | Out-Null
    }

    $zipPath = Join-Path $targetDir $zipName
    if (Test-Path -LiteralPath $zipPath) { Remove-Item -LiteralPath $zipPath -Force }

    $fs = [IO.File]::Open($zipPath, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write)
    try {
        $zip = [System.IO.Compression.ZipArchive]::new(
            $fs, [System.IO.Compression.ZipArchiveMode]::Create, $true, [System.Text.Encoding]::UTF8)
        try {
            foreach ($s in $staged) {
                $entry = $zip.CreateEntry(
                    ("intelligent_uv/" + $s.Rel), [System.IO.Compression.CompressionLevel]::Optimal)
                $entry.LastWriteTime = $ZipEpoch
                $outStream = $entry.Open()
                $inStream = [IO.File]::OpenRead($s.Full)
                try { $inStream.CopyTo($outStream) }
                finally { $inStream.Dispose(); $outStream.Dispose() }
            }
        }
        finally { $zip.Dispose() }
    }
    finally { $fs.Dispose() }

    # -----------------------------------------------------------------------
    # 6. Checksum e file list su disco
    # -----------------------------------------------------------------------

    $zipHash = Get-Sha256 -Path $zipPath
    $shaPath = Join-Path $targetDir ("intelligent_uv-$version$suffix.sha256")
    $listPath = Join-Path $targetDir $listName

    $utf8 = New-Object System.Text.UTF8Encoding($false)
    [IO.File]::WriteAllText($shaPath, ("{0}  {1}`n" -f $zipHash, $zipName), $utf8)
    [IO.File]::WriteAllLines($listPath, $lines.ToArray(), $utf8)

    # -----------------------------------------------------------------------
    # 7. Report
    # -----------------------------------------------------------------------

    Write-Output ("EDIZIONE {0}" -f $edition)
    Write-Output ("PACKAGE versione={0} file={1} py={2} docs={3}" -f $version, $staged.Count, $pyCount, $docCount)
    Write-Output ("ZIP {0}" -f $zipPath)
    Write-Output ("SHA256 {0}" -f $zipHash)
    Write-Output ("FILELIST {0}" -f $listPath)
    Write-Output ("CHECKSUM {0}" -f $shaPath)

    # Edizione nativa: verifica del contenuto dello ZIP. Riapre l'artefatto e
    # fallisce esplicitamente se uno dei moduli RizomUV compare tra le entry.
    if ($edition -eq 'nativo') {
        $readFs = [IO.File]::OpenRead($zipPath)
        try {
            $readZip = [System.IO.Compression.ZipArchive]::new(
                $readFs, [System.IO.Compression.ZipArchiveMode]::Read)
            try {
                $entries = @($readZip.Entries | ForEach-Object { $_.FullName })

                # VERIFY_NATIVE esteso: capabilities.py dentro lo ZIP deve
                # dichiarare EXTERNAL_ENGINE_ENABLED = False (non basta il flag
                # nello staging: si verifica l'artefatto, non il sorgente).
                $capEntry = $readZip.GetEntry('intelligent_uv/capabilities.py')
                if ($null -eq $capEntry) {
                    throw 'VERIFY_NATIVE FAIL: capabilities.py assente nello ZIP nativo.'
                }
                $capReader = New-Object IO.StreamReader($capEntry.Open(), [Text.Encoding]::UTF8)
                try { $capZipText = $capReader.ReadToEnd() }
                finally { $capReader.Dispose() }
                if ($capZipText -notmatch '(?m)^\s*EXTERNAL_ENGINE_ENABLED\s*=\s*False\s*$') {
                    throw 'VERIFY_NATIVE FAIL: capabilities.py nello ZIP nativo non ha EXTERNAL_ENGINE_ENABLED = False.'
                }
                if ($capZipText -match '(?m)^\s*EXTERNAL_ENGINE_ENABLED\s*=\s*True\s*$') {
                    throw 'VERIFY_NATIVE FAIL: capabilities.py nello ZIP nativo ha ancora EXTERNAL_ENGINE_ENABLED = True.'
                }
            }
            finally { $readZip.Dispose() }
        }
        finally { $readFs.Dispose() }

        $found = @($entries | Where-Object {
            $NativeExcludedModules -contains ([IO.Path]::GetFileName($_).ToLowerInvariant())
        })
        if ($found.Count -gt 0) {
            throw ('VERIFY_NATIVE FAIL: moduli RizomUV nello ZIP nativo: ' + ($found -join ', '))
        }
        Write-Output ("VERIFY_NATIVE OK zip={0} entries={1} esclusi={2} presenti=0 flag=False" -f `
            $zipName, $entries.Count, ($NativeExcludedModules -join ','))
    }

    Write-Output ("STAGING {0}" -f $stagingRoot)
    if ($DryRun) { Write-Output 'MODALITA dry-run: dist\ non e stato toccato.' }
}
finally {
    if ((-not $DryRun) -and (-not $KeepStaging) -and (Test-Path -LiteralPath $stagingRoot)) {
        Remove-Item -LiteralPath $stagingRoot -Recurse -Force
    }
}

} # fine ciclo edizioni

exit 0
