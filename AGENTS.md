# AGENTS.md — Intelligent UV Mapping

Regole operative per gli agenti. È l'unica fonte di verità sul progetto: se un altro
documento dice il contrario, vale questo.

---

## 0. Dove siamo

- Workspace: `C:\Users\checc\Desktop\BLENDER ADDONS\` — **una cartella per addon**.
- Progetto: `C:\Users\checc\Desktop\BLENDER ADDONS\intelligent_uv\`
- Backup: `G:\Il mio Drive\ADDON BLENDER\intelligent_uv\ULTIMA\`
- Mappa del workspace: `..\00-INDICE.md`

Qui la cartella del progetto **è** l'addon: package Python piatto, nessun monolite, nessun
build step. Non esiste una `actd_build\` e non va inventata.

---

## 1. Com'è fatto il codice

| Area | File | Note |
|---|---|---|
| ingresso | `__init__.py` | `bl_info`, `CLASSES`, `register`/`unregister` |
| dati utente | `properties.py` | `PropertyGroup` agganciato a `Scene.intelligent_uv_settings` |
| UI | `ui.py` | `VIEW3D_PT_IntelligentUV`, tab **Intelligent UV** |
| operatori | `operators\` | `run`, `native`, `external`, `diagnose`, `batch`, `preview_ops`, `check`, `seams`, `base` |
| pipeline | `mesh_analysis` → `curvature` → `seam_planning` → `region_merge` → `seam_marking` → `uv_executor` | |
| qualità | `distortion`, `texel_density`, `island_extraction`, `validation`, `margins` | |
| RizomUV | `rizomuv_bridge`, `rizomuv_link`, `rizomuv_script` | import **lazy**, Windows-only |
| capability | `capabilities.py` | `EXTERNAL_ENGINE_ENABLED` (bool fisso, `capabilities.py:8`) |

- ~15.238 righe, 52 file `.py` (33 moduli radice + 10 in `operators\` + 9 test in `tests\`), conteggio da `dist\intelligent_uv-0.36.0.files.txt`.
- **Due edizioni dallo stesso sorgente.** L'edizione completa (GitHub) contiene l'integrazione
  RizomUV opzionale; l'edizione nativa per Blender Extensions (0.36.0, script
  `.opencode\scripts\build_extension_native.ps1`) **esclude fisicamente**
  `rizomuv_bridge.py`, `rizomuv_link.py` e `rizomuv_script.py` dallo staging e dallo ZIP e
  impone `EXTERNAL_ENGINE_ENABLED = False` in `capabilities.py` nell'artefatto (verifica
  sia a staging sia a ZIP chiuso: `build_extension_native.ps1:41-72`).
- **Codice, commenti e docstring in inglese**: non tradurre, non mescolare le due lingue nei file.
- Versione dichiarata: **0.36.0**, Blender minimo **4.2.0**, verificato su 5.2 LTS.

---

## 2. Vincoli di progetto

- **Un modulo alla volta**: una modifica, la sua verifica, poi la successiva. Niente refactoring a tappeto.
- **Nessuna dipendenza nuova**: solo `bpy`, `bmesh`, `mathutils`, `numpy` (incluso in Blender).
  RizomUV resta opzionale e caricato in modo lazy.
- Il `PropertyGroup` va registrato **prima** di chi lo usa: l'ordine in `CLASSES` non è casuale.
- Non rinominare: `intelligent_uv_settings`, le classi `IntelligentUV_*`, il pannello, la
  `bl_category`, gli id degli operatori.
- Non rimuovere proprietà esposte nella UI: i preset e i `.blend` salvati le referenziano.
- Differenze Blender 4.2 / 5.2: **fallback espliciti** (`try/except`, `getattr`), mai controlli
  di versione sparsi nel codice.
- Reinstallare l'addon **richiede il riavvio di Blender**: il motivo è spiegato in `__init__.py`
  (il puntatore RNA al `PropertyGroup` resterebbe appeso). Non aggiungere reload automatici.

---

## 3. Verifica

### Tabella Verifica (la leggono gli agenti generici)

Eseguire i comandi **dalla radice del progetto**.

| Cosa | Comando |
|---|---|
| test | `powershell -NoProfile -ExecutionPolicy Bypass -File .opencode\scripts\run_tests.ps1` |
| mappa | `powershell -NoProfile -ExecutionPolicy Bypass -File .opencode\scripts\run_index.ps1` |
| ui | `powershell -NoProfile -ExecutionPolicy Bypass -File .opencode\scripts\run_ui_probe.ps1` |
| suite selettive | `powershell -NoProfile -ExecutionPolicy Bypass -File .opencode\scripts\verify.ps1 -TaskTag <tag> -Suites <test_1.py,test_2.py>` (verdetto solo dalla riga finale `VERIFY_OK | ...` / `VERIFY_FAIL | ...`, exit code 0/1/2) |
| build edizione nativa | `powershell -NoProfile -ExecutionPolicy Bypass -File .opencode\scripts\build_extension_native.ps1` (produce lo ZIP Blender Extensions senza `rizomuv_*`) |
| gate G3 nativo | `powershell -NoProfile -ExecutionPolicy Bypass -File .opencode\scripts\gate_g3_native_install.ps1` (ultima riga `G3_NATIVE OK | ...` / `G3_NATIVE FAIL | ...`, install pulita dell'edizione nativa su profilo vergine) |

Atteso: **14 controlli, 0 fallimenti**. Il probe UI scrive in `%TEMP%\opencode\iuv_gui\` e deve
chiudere con `flagged=0`.

Blender non è nel PATH; `python` nel PATH è la stub del Microsoft Store. Percorsi completi:
- Blender: `C:\Program Files\Blender Foundation\Blender 5.2\blender.exe`
- Python interno: `C:\Program Files\Blender Foundation\Blender 5.2\5.2\python\bin\python.exe`

Le **prove esplorative** (mesh esterne, esperimenti) non sono verifiche: l'Esploratore scrive solo
in `_esperimenti\` e i suoi risultati restano fuori da ROADMAP e dal gate G1.

Lo smoke test copre import, registrazione, pannello, operatori, proprietà e unregister. Scrive `.opencode\tests\test_out.txt` e termina con
`RISULTATO passati=X falliti=Y totale=N`. Il Tester riporta solo quella riga.

---

## 4. Cosa manca (stato reale)

- Lo smoke test copre registrazione e struttura, non la pipeline: export, seam, import e RizomUV
  restano scoperti.
- Il probe UI deterministico (misura di ogni etichetta con `blf.dimensions`) è attivo anche qui:
  88 etichette, `flagged=0` in IT e EN, screenshot in `%TEMP%\opencode\iuv_gui\`
  (run 2026-11-08 19:51, `ui_report.txt`: `UI_SUMMARY labels=88 flagged=0 region_width=561`).
- Il doppio `register()` è verificato: il check `doppio_register` dello smoke test richiama
  `register()` una seconda volta e controlla che `Scene.intelligent_uv_settings` sopravviva. Log
  `.opencode\tests\test_out.txt`: 14/14, 0 fallimenti. Restano scoperti pipeline UV e RizomUV.
- RizomUV non è verificabile headless: serve il programma installato e un caso reale.
- Il packaging esiste: `.opencode\scripts\package_release.ps1` produce in `dist\` (gitignored)
  `intelligent_uv-0.36.0.zip`, il `.sha256` e la lista file (release GitHub
  `v0.36.0`). Il gate G3, cioè l'installazione pulita su configurazione vergine, è
  **superato**: ultima riga `G3_NATIVE OK` con `.opencode\scripts\gate_g3_native_install.ps1`
  sullo ZIP 0.36.0 dell'edizione nativa.

---

## 5. Squadra

I ruoli sono **globali**, in `~\.config\opencode\agents\`: un'unica copia per tutti gli addon
(squadra Fuoriclasse, aggiornata 10/2026). Questo progetto li specializza con i fatti di questo
file (tabella Verifica) e con i permessi di `opencode.json` riguardanti `ops` e `publisher`.

Ruoli e modelli (squadra a pagamento sul provider managed di OpenCode aka Zen, fatturata a token,
attiva dal 2026-10-26 dopo l'esaurimento dei limiti gratuiti):
- `architetto` (+ `architetto-riserva` su OpenRouter): Gemini 4 Argon via Vertex AI, piano e
  deleghe con tag, non tocca file; risposta nella struttura Stato / Piano / Deleghe / Prossimo passo.
- `architetto-free`: Claude Haiku 5.5 #low (`opencode/claude-haiku-5-5#low`, unico modello paid a
  basso costo; forza tutti i subagenti sui modelli *-free di Zen e ollama locali a 0 €).
