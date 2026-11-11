# ASSETS.md — Standard immagini del portfolio

Standard valido per **tutti** gli addon del portfolio. Nessuna immagine è "pronta"
senza la validazione descritta qui. Riferimento: `AGENTS.md` sezione 5 (skill
`blender-gui-capture` e gate `gif_check.py`).

## 1. Hero GIF

- Durata: **6-8 secondi**.
- Peso: **sotto 8 MB**.
- Inquadratura **identica per ogni addon**: stessa scena checker, stessa camera,
  stesse proporzioni. L'utente deve riconoscere il portfolio dalla composizione.
- Contenuto: il workflow dell'addon in azione, nessun montaggio decorativo.

## 2. Still (tre fisse)

Nomi obbligatori, identici per ogni addon:

| File | Contenuto |
|---|---|
| `01-panel` | pannello Sidebar aperto, tab dell'addon attiva |
| `02-work` | l'addon durante l'esecuzione (pipeline visibile) |
| `03-result` | risultato finale sulla scena checker |

- Risoluzione **coerente tra addon** e tra i tre still dello stesso addon.
- **Stessa scena checker** in tutti gli still: base neutra condivisa, cambia solo
  ciò che l'addon fa.
- Sidebar sempre visibile e leggibile (etichette non troncate, verifiche con il
  probe UI dove disponibile).
- **Niente splash screen, niente cursore** nel frame.

## 3. Coerenza cross-addon

- Stessi font e stesse proporzioni del viewport tra tutti gli addon.
- Stesso stile di cattura: niente filtri, niente annotazioni disegnate a mano.

## 4. Pipeline tecnica

1. Cattura: **solo** con la skill `blender-gui-capture` (ricetta one-shot,
   `screenshot_area` con `temp_override`, max 2 avvii Blender GUI per task).
2. Composizione/montaggio: `compose_gif.py`.
3. Validazione **obbligatoria**: `gif_check.py` (`~\.config\opencode\scripts\gif_check.py`,
   puro stdlib) — l'asset è pronto solo dopo la riga `GIF_CHECK_OK`.
4. **Vietato il ritocco manuale** delle immagini (Photoshop, crop estetici, ecc.).

## 5. Convenzione percorsi

Tutte le immagini vivono in `docs\images\` dell'addon, con prefisso addon:

```
docs\images\<addon>-hero.gif
docs\images\<addon>-01-panel.png
docs\images\<addon>-02-work.png
docs\images\<addon>-03-result.png

Nota (intelligent_uv): gli still effettivamente in repo usano nomi
descrittivi, non il prefisso `<addon>`; il momento "result" e' coperto da
`02-uv-checker-result.png` (render checker approvato). Non esiste alcun file
`03-*` nel repository: non referenziarlo.
```

Esempio: `docs\images\intelligent_uv-01-panel.png`.

## 6. Checklist finale (5 punti)

1. Hero GIF 6-8 s, sotto 8 MB, inquadramento identico agli altri addon?
2. Tre still con nomi fissi (`01-panel`, `02-work`, `03-result`), stessa scena
   checker e risoluzione coerente?
3. Sidebar visibile e leggibile, zero splash e zero cursore in ogni frame?
4. Cattura con `blender-gui-capture`, montaggio con `compose_gif.py`?
5. `gif_check.py` eseguito e riga `GIF_CHECK_OK` ottenuta, nessun ritocco manuale?

Se un solo punto è "no", l'asset **non è pronto**.
