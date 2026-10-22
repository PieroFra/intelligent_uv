# G1 — Release gate procedure (bolt_action_rifle_7_62)

Internal note (Italian allowed by AGENTS.md §5 for notes; procedure steps in English).

## Scope

This document is the **executable recipe** for gate **G1** (clean install + real-asset pipeline
run) of `intelligent_uv` 0.34.0. It is written to be executed end-to-end by a single operator
without asking questions: every step has a command, an expected result and an explicit STOP
condition. Anything not covered here is out of G1 scope.

## Evidence class

G1 produces evidence of **class (c)** as defined in `ROADMAP.md` §3 / Phase 1:
**clean install on a pristine configuration, real asset, human-visible UI run, dated log kept.**

Class (c) is the only class that satisfies G1. Classes (a)/(b) and any run under `_esperimenti\`
do **not** satisfy it.

## Rule: executable without questions

Each numbered step below is self-contained: command or click path, expected observation,
STOP rule. If a step cannot be executed as written, G1 is **FAIL (not executed)** — do not
improvise a substitute step and do not reinterpret the expected result.

## Warning: `_esperimenti\` runs are non-gate

The Explorer runs recorded under `_esperimenti\` are **non-gate** by construction
(AGENTS.md §3): they are headless, they load the add-on with an **in-process `register()`**
instead of a real install, and there is **no install-then-restart cycle**. They therefore
**cannot** be used as G1 evidence, no matter how green they look. `_esperimenti\` is
**read-only** for this procedure: the only thing taken from it is the SHA256 table in step 2.

---

## 1. Artifact prep

Run from the project root (`C:\Users\checc\Desktop\BLENDER ADDONS\intelligent_uv`).

1. **Trigger**: only AFTER the documentation commits of this phase are done. Do not package a
   dirty tree.
2. Run:
   ```
   powershell -NoProfile -ExecutionPolicy Bypass -File .opencode\scripts\package_release.ps1
   ```
3. Record verbatim from the console the four reported items: **ZIP**, **SHA256**, **FILELIST**,
   **CHECKSUM**.
4. Record the ZIP hash independently and compare it with the printed value:
   ```
   Get-FileHash -Algorithm SHA256 dist\intelligent_uv-0.34.0.sha256
   ```
   and read the sidecar:
   ```
   Get-Content dist\intelligent_uv-0.34.0.sha256
   ```
   Expected: sidecar content equals the console SHA256 of the ZIP. Otherwise **STOP**.
5. Note for the log: `dist\` is **gitignored** — the artifact is not part of the commit, so the
   recorded hash is the only durable reference.
6. Expected artifact name: `intelligent_uv-0.34.0.zip` (+ `.sha256`, + file list).

STOP if: script exits non-zero, no ZIP produced, or sidecar/hash mismatch.

## 2. Asset re-download

1. Source page: `https://polyhaven.com/a/bolt_action_rifle_7_62`
2. Direct download of the 1K glTF set:
   `https://dl.polyhaven.org/file/ph-assets/Models/gltf/1k/bolt_action_rifle_7_62/bolt_action_rifle_7_62_1k.gltf`
3. Author: **Mateusz Sadek** — licence **CC0**.
4. Download all **8 files** (`.gltf` + `.bin` + 6 JPG textures) into a **new, empty** folder
   (do not reuse `_esperimenti\assets\...`). The FONTE.md line says "~4.2 MB"; that figure does
   **not** match the byte column below, whose sum is **6,040,615 B (~5.76 MiB)**. Treat the byte
   column as authoritative and record the real on-disk total.
5. Verify with the SHA256 table below (copied verbatim from
   `_esperimenti\FONTE.md`, read-only source of truth for the hashes):

