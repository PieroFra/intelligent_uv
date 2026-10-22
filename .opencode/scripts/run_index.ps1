param(
    [string]$Out = (Join-Path $env:TEMP 'opencode\iuv_map.txt'),
    [string]$Filter = ''
)

# Mappa dei simboli di Intelligent UV Mapping.
# Usa il Python interno a Blender: `python` nel PATH e' la stub del Microsoft Store.

$ErrorActionPreference = 'Stop'
$blender = 'C:\Program Files\Blender Foundation\Blender 5.2\blender.exe'
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$script = Join-Path $root '.opencode\scripts\index_addon.py'

if (-not (Test-Path $blender)) { throw "Blender non trovato: $blender" }
if (-not (Test-Path $script)) { throw "Script non trovato: $script" }

New-Item -ItemType Directory -Force (Split-Path -Parent $Out) | Out-Null

$blenderArgs = @('--factory-startup', '--background', '--python', $script, '--', '--out', $Out)
if ($Filter) { $blenderArgs += @('--filter', $Filter) }

$lines = & $blender @blenderArgs 2>&1 | ForEach-Object { $_.ToString() }
$line = $lines | Where-Object { $_ -match '^INDEX_OUT ' } | Select-Object -Last 1
if (-not $line) {
    $lines | Select-Object -Last 15
    throw 'La mappa non e stata generata.'
}
Write-Output $line