- `coder`: `opencode/deepseek-v4.1-flash` (Zen, paid) - patch chirurgiche su `*.py` e test headless.
- `tester`: `opencode/deepseek-v4.1-flash#low` (online: il gate reale).
- `repo-ops`: `opencode/deepseek-v4.1-flash#low` - test, docs, packaging, esperimenti documentati.
- `esploratore`: `opencode/qwen3.8-flash` (Zen, paid, file `esploratore.md`) - solo `_esperimenti\`, risultati non-gate.
- `visualizzatore`: `google-vertex/gemini-4-argon#low` - probe UI deterministico, Vision nativa.
- `composer`: `google-vertex/gemini-4-argon#low` - composizione e montaggio asset visivi.
- `scenografo`: `opencode/deepseek-v4.1-flash#low` - prepara i `.blend` da registrare.
- `publisher`: `opencode/glm-5.3-flash` (Zen, paid) - per la verifica visiva si affida al visualizzatore o alla
  variante Vision su OpenRouter (richiede chiave).
- `revisore`: `opencode/deepseek-v4.1-flash#low` (`revisore.md`) - rilegge le patch del coder, solo lettura.
- `diagnostico`: `opencode/deepseek-v4.1-flash#low` -
  localizza la causa radice dei bug (file:righe) con `grep`/`read` e verifica la riproduzione
  headless; sola lettura, risposta in 3 righe.
