param(
    [string]$Blender = 'C:\Program Files\Blender Foundation\Blender 5.2\blender.exe'
)

# Smoke test headless di Intelligent UV Mapping.
# Scrive il log in .opencode\tests\test_out.txt e termina con RISULTATO passati=X falliti=Y.

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$test = Join-Path $root '.opencode\tests\smoke_test.py'
$out = Join-Path $root '.opencode\tests\test_out.txt'

if (-not (Test-Path $Blender)) { throw "Blender non trovato: $Blender" }
if (-not (Test-Path $test)) { throw "Smoke test non trovato: $test" }

# Blender scrive su stderr anche quando va tutto bene: con ErrorActionPreference=Stop
# PowerShell trasformerebbe quel rumore in un errore fatale.
$ErrorActionPreference = 'Continue'
$sw = [Diagnostics.Stopwatch]::StartNew()
$lines = & $Blender --factory-startup --background --python $test 2>&1 |
    ForEach-Object { $_.ToString() }
$sw.Stop()
$ErrorActionPreference = 'Stop'

$utf8 = New-Object System.Text.UTF8Encoding($false)
[IO.File]::WriteAllLines($out, $lines, $utf8)

$result = $lines | Where-Object { $_ -match '^RISULTATO ' } | Select-Object -Last 1
$failures = $lines | Where-Object { $_ -match '^CHECK .* FAIL ' }

if ($failures) { $failures | ForEach-Object { Write-Output $_ } }

if (-not $result) {
    Write-Output 'RISULTATO assente: lo smoke test non e arrivato in fondo.'
    $lines | Select-Object -Last 15 | ForEach-Object { Write-Output $_ }
    exit 1
}

Write-Output $result
Write-Output ("tempo: {0:N1} s" -f $sw.Elapsed.TotalSeconds)
Write-Output ("log: {0}" -f $out)

if ($result -notmatch 'falliti=0') { exit 1 }
exit 0
