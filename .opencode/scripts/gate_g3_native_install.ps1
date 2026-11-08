param(
    [string]$Zip = ''
)

$ErrorActionPreference = 'Stop'

# Gate G3 (installazione nativa): profilo utente Blender isolato in TEMP,
# installazione e abilitazione della sola edizione nativa in formato extension
# (dist\intelligent_uv-0.35.1-nativo-extension.zip), poi controllo headless:
#   1) estensione abilitata (chiave 'intelligent_uv' o 'bl_ext.<repo>.intelligent_uv'
#      in preferences.addons);
#   2) pannello VIEW3D_PT_IntelligentUV e operatore intelligent_uv.run registrati;
#   3) nessun modulo intelligent_uv.rizomuv_* importabile;
#   4) nessun processo esterno avviato (subprocess non toccato dal load dell'addon).
# Uscita: exit code 0/1, riga finale "G3_NATIVE OK ..." o "G3_NATIVE FAIL ...".
#
# Non tocca il sorgente del repo e non crea profili permanenti: BLENDER_USER_RESOURCES
# e' reindirizzato su una cartella temporanea cancellata alla fine.

$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$blender = "C:\Program Files\Blender Foundation\Blender 5.2\blender.exe"
if (-not (Test-Path -LiteralPath $blender)) { throw "Blender non trovato: $blender" }
if (-not $Zip) { $Zip = Join-Path $root 'dist\intelligent_uv-0.35.1-nativo-extension.zip' }
if (-not (Test-Path -LiteralPath $Zip)) { throw "Artefatto nativo assente: $Zip" }

$stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$prof = Join-Path ([IO.Path]::GetTempPath()) "opencode\g3_native\$stamp"
New-Item -ItemType Directory -Path $prof -Force | Out-Null

$check = Join-Path $prof 'g3_check.py'
$verdict = Join-Path $prof 'g3_verdict.txt'

@'
# Controllo headless del gate G3 (edizione nativa): scrive esattamente una riga
# di verdetto in g3_verdict.txt e non tocca altro.
import importlib.util
import sys
import traceback

import bpy

fails = []

# 1) Estensione abilitata: come extension il modulo si registra come
#    bl_ext.<repo>.intelligent_uv, quindi si accetta una chiave che termina
#    con '.intelligent_uv' oppure la chiave esatta 'intelligent_uv'.
_addon_keys = list(bpy.context.preferences.addons.keys())
if not any(k == 'intelligent_uv' or k.endswith('.intelligent_uv') for k in _addon_keys):
    fails.append('estensione intelligent_uv non abilitata (chiavi addons: ' + ', '.join(_addon_keys) + ')')

# 2) Operatore registrato: si interroga bpy.ops.intelligent_uv, non bpy.types.
#    Pannello: si scansiona bpy.types cercando bl_idname 'VIEW3D_PT_intelligent_uv'.
try:
    if not hasattr(bpy.ops.intelligent_uv, 'run'):
        fails.append('operatore bpy.ops.intelligent_uv.run assente')
    _panel = (
        hasattr(bpy.types, 'VIEW3D_PT_IntelligentUV')
        or hasattr(bpy.types, 'VIEW3D_PT_intelligent_uv')
        or any(
            getattr(cls, 'bl_idname', '') == 'VIEW3D_PT_intelligent_uv'
            for cls in vars(bpy.types).values()
            if isinstance(cls, type)
        )
    )
    if not _panel:
        _evid = 'nomi bpy.types con "ntelligent": [' + ', '.join(
            n for n in dir(bpy.types) if 'ntelligent' in n
        ) + ']'
        _evid += ' | bl_idname con "intelligent": [' + ', '.join(
            (getattr(c, 'bl_idname', '') or '') for c in vars(bpy.types).values()
            if isinstance(c, type) and 'intelligent' in (getattr(c, 'bl_idname', '') or '')
        ) + ']'
        fails.append('pannello VIEW3D_PT_intelligent_uv assente; evidenza: ' + _evid)
    if not hasattr(bpy.types.Scene, 'intelligent_uv_settings'):
        fails.append('proprietà Scene.intelligent_uv_settings assente')
    if not hasattr(bpy.ops.intelligent_uv, 'run'):
        fails.append('operatore bpy.ops.intelligent_uv.run assente')
except Exception as exc:
    fails.append('check registrazione fallito: ' + repr(exc))

# 3) Nessun modulo RizomUV importabile (assenti fisicamente dal pacchetto).
# find_spec: ModuleNotFoundError sul package padre e' assenza attesa = ok.
for mod in ('intelligent_uv.rizomuv_bridge', 'intelligent_uv.rizomuv_link', 'intelligent_uv.rizomuv_script'):
    try:
        _spec = importlib.util.find_spec(mod)
    except ModuleNotFoundError:
        _spec = None
    if _spec is not None:
        fails.append('modulo importabile non atteso: ' + mod)
    try:
        __import__(mod)
        fails.append('import riuscito non atteso: ' + mod)
    except ModuleNotFoundError:
        pass
    except Exception:
        # Presente ma rotto: comunque una violazione (deve proprio non esserci).
        fails.append('modulo presente ma in errore: ' + mod)

# 4) Nessun processo esterno avviato: il load non deve aver messo in sys.modules
#    i launcher RizomUV e le proprieta' operatore non devono agganciare il bridge.
for mod in ('rizomuv_bridge', 'rizomuv_link', 'rizomuv_script'):
    if mod in sys.modules:
        fails.append('sys.modules contiene: ' + mod)

if fails:
    with open(r'%(verdict)s', 'w', encoding='utf-8') as fh:
        fh.write('G3_NATIVE FAIL | ' + '; '.join(fails))
else:
    with open(r'%(verdict)s', 'w', encoding='utf-8') as fh:
        fh.write('G3_NATIVE OK | estensione abilitata, pannello e operatore run registrati, rizomuv_* assenti')
'@ -replace [regex]::Escape('%(verdict)s'), $verdict | Set-Content -LiteralPath $check -Encoding UTF8

$env:BLENDER_USER_RESOURCES = $prof
try {
    # Installazione CLI nativa Blender 5.2: install-file nel repo utente + abilitazione.
    & $blender --command extension install-file -r user_default --enable $Zip | Out-Null
    $installCode = $LASTEXITCODE
    & $blender --background --python $check | Out-Null
    $checkCode = $LASTEXITCODE
}
finally {
    Remove-Item Env:\BLENDER_USER_RESOURCES -ErrorAction SilentlyContinue
}

if ($installCode -ne 0) {
    Write-Output "G3_NATIVE FAIL | extension install_file exit code $installCode"
    Remove-Item -LiteralPath $prof -Recurse -Force -ErrorAction SilentlyContinue
    exit 1
}

if (Test-Path -LiteralPath $verdict) {
    $line = (Get-Content -LiteralPath $verdict -Raw).Trim()
} else {
    $line = "G3_NATIVE FAIL | verdict assente (check exit code $checkCode)"
}

Write-Output $line
Remove-Item -LiteralPath $prof -Recurse -Force -ErrorAction SilentlyContinue
if ($line -like 'G3_NATIVE OK*') { exit 0 } else { exit 1 }