| File | SHA256 | Byte |
|---|---|---|
| bolt_action_rifle_7_62_1k.gltf | 60A5C7A745625DD38275756CA359170FFADCD427827FF5A161AF3149BDABB9EC | 15369 |
| bolt_action_rifle_7_62.bin | C9A32B6471EF08B6D901F9C1865A31C22D37B254A3F772A3C3348D0FA8203ED0 | 736616 |
| textures/bolt_action_rifle_7_62_accesories_arm_1k.jpg | D45228BCDD1FB969F2A5FE07DACB4864C68BAF27CD0BFC821EA9AE0B9F0BAFED | 984292 |
| textures/bolt_action_rifle_7_62_accesories_diff_1k.jpg | 624908D9514C958F0F17CD967CA93A3060B613EDA97D6D94BC25AA40EDCAA8F9 | 878584 |
| textures/bolt_action_rifle_7_62_accesories_nor_gl_1k.jpg | A437112195ECEBBB809D208A444E38581C769AB4849D9A714F65C1D8BDE414B4 | 1007303 |
| textures/bolt_action_rifle_7_62_arm_1k.jpg | 8206367BAA98EDA75C09BCA5C43341E382EB4365C1A08CF7ABBDFAA3801C46F5 | 892057 |
| textures/bolt_action_rifle_7_62_diff_1k.jpg | 81A7A97770E7F8D5E19BB45B35D2BA97404D6BD44AB1D29487C3C3B431883C4A | 856375 |
| textures/bolt_action_rifle_7_62_nor_gl_1k.jpg | CC0477D86301EA63FDD877416F80D70A9B8FE0598A8772C9CBD754B212D9C2EA | 670019 |

6. Check every file:
   ```
   Get-ChildItem -Recurse -File | ForEach-Object { "$($_.Name) $((Get-FileHash -Algorithm SHA256 $_.FullName).Hash) $($_.Length)" }
   ```
7. Expected: **8/8 identical** (hash and byte count). Any single mismatch → **STOP**, do not
   proceed to step 3; a gate run on unverified input is void.
