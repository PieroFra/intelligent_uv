# G2 / G3 — Manual Verification Procedures

Internal note (Repo-Ops). Scope: gate **G3** (clean install lifecycle) and gate **G2**
(RizomUV manual round trip) as defined in `ROADMAP.md` §3.

Evidence class: **(c) — manual execution on a real Blender session, transcribed by a human
operator**. Nothing in this document may be promoted to class (a)/(b) by inference: if a step
was not actually executed and observed, it is recorded as `NOT EXECUTED` with the reason, never
as `PASS`.

Rule of the house: **every step must be executable without questions**. Each step states what to
do, where to look, and what outcome counts as failure. Ambiguity in a step is a bug in this
document, not in the addon.

Runs performed inside `_esperimenti\` are **non-gate**: they are exploratory evidence, they stay
out of `ROADMAP.md`, and they never close G2 or G3.

---

## Artifact under test

| Field | Value |
|---|---|
| ZIP | `dist\intelligent_uv-0.34.0.zip` |
| Size | 195,308 B |
| Contents | 45 files — 41 `.py` + 4 docs |
| SHA-256 | `5860c473c2905ce48b7942b52d88d0111a3caa67b70a729b3e4126c99287e75e` |

> **Re-verify the hash immediately before every run.** `dist\` is gitignored, so the ZIP is not
> versioned and may have been rebuilt or replaced since the hash above was recorded. If the
> recomputed SHA-256 differs, stop and record the new hash together with the run — do not
> silently continue against an unknown artifact.

Hash check (from the project root):

```powershell
Get-FileHash dist\intelligent_uv-0.34.0.zip -Algorithm SHA256
```

Installations present on this machine (`C:\Program Files\Blender Foundation\`): **Blender 5.2**
and **Blender 4.5**. **Blender 4.2 LTS is absent.** Therefore the 4.2 LTS branch of G3 stays
`NOT EXECUTED (4.2 LTS absent on this machine)` until a 4.2 build is installed. 4.5 is *not* a
substitute for 4.2 in the record: it is a different branch and must be reported under its own
version string.

---

## G3 — Clean install lifecycle

Goal: prove that the packaged ZIP installs, enables, exposes its panel, survives a
disable/re-enable cycle in the same session, and uninstalls cleanly, on a **virgin configuration**.

### Preconditions

- A pristine Blender configuration. Point Blender at an empty config directory so that no
  previously installed copy of the addon can be picked up:
  - Portable/CLI form: launch `blender.exe` with
    `--factory-startup` for the session, and use a dedicated, empty `BLENDER_USER_CONFIG`
    directory for the whole run.
  - GUI form: rename/empty the user config folder *for the duration of the run* and restore it
    afterwards.
- The ZIP hash re-verified as described above.
- A console window visible and scrollable (Blender started with `--debug` optional, but the
  system console must be readable for the whole run). On Windows launch `blender.exe` from a
  terminal so stdout/stderr are captured, or use `Window > Toggle System Console`.
- Note the exact build hash from `Help > About Blender` (or the splash screen): the final report
  line requires it.

### Steps — Blender 5.2 LTS branch

1. **Hash check.** Run the `Get-FileHash` command above. Record the output. A mismatch against
   the documented hash = **FAIL**, do not install.
2. **Virgin profile.** Start Blender 5.2 with the empty user-config directory (see
   Preconditions). Confirm in `Preferences > Add-ons` that `Intelligent UV` is **not** listed.
   If it is listed, the profile is not virgin: stop and fix the config, do not continue.
3. **Install from Disk.** `Preferences > Add-ons > Install from Disk...`, select
   `dist\intelligent_uv-0.34.0.zip`. Read the console: an install error or a traceback during
   install = **FAIL**.
4. **Restart (mandatory).** Close Blender completely and reopen it with the same config
   directory. Reinstalling/enabling this addon requires a Blender restart: the RNA pointer to the
   `PropertyGroup` would otherwise remain dangling (reason documented in `__init__.py`; do not
   attempt a reload workaround).
5. **Enable.** `Preferences > Add-ons`, enable `Intelligent UV`. Read the console: any traceback,
   or an `Error: ...` line during registration = **FAIL**. Confirm a second time in
   `Preferences > Add-ons` that the entry is now checked and not greyed out.
6. **Panel present.** In the 3D Viewport, press `N` and open the sidebar tab **Intelligent UV**.
   The panel `VIEW3D_PT_IntelligentUV` must be visible with its sections populated. Missing or
   empty panel = **FAIL**.
7. **Check Mesh.** With a default cube (and, optionally, any second mesh of interest) selected as
   the active object, run the **Check Mesh** operator from the panel. The expected result is a
   report without traceback; any traceback in the console = **FAIL**. Record the report line
   verbatim.
8. **Disable + re-enable without restart (console capture).** Disable the addon, then immediately
   enable it again, **without closing Blender**. Copy the console output of this cycle verbatim
   into the evidence file — do not paraphrase and do not invent messages.
   - Expected behaviour with the idempotency fix (`ef6a94d`): `_registered_classes` tracks what
     the addon registered, so the second `register()` in the same session does **not** lose the
     RNA pointer to `Scene.intelligent_uv_settings`. The panel should come back intact and the
     settings property should still be accessible.
   - The message `[IUV] An earlier version was still loaded...` is expected **only** when classes
     already exist outside `_registered_classes` (e.g. a module reinstall on top of a live
     session). If it appears during this plain disable/enable cycle, record it as an observation
     to investigate — it is not the normal path.
   - Any traceback, or a panel that does not return, = **FAIL**.
   - Reminder for the record: a **reinstall of a new version still requires a restart**, exactly
     as in step 4. The disable/re-enable result says nothing about hot-reloading a new build.
9. **Restart.** Close and reopen Blender with the same config directory.
10. **Enable after restart.** Enable `Intelligent UV` again and read the console (no traceback =
    continue; traceback = **FAIL**).
11. **Confirm panel.** `N` sidebar > **Intelligent UV** visible and populated, and
    `Scene.intelligent_uv_settings` readable (the panel's fields hold their defaults). Missing
    panel or missing properties = **FAIL**.
12. **Remove.** `Preferences > Add-ons > Remove` (or the `v` menu > Uninstall) for
    `Intelligent UV`. Read the console: a traceback during unregister/uninstall = **FAIL**.
    Confirm the entry disappears from the add-ons list.

### Steps — Blender 4.2 LTS branch

Same sequence as steps 1–12 above, executed on a Blender 4.2 LTS build.

Status on this machine: **`NOT EXECUTED (4.2 LTS absent on this machine)`**. Only Blender 5.2 and
4.5 are installed under `C:\Program Files\Blender Foundation\`. Do not substitute 4.5 for 4.2 in
this record; if 4.5 is exercised, report it as a separate, clearly labelled column.

### Evidence to keep

- Re-verified SHA-256 output of the ZIP.
- Blender version **and build hash**.
- Path of the user-config directory used, plus proof it started empty.
- Full console capture for steps 3, 5, 8, 10, 12 (the step 8 capture is the important one: it is
  the only record of the disable/re-enable messages).
- The verbatim Check Mesh report line from step 7.
- Screenshot or text dump of the panel in steps 6 and 11.

### Report line

```
G3 PASS/FAIL — <date> — Blender <ver> (<build hash>) — ZIP sha256 <hash>
```

One such line per Blender branch exercised. Branches not executed get their own line with
`NOT EXECUTED` and the reason in place of PASS/FAIL.

---

## G2 — RizomUV manual round trip

Goal: prove the manual FBX round trip Blender → RizomUV → Blender works end to end on a real
scene, and that the import report matches the faces actually written.

### Preconditions

- RizomUV installed. Default expected path (from `settings.rizomuv_path`):
  `C:\Program Files\Rizom Lab\RizomUV 2025.0\rizomuv.exe`. Verify the actual install path and
  record the RizomUV version from its About/Help dialog.
- `open_in_editor` is `True` by default, so the export operator opens the editor automatically.
- A mesh object with a real UV situation (existing UVs or none — record which) selected and
  active in the 3D Viewport.
- A console/task-manager window available for the orphan-process check.

### Steps

1. **Verify RizomUV presence and version.** Confirm the executable exists at the configured
   `settings.rizomuv_path` (or point the setting at the real path). Open RizomUV once and record
   its version string.
   - If RizomUV is not installed: mark the whole gate **`NOT EXECUTED (RizomUV absent)`** and
     stop. In that state every automatic (non-manual) claim about the bridge stays labelled
     **experimental** in `ROADMAP.md` — an absent editor can never be reported as verified.
2. **Select the mesh object.** Make the target mesh the active object. Note its name and its face
   count — both are needed to read the import report later.
3. **Export & Open.** Press the **Export & Open** button in the panel, which calls
   `intelligent_uv.export_fbx` (label: "Export UV to FBX"). Record the FBX path written and read
   the console for traceback (traceback = **FAIL**). With `open_in_editor = True`, RizomUV must
   come up on that file.
4. **Unwrap and save in RizomUV, over the file.** Perform the unwrap/pack in RizomUV and save
   either back over the file that was opened, or as `<name>_import.fbx` next to it. Record which
   of the two was done: the import operator accepts both.
5. **Import.** Either press **Import** (calls `intelligent_uv.import_last`, "Import Last") to pick
   the newest candidate, or press **Import from...** (calls `intelligent_uv.import_fbx`,
   "Import UV from FBX") and choose the file explicitly.
   - Candidate resolution for Import Last: `<root>_import.fbx` or the exported file — the newest
     one wins. If the wrong file is picked up, that is a finding: record the two timestamps.
6. **Capture the import report.** Copy the report line verbatim from the console / info area:

   ```
   UVs imported onto '<obj>' - layer '<layer>', <matched>/<total> faces matched, <copied> loops written[, <unmatched> faces kept their previous UVs.]
   ```

   Check that `<total>` equals the face count noted in step 2, that `<obj>` and `<layer>` are the
   ones expected, and that the report is internally consistent with what was saved in RizomUV.
   A missing report line, or a traceback, = **FAIL**.
7. **Zero hang, zero orphans.** Confirm Blender is responsive after the import (no hang) and that
   no RizomUV process is left running unattached. Check the task manager for `rizomuv.exe`
   processes; close any that the workflow legitimately leaves open and record that it was manual.
   A hung Blender or an orphaned process = **FAIL**.

### Absent-RizomUV branch

If step 1 fails, the gate line is:

```
G2 NOT EXECUTED — <date> — RizomUV absent
```

and every claim about automatic/external handling stays marked **experimental** in the roadmap.

### Report line

```
G2 PASS/FAIL — <date> — RizomUV <ver> — match <N>/<M>
```

`<N>/<M>` is copied from the step 6 report line (`<matched>/<total>`), not recomputed by hand.

---

## Summary of the two gate lines

| Gate | Line |
|---|---|
| G3 | `G3 PASS/FAIL — <date> — Blender <ver> (<build hash>) — ZIP sha256 <hash>` |
| G2 | `G2 PASS/FAIL — <date> — RizomUV <ver> — match <N>/<M>` |

Neither line may be written from memory, from a previous run, or from an inference. Numbers come
from the console output and the artifact hash of the run being reported.
