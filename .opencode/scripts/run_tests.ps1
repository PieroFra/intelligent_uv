param(
    [string]$Blender = 'C:\Program Files\Blender Foundation\Blender 5.2\blender.exe',
    # Lista di suite separate da virgola (es. -Suites "test_native_uv_baseline.py").
    # Nomi senza percorso vengono risolti in tests\; vuoto = smoke test di default.
    [string]$Suites = ''
)

# Test headless di Intelligent UV Mapping.
# Scrive il log in .opencode\tests\test_out.txt e termina con RISULTATO passati=X falliti=Y.

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$testsDir = Join-Path $root 'tests'
$out = Join-Path $root '.opencode\tests\test_out.txt'

if (-not (Test-Path $Blender)) { throw "Blender non trovato: $Blender" }

if ($Suites) {
    $tests = $Suites -split ',' | ForEach-Object {
        $name = $_.Trim()
        if (-not $name) { throw "Nome suite vuoto in -Suites: '$Suites'" }
        $p = if ([IO.Path]::IsPathRooted($name) -or ($name -like '*\*') -or ($name -like '*/*')) {
            Join-Path $root $name
        } else {
            Join-Path $testsDir $name
        }
        if (-not (Test-Path $p)) { throw "Suite non trovata: $p" }
        $p
    }
} else {
    $tests = @(Join-Path $root '.opencode\tests\smoke_test.py')
}

# Blender scrive su stderr anche quando va tutto bene: con ErrorActionPreference=Stop
# PowerShell trasformerebbe quel rumore in un errore fatale.
$ErrorActionPreference = 'Continue'
$sw = [Diagnostics.Stopwatch]::StartNew()
$lines = foreach ($t in $tests) {
    & $Blender --factory-startup --background --python $t 2>&1 |
        ForEach-Object { $_.ToString() }
}
$sw.Stop()
$ErrorActionPreference = 'Stop'

$utf8 = New-Object System.Text.UTF8Encoding($false)
[IO.File]::WriteAllLines($out, $lines, $utf8)

$results = @($lines | Where-Object { $_ -match '^RISULTATO ' })
$failures = $lines | Where-Object { $_ -match '^CHECK .* FAIL ' }

if ($failures) { $failures | ForEach-Object { Write-Output $_ } }

if ($results.Count -eq 0) {
    Write-Output 'RISULTATO assente: la suite non e arrivata in fondo.'
    $lines | Select-Object -Last 15 | ForEach-Object { Write-Output $_ }
    exit 1
}

if ($results.Count -ne $tests.Count) {
    Write-Output ("ATTESO: {0} righe RISULTATO, trovate {1}: qualche suite non e arrivata in fondo." -f $tests.Count, $results.Count)
    $lines | Select-Object -Last 15 | ForEach-Object { Write-Output $_ }
    exit 1
}

if ($results.Count -gt 1) { $results | ForEach-Object { Write-Output $_ } }

$totPassed = 0; $totFailed = 0; $totAll = 0
foreach ($r in $results) {
    if ($r -match 'passati=(\d+)\s+falliti=(\d+)\s+totale=(\d+)') {
        $totPassed += [int]$Matches[1]; $totFailed += [int]$Matches[2]; $totAll += [int]$Matches[3]
    } else {
        # Una riga RISULTATO malformata non si aggrega a zero: fallisce esplicitamente.
        Write-Output ("RISULTATO malformato, aggregazione annullata: {0}" -f $r)
        exit 1
    }
}
$result = "RISULTATO passati=$totPassed falliti=$totFailed totale=$totAll"
Write-Output ("tempo: {0:N1} s" -f $sw.Elapsed.TotalSeconds)
Write-Output ("log: {0}" -f $out)
Write-Output $result

if ($result -notmatch 'falliti=0') { exit 1 }
exit 0