8. `_esperimenti\` stays read-only: do not write there.

## 3. Fresh Blender install

1. Use a **virgin config/profile** — no `intelligent_uv` anywhere in
   `%APPDATA%\Blender Foundation\Blender\<ver>\` (start with `--factory-startup --config` or a
   dedicated user config dir). Record which config dir was used.
2. `Edit > Preferences > Add-ons > Install from Disk...` → select
   `dist\intelligent_uv-0.34.0.zip`.
3. **Enable** the add-on; confirm the panel appears in the `Intelligent UV` tab.
4. **Restart Blender** (mandatory: the RNA pointer to the `PropertyGroup` stays attached, see
   `__init__.py`; no auto-reload exists by design). G1 requires the post-restart state — an
   install without restart is not class (c).
5. After restart, record version + build hash:
   ```python
   import bpy
   print(bpy.app.version_string, bpy.app.build_hash.decode())
   ```
   Expected: **`5.2.0`** and build hash **`fbe6228777e7`**. Different build → record it and
   mark the run as *off-baseline* (do not silently accept).
6. Record: OS, Blender version + build hash, add-on version **0.34.0**, ZIP SHA256 (step 1).

## 4. Check Mesh

1. Import the glTF from step 2 into an empty scene.
2. Join the **7 meshes** into one object. Target: **19,985 faces**. Record the actual face count
   before pressing anything; a different count means a different asset/case → record it as
   *off-baseline*.
3. Press **Check Mesh** in the panel (operator id `intelligent_uv.check`).
4. Copy the **entire** report as printed, including the closing `summary()` line with its exact
   shape: `N blocking / N warning / N note`.
5. Rule: any `blocking > 0` → **G1 FAIL**, stop here. Warnings and notes are recorded, not fatal.

## 5. Unwrap ×2

1. Confirm **all defaults untouched** (no preset loaded, no value edited). Record the panel state
   (preset name / `default`).
2. Press the button labelled **Unwrap** (operator **id `intelligent_uv.run`**, whose `bl_label` is
   "Run Intelligent UV" — record both label and id in the log; a screenshot of the button is the
   proof of the label).
3. Record, verbatim from console/UI:
   - total time (s), as printed;
   - island count;
   - fill / efficiency percentages;
   - distortion metric(s) as printed;
   - unresolved islands count;
   - warnings list.
4. Overlap/labelling outcomes — quote the **literal** line, exactly one of the two is expected:
   - overflow case: `N island bounding boxes intersect, too many to verify precisely. Check the UV editor.`
     (candidate cap = **40,000**)
   - clean case: `No real overlaps: all N bounding-box candidates cleared the edge intersection test.`
5. Run the **second time** on the same object to measure variance; record total time and islands
   for run #2 next to run #1. Record the delta, not a judgement.
6. STOP/FAIL rule: crash, exception traceback, or a missing metric = FAIL for this step; record
   the traceback text in full.

## 6. B1–B4 (behavioural claims)

Each item must end with an explicit verdict: ***reproduced*** or ***refuted***, plus the measured
number. No verdict without a number.

**B1 — speed claim**
1. Only the endpoint **0.36 s** is testable. The **3.78 s** baseline is **not recoverable**:
   history is single-commit, so the old behaviour cannot be re-instantiated.
2. Measure the endpoint on the step-4 mesh, same machine/session as step 5. Record the measured
   wall time next to 0.36 s.
3. Verdict on the endpoint only; state explicitly that the 3.78 s comparison is out of reach.

**B2 — secondary timing claim**
1. **0.72 s** is accepted **only if** the stage and the mesh it refers to are both defined in the
   claim source (stage boundaries + exact mesh/face count).
2. If either is undefined → write **"not reproducible"** and stop the item. Do not invent a
   substitute stage to make it pass.

**B3 — nested island**
1. Construct an island nested inside another island's bounding box.
2. Expected: the nested island is reported as **overlapping** (literal line from step 5.4).
3. Then, in a **scratch copy** of the file, remove the fix that handles nesting and re-run
   **Check Mesh**: expected the check **fails** (blocking). Original file untouched.
4. Verdict + numbers (island ids, blocking/warning counts).

**B4 — crease threshold**
1. Claim: the crease angle is **absolute 30°** — constants `CREASE_ANGLE = 30.0` and
   `HARD_EDGE_FLOOR_DEG = 30.0`.
2. Test: edges on the border a few degrees under 30° must **not** be creased; at/over 30° they
   must be.
3. Same scratch-copy discipline as B3: original file untouched, run on a copy.
4. Verdict + measured angles (e.g. edge at X° → creased yes/no).

## 7. Evidence to keep

Keep one dated log file (outside `dist\`, which is gitignored) containing:

1. Date/time and operator, machine, OS.
2. ZIP name + SHA256 + sidecar content (step 1).
3. All **8 asset SHA256 + byte counts** and the folder used (step 2).
4. Blender **version + build hash**, add-on **0.34.0**, config dir used, restart confirmed
   (step 3).
5. Check Mesh report **verbatim** + `summary()` line (step 4).
6. Both Unwrap runs: times, islands, fill/efficiency, distortion, unresolved islands, warnings,
   literal overlap line (step 5).
7. B1–B4 verdicts with the measured numbers (step 6).
8. Stage boundaries (which stage timed what) and every console line quoted literally.

Checklist (all must be ticked for PASS):

- [ ] `dist\intelligent_uv-0.34.0.zip` built after commits; SHA256 recorded and matching sidecar
- [ ] 8/8 asset hashes identical; folder recorded
- [ ] virgin config, install from disk, enabled, **Blender restarted**
- [ ] Blender `5.2.0` / `fbe6228777e7`; add-on `0.34.0`
- [ ] 7 meshes joined, face count recorded (target 19,985)
- [ ] Check Mesh: `0 blocking` (else FAIL)
- [ ] Unwrap run #1 with defaults intact; all metrics recorded; overlap line literal
- [ ] Unwrap run #2 variance recorded
- [ ] B1 endpoint measured (baseline declared unrecoverable)
- [ ] B2 = measured number or "not reproducible"
- [ ] B3 verdict (*reproduced*/*refuted*) + numbers
- [ ] B4 verdict (*reproduced*/*refuted*) + measured angles
- [ ] dated log kept; `_esperimenti\` unmodified

## 8. Output

Final line of the run log, exactly this shape:

```
G1 PASS/FAIL — <date> — Blender <ver> (<build hash>) — add-on 0.34.0 — ZIP sha256 <hash>
```

Example of the expected baseline values (not a result): `Blender 5.2.0 (fbe6228777e7)`.
