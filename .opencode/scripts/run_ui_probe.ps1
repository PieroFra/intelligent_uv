param([int]$Port = 9879)

# Verifica UI di Intelligent UV Mapping in un colpo solo:
#   1. avvia Blender in modalita' GUI col ponte TCP (dietro le altre finestre);
#   2. esegue iuv_ui_probe.py dentro Blender;
#   3. chiude il ponte (solo il PID avviato qui).
#
# Output: report UI_TEXT/UI_SUMMARY + 2 PNG ritagliati in
# %TEMP%\opencode\iuv_gui\ : iuv-ui-it.png e iuv-ui-en.png (max 1024 px).

$ErrorActionPreference = 'Stop'
$env:BLENDER_BRIDGE_PORT = "$Port"
$env:PYTHONIOENCODING = 'utf-8'

$blender = 'C:\Program Files\Blender Foundation\Blender 5.2\blender.exe'
$py = 'C:\Program Files\Blender Foundation\Blender 5.2\5.2\python\bin\python.exe'

if (-not (Test-Path $blender)) { throw "Blender non trovato: $blender" }

# Radice del progetto: la cartella che contiene ui.py (risalendo da .opencode\scripts).
$root = $null
$base = $PSScriptRoot
for ($i = 0; $i -lt 4; $i++) {
    $candidate = Split-Path -Parent $base
    if (-not $candidate) { break }
    if ((Test-Path (Join-Path $candidate 'ui.py')) -and (Test-Path (Join-Path $candidate '__init__.py'))) {
        $root = $candidate
        break
    }
    $base = $candidate
}
if (-not $root) { throw 'Radice del progetto non trovata (ui.py)' }
$env:IUV_PROJECT_ROOT = $root

$scripts = Join-Path $root '.opencode\skills\blender-bridge\scripts'
if (-not (Test-Path (Join-Path $scripts 'blender_bridge.py'))) { throw "Ponte non trovato: $scripts" }

$proc = Start-Process -FilePath $blender `
    -ArgumentList @('--factory-startup', '--no-window-focus', '--python',
        ('"' + (Join-Path $scripts 'blender_bridge.py') + '"')) `
    -PassThru -WindowStyle Hidden

try {
    $ready = $false
    for ($i = 0; $i -lt 60; $i++) {
        Start-Sleep -Seconds 1
        if (Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue) {
            $ready = $true
            break
        }
    }
    if (-not $ready) { throw "Ponte Blender non in ascolto sulla porta $Port" }

    & $py (Join-Path $scripts 'bridge_call.py') (Join-Path $scripts 'iuv_ui_probe.py')
}
finally {
    Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
}
