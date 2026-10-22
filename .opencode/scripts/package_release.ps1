param(
    [string]$OutputDir = 'dist',
    [switch]$DryRun,
    [switch]$KeepStaging
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
    '__pycache__', '_esperimenti', 'dist', 'venv', '.venv', 'build'
)
$ExcludeNames = @(
    'agents.md', 'opencode.json', 'roadmap.md', '.gitignore', '.gitattributes',
    'thumbs.db', 'desktop.ini'
)
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

$selected = @()
$selected += @($allFiles | Where-Object {
    ($_.Name -like '*.py') -and (-not (Test-ExcludedRelPath $_.Rel))
})
$selected += @($allFiles | Where-Object {
    ($_.Rel -notmatch '[\\/]') -and ($IncludeDocs -contains $_.Name)
})
$selected = @($selected | Sort-Object -Property Rel -CaseSensitive)

if ($selected.Count -eq 0) { throw 'Nessun file selezionato: il packaging non ha nulla da impacchettare.' }

# ---------------------------------------------------------------------------
# 3. Staging in intelligent_uv/
# ---------------------------------------------------------------------------

$stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$stagingRoot = Join-Path ([IO.Path]::GetTempPath()) ("opencode\iuv_pkg\{0}_{1}" -f $stamp, [guid]::NewGuid().ToString('N').Substring(0, 8))
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

    # -----------------------------------------------------------------------
    # 4. File list
    # -----------------------------------------------------------------------

    $pyCount = @($staged | Where-Object { $_.Rel -like '*.py' }).Count
    $docCount = @($staged | Where-Object { $_.Rel -notmatch '[\\/]' -and $_.Rel -notlike '*.py' }).Count
    $zipName = "intelligent_uv-$version.zip"
    $listName = "intelligent_uv-$version.files.txt"

    $lines = New-Object System.Collections.Generic.List[string]
    $lines.Add("# intelligent_uv $version - release file list")
    $lines.Add("# bl_info.version $($blInfo.Tuple)")
    $lines.Add("# generated $((Get-Date).ToString('yyyy-MM-ddTHH:mm:ssK')) on $env:COMPUTERNAME")
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
    $shaPath = Join-Path $targetDir ("intelligent_uv-$version.sha256")
    $listPath = Join-Path $targetDir $listName

    $utf8 = New-Object System.Text.UTF8Encoding($false)
    [IO.File]::WriteAllText($shaPath, ("{0}  {1}`n" -f $zipHash, $zipName), $utf8)
    [IO.File]::WriteAllLines($listPath, $lines.ToArray(), $utf8)

    # -----------------------------------------------------------------------
    # 7. Report
    # -----------------------------------------------------------------------

    Write-Output ("PACKAGE versione={0} file={1} py={2} docs={3}" -f $version, $staged.Count, $pyCount, $docCount)
    Write-Output ("ZIP {0}" -f $zipPath)
    Write-Output ("SHA256 {0}" -f $zipHash)
    Write-Output ("FILELIST {0}" -f $listPath)
    Write-Output ("CHECKSUM {0}" -f $shaPath)
    Write-Output ("STAGING {0}" -f $stagingRoot)
    if ($DryRun) { Write-Output 'MODALITA dry-run: dist\ non e stato toccato.' }
}
finally {
    if ((-not $DryRun) -and (-not $KeepStaging) -and (Test-Path -LiteralPath $stagingRoot)) {
        Remove-Item -LiteralPath $stagingRoot -Recurse -Force
    }
}

exit 0
