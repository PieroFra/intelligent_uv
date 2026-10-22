---
name: blender-bridge
description: Eseguire Python dentro un Blender gia' aperto via ponte TCP locale. Usare quando serve ispezionare la UI o lo stato reale di Blender senza riavviarlo.
---

# Blender Bridge

Ponte TCP locale che esegue codice Python **dentro Blender**, nel thread principale, e
restituisce stdout ed errori. Serve per guardare lo stato vero di un'istanza viva (pannelli,
aree, proprieta' della scena) invece di ricostruirlo a tavolino.

Non serve per i test: quelli passano da `.opencode\scripts\run_tests.ps1`, che avvia una
istanza pulita e non ha bisogno del ponte.

## Avvio (una volta sola)

```powershell
$env:BLENDER_BRIDGE_PORT = '9879'
Start-Process 'C:\Program Files\Blender Foundation\Blender 5.2\blender.exe' -ArgumentList @(
  '--factory-startup', '--no-window-focus',
  '--python', 'C:\Users\checc\Desktop\BLENDER ADDONS\intelligent_uv\.opencode\skills\blender-bridge\scripts\blender_bridge.py'
)
```

Porta diversa da 9878 (quella di ACTD): due progetti possono avere il ponte aperto insieme.

## Chiamata

`python` nel PATH e' la stub del Microsoft Store: usare il Python di Blender.

```powershell
$py = 'C:\Program Files\Blender Foundation\Blender 5.2\5.2\python\bin\python.exe'
& $py 'C:\Users\checc\Desktop\BLENDER ADDONS\intelligent_uv\.opencode\skills\blender-bridge\scripts\bridge_call.py' -c "import bpy; print(bpy.app.version_string)"
```

Oppure con un file:

```powershell
& $py '...\bridge_call.py' 'C:\percorso\script.py'
```

## Note

- Una richiesta per volta: il ponte serializza, ma non e' pensato per il parallelismo.
- In modalita' GUI un timer esegue la coda nel thread principale; in `--background` il ciclo
  e' bloccante.
- Il codice gira **dentro** Blender: `sys.path` e' quello di Blender, non del progetto. Per
  caricare l'addon aggiungere a mano la radice del workspace.
- Le variabili `BLENDER_BRIDGE_HOST` (default `127.0.0.1`) e `BLENDER_BRIDGE_PORT`
  (default `9878`) vanno impostate **sia** all'avvio **sia** nella chiamata.