- `traduttore`: `ollama/nemotron-bolt-e4b-q8:actd` (locale, solo testo).
- `ops-offline`: `ollama/nemotron-bolt-e4b-q8:actd`.
- `coder-offline`: `ollama/mimo-v2.6-9b-q8:actd`.
- `architetto-offline`: `ollama/qwen35-9b-q8:actd`.

- Il Coder scrive solo i `.py` del package; non tocca `.opencode\` né i `.md`.
- Il Repo-Ops scrive test, documentazione e `.opencode\`, mai il codice dell'addon.
- Il Tester esegue `.opencode\scripts\run_tests.ps1`; il Visualizzatore esegue
  `.opencode\scripts\run_ui_probe.ps1`.
- L'Architetto esegue i comandi della tabella Verifica solo quando l'utente lo richiede
  esplicitamente; in quel caso riporta l'esito come farebbe il Tester (per il test la riga
  `RISULTATO passati=X falliti=Y totale=N`). Negli altri casi delega a Tester e Visualizzatore.
- L'Esploratore fa prove su mesh esterne e scrive solo in `_esperimenti\` con i tool di
  scrittura (la shell non è sandboxata): i risultati sono **non-gate** e non entrano in ROADMAP.
- Il Publisher (scrittura dev-to-dev; per la verifica visiva usa la variante Vision su
  OpenRouter o chiede la verifica al Visualizzatore) prepara `docs/PROMO.md` e
  `docs/FEEDBACK.md`, verifica visivamente con `read` che GIF e screenshot siano dritti
  prima dell'upload, scrive con zero em-dash e pubblica via Chrome CDP con la regola
  Prepare & Hand-off.
- Le skill globali, in `~\.config\opencode\skills\` (una copia per tutti gli addon):
  `addon-publisher` (pubblicazione multi-canale via Chrome CDP), `browser-personale` (Chrome
  personale dell'utente, porta 9222, login gia attivi), `caccia-bug` (bug in 4 fasi Red ->
  Root Cause -> Green -> Gate: riproduzione, causa radice, fix del coder, gate a tag),
  `blender-gui-capture` (screenshot,
  crop Sidebar IT/EN e GIF nella GUI reale), `addon-gui-gate` (gate interattivi tipo G2/G3),
  `obs-screen-capture` (video GUI con OBS/FFmpeg), `ciclo-verifica` (smoke test + mappa +
  probe UI in un ciclo), `modulo-sprint` (un modulo: prompt coder+tester+visualizzatore e
  gate a tag), `release-addon` (bump versione, changelog, packaging, zip+sha256), `audit-docs`
  (doc sincere rispetto al codice), `preset-compatible` (proprieta utente non rimosse o
  rinominate), `triage-feedback` (feedback -> proposte ROADMAP), `sessione-inventario`
  (handoff di fine sessione in `.opencode\handoff\`).
- Le due skill di cattura chiudono con un gate deterministico:
  `~\.config\opencode\scripts\gif_check.py` (puro stdlib, `--selftest` incluso) boccia
  i GIF neri, statici, senza loop o oltre 10 MB **prima** di spendere token di vision.
  Va rilanciato dopo ogni montaggio, e la vision viene dopo, non al posto suo.
