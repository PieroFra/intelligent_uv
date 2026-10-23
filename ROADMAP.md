# Intelligent UV Mapping — Roadmap to a Reliable Public Release

This roadmap covers one goal: making the add-on safe to publish on GitHub and
cheap to keep updated. It is not a feature roadmap. New UV algorithms are out of
scope until the repository, the documentation and the verification story agree
with the code.

Baseline: **0.34.0**. Target: the first tagged public release of that baseline,
with an artifact that installs cleanly and a set of logs that supports every
claim the README, the release notes and any portfolio material make. Post-release
development and the GitHub publication plan are recorded separately in section 8
and are not part of this target.

---

## 0. How to read this file

Every statement here belongs to exactly one of three classes. Do not mix them;
most of the confusion this roadmap exists to remove came from treating one class
as another.

| Class | Meaning | Where it lives |
|---|---|---|
| **(a) Verified** | Read from this working tree, the smoke log, `git`, `THIRD_PARTY.md` or `AGENTS.md` | Sections 1 and 3 |
| **(b) Reported, not reproduced** | Numbers or bug fixes supplied by the owner from an external report; no benchmark, test or log in this repository backs them | Section 2, to be settled by the gate in Phase 1 |
| **(c) Manual gates** | Checks no headless run in this repository can perform; a human executes them on a named build, asset or program, and the log is kept | Section 3 |

**Rule:** a claim moves up a class only when the artifact that proves it exists
and is referenced from this file. Prose in the README is not that artifact.

### 0.1 The v0.33.0 → v0.34.0 material handled here

The owner supplied, as the last report from an earlier session (Opus), a set of
performance results and two bug fixes attributed to the 0.33.0 → 0.34.0 span.
They arrive second-hand, after the work that produced this file, and **none of
them was re-measured or re-tested while this roadmap was written**. They are
therefore class (b) until Phase 1 says otherwise.

| Claim as reported | Status in this tree | Missing evidence |
|---|---|---|
| Island/overlap grouping went from **3.78 s** to **0.36 s** on a **315-island** layout | Appears as prose in `README.md` (island overlap test) and in a `distortion.py` docstring; no benchmark script, no log, no separate timing table | A re-runnable timing on a named mesh, with stage boundaries and the Blender build hash |
| **0.72 s** for the post-unwrap stage on a **47k-face** mesh | **Not present anywhere in the repository**; no code comment, doc, changelog entry or test mentions it | Definition of which stage was timed, the mesh, and a re-runnable measurement |
| Overlap containment bug (nested island) fixed | Described in README and implemented as a distinct containment path in `distortion.py`; the smoke suite does not exercise it | A regression assertion that fails if the containment path is removed |
| Otsu crease-threshold bug fixed | Described in README; the code uses an absolute crease angle (`CREASE_ANGLE = 30.0`, `HARD_EDGE_FLOOR_DEG = 30.0`) instead of a share of the Otsu split | A regression assertion on a mesh whose sharpest edge is well below 30° |

Consequences that shape the phases below:

- The **0.33.0 baseline is not in this repository.** History is a single import
  commit of 0.34.0, and `CHANGELOG.md` has a 0.34.0 entry but no 0.18.0 – 0.33.0
  history. The 3.78 s figure therefore cannot be re-measured here: only the
  **0.36 s endpoint** can be checked against a re-run. A delta is a claim about
  a tree nobody can check out.
- The **0.72 s figure cannot be reproduced at all** until someone defines the
  stage boundaries and the mesh. It must not enter the README, release notes or
  portfolio in the meantime.
- The two bug fixes may well be real; the tree is consistent with both
  descriptions. Consistency is not verification. What is missing is a test that
  fails when the fix is removed.
- None of these figures may be used as evidence of quality, speed or readiness.
  They are **historical results to reproduce**, first in the Phase 1 gate and then
  in the benchmark harness of section 5.

---

## 1. Verified current state — class (a)

Everything below is read from the repository, not from earlier plans.

| Area | Fact | Source |
|---|---|---|
| Version | `bl_info` declares **0.34.0**, minimum Blender **4.2.0**, category `UV` | `__init__.py` |
| Author | `bl_info["author"]` is still `"Your Name"` | `__init__.py` |
| Size | **41** Python files (**31** root modules + **10** in `operators/`), **11,715** lines | file count |
| Smoke test | **14 passed, 0 failed, 14 total** on Blender **5.2.0 LTS**, build hash `fbe6228777e7`, built 2026-07-14; asserts 17 classes, 14 operators, 65 properties | `.opencode/tests/test_out.txt` |
| Pipeline test | **7 passed, 0 failed, 7 total** on the same build: three negative paths (no active object, non-mesh object, empty mesh) and the native pipeline on cube, cylinder and sphere, with UV range/density/angle checks | `.opencode/tests/pipeline_out.txt` |
| Register risk | The log includes passing `doppio_register` and `re-register` checks; the guard tracks what it registered and snapshots scene settings. `register()` now reads scenes through `getattr` so it survives Blender's `RestrictBlend` sandbox | smoke log, `__init__.py` |
| Test scope | The smoke test covers registration, panel, operators, properties and unregister; the pipeline test covers the native pipeline on **primitives only**. Neither runs on the gate asset, and neither executes the external/RizomUV path | `smoke_test.py`, `pipeline_test.py` |
| Repository | Branch `main`, one commit (`e357426 import iniziale Intelligent UV Mapping 0.34.0`), **no remote configured** | `git log`, `git remote` |
| Working tree | `README.md`, `ROADMAP.md`, `__init__.py` and the smoke test are modified but uncommitted; the two UI-probe scripts, `LICENSE` and `THIRD_PARTY.md` are untracked | `git status` |
| Distribution files | `LICENSE` (GPL-3.0-or-later) and `THIRD_PARTY.md` exist but are **not committed**; no `.github/`, no `blender_manifest.toml`, no packaging script | directory listing, `git status` |
| Documentation drift | `CHANGELOG.md` now has a **0.34.0** entry, and neither the README nor this file cites `tests/test_core.py` any more: both point at `.opencode/tests/smoke_test.py`. The 0.16.0 version drift in this file is fixed by this revision | `CHANGELOG.md`, `README.md`, grep over `*.md` |
| User flow in the panel | Nine primary controls, everything else behind **Advanced**; the README documents Check Mesh and the native Unwrap as the normal path | `README.md`, `ui.py` |
| Relevant operators | `intelligent_uv.check` ("Check Mesh"), `intelligent_uv.run` ("Run Intelligent UV"), `intelligent_uv.export_fbx` ("Export UV to FBX"), `intelligent_uv.import_fbx` ("Import UV from FBX"), `intelligent_uv.import_last` ("Import Last") | `operators/check.py`, `operators/run.py`, `manual_io.py` |
| RizomUV | Optional, Windows-only, imported lazily. README records a manual round trip against **2025.0.117**. The automated engine sits behind an experimental toggle that the README itself says has **never completed a round trip reliably** | `README.md`, `AGENTS.md`, bridge modules |
| RizomUVLink | MIT, Rizom-Lab, **not vendored**: no package, wheel or binary in the tree; imported at runtime from the RizomUV install | `THIRD_PARTY.md` §2 |
| Licence audit | Two development scripts under `.opencode/` are byte-identical to the sibling `ACTD` copies (SHA-256 recorded). No vendored Python package. No copyright/SPDX headers found in the add-on. Explicitly **not a legal audit** and no proof of title | `THIRD_PARTY.md` |
| Internal notes | `AGENTS.md` and `opencode.json` are git-ignored; `AGENTS.md` now matches the smoke log (**14** checks, `doppio_register` listed as verified) and declares the **0.34.0** version | `.gitignore`, `AGENTS.md`, smoke log |

What this means:

- The double-`register()` risk is **closed by both code and test**; it is no
  longer a release blocker.
- The UV pipeline is now **covered on primitives** by the 7-check pipeline suite,
  but still **unverified on a real asset**: a passing smoke 14/14 and pipeline
  7/7 says nothing about the gate asset, seams, packing or density under
  production conditions — and nothing at all about the timings in section 2.
- The public documentation still states performance figures whose measurement
  nobody can rerun; they stay class (b) until a timed run is recorded.
- The licence is chosen and written, but **not committed**; choosing it records
  the terms of distribution, not proof of authorship over every line.
- The repository has never been pushed or packaged. That, not the code, is the
  gap between this tree and a GitHub release.

---

## 2. Reported but not reproduced — class (b)

This section exists so the figures are not lost and not believed. They are
accepted only as hypotheses with a reproduction procedure attached.

| # | Claim | Reported value | Appears in tree as | Reproduction requires |
|---|---|---|---|---|
| B1 | Island overlap/grouping speed-up, 0.34.0 | 3.78 s → 0.36 s, 315 islands | README prose, `distortion.py` docstring | A timed stage on the gate asset mesh (G1); check the **0.36 s endpoint** only, because no 0.33.0 tree exists |
| B2 | Post-unwrap stage time, 0.34.0 | 0.72 s, 47k faces | **Nothing** | A defined stage boundary, the mesh, the build hash, a rerun |
| B3 | Overlap containment (nested island) fix | fixed | README prose; containment path in `distortion.py` | A regression check that fails when the path is removed |
| B4 | Otsu crease-threshold fix | fixed | README prose; absolute crease angle in `auto_params.py` / `curvature.py` | A regression check on a mesh whose sharpest edge is far below 30° |

Rules for class (b):

- No README sentence, release note, commit message or portfolio page may present
  B1–B4 as measured facts until the corresponding log exists.
- B2 is not in the README today. Keep it out; the absence is correct.
- When a claim is reproduced, record: date, add-on version, Blender build hash,
  mesh name and face/island counts, stage boundaries, wall-clock value, log path.
  When it is refuted, remove the prose from the README in the same change.
- A reproduced value that differs from the reported one is a finding, not a
  problem to smooth over: the README gets the measured number.

---

## 3. Manual gates — class (c)

These are the only checks that can turn class (b) into class (a), and the only
ones that can authorise the words "verified", "tested" or a performance figure in
public. Each gate produces a dated record that stays with the release.

| Gate | What is executed | Pass criteria | Evidence to keep | Verdict |
|---|---|---|---|---|
| **G1 — Release gate on the CC0 rifle asset** | Install 0.34.0 the documented way, **restart Blender**, open the gate asset — Poly Haven `bolt_action_rifle_7_62`, CC0, author Mateusz Sadek, <https://polyhaven.com/a/bolt_action_rifle_7_62> — re-downloaded from that source and hash-verified, run **Check Mesh**, then **Unwrap** | Check Mesh report read and its blockers/warnings accounted for; Unwrap finishes with no traceback and no silent zero-area islands; island count and quality numbers recorded; console output captured | Gate log with date, add-on version, Blender build hash, asset source URL and per-file SHA-256, mesh vertex/face/island counts, Check Mesh summary, timings, unsaved warnings | **OPEN** — pending the interactive install → restart → Check Mesh → Unwrap session on the gate asset (the 2026-10-23 headless run is non-gate support only) |
| **G2 — RizomUV manual round trip** | Export UV to FBX with the RizomUV launch option, unwrap and save in RizomUV, Import UV from FBX / Import Last | UVs return by position onto the same object; layer name and match reported; no hang, no orphaned process | Dated log: RizomUV version, export path, import path, object and layer name, match/failure counts | **G2 PASS — 2026-10-23 — RizomUV 2025.0.117 — match 500/500** |
| **G3 — Clean install lifecycle** | Fresh Blender config, install ZIP, restart, enable, Check Mesh, disable, enable again, restart, enable, remove | No traceback in the console at any step; documented restart requirement reproduced, not worked around | Console log per step for each target Blender version | **G3 PASS — 2026-10-23 — Blender 5.2.0 LTS (fbe6228777e7) — ZIP sha256 df81d098...93a1**; Blender 4.2 LTS branch: **NOT EXECUTED** (4.2 LTS absent on this machine) |
| **G4 — Publication authorisation** | Owner reviews any asset, `.blend`, FBX, screenshot or log intended for the public case study | Explicit approval recorded before publication; sanitised if paths or names leak | Written approval note | **OPEN** — owner approval not yet recorded |

**G1 asset substitution (2026-10-22).** The production rifle the gate was
originally written for is no longer available, so the owner has accepted the CC0
Poly Haven model **`bolt_action_rifle_7_62`** (author Mateusz Sadek, CC0,
<https://polyhaven.com/a/bolt_action_rifle_7_62>) as the gate asset. The gate is
executed on that asset **re-downloaded from the source above**, not on a local
copy of unknown provenance, and the download is hash-verified file by file
exactly as recorded in `_esperimenti/FONTE.md` (SHA-256 table for the 1K glTF
set). That file is read-only input for this purpose: nothing inside
`_esperimenti/` is modified by a gate run. Source URL, download date and hashes
belong in the gate log so a third party can rebuild the same mesh.

**G1 requires a real install and a restart.** The gate is an interactive session
on Blender with the add-on installed the documented way (ZIP from Preferences on
a fresh configuration), **Blender restarted afterwards**, then Check Mesh →
Unwrap. The exploratory runs recorded under `_esperimenti/` do not satisfy it:
they were headless (`--background`, factory startup), with the add-on registered
in-process from source instead of installed, no restart, and no interactive
product session. Per `AGENTS.md` §3 they are **class non-gate**: they may inform
the procedure and suggest where to look, but they are not G1 evidence and none of
their numbers may be cited as a gate result.

**What G1 blocks, and what it does not.**

- It **does not block** preliminary work: repository hygiene, commits,
  documentation edits, packaging scripts, CI scaffolding, the benchmark harness,
  the manifest research, or any other technical work in this file. Those can and
  should proceed while the gate is pending.
- It **does block**: any claim of quality, reliability or speed in the README or
  release notes; any use of B1–B4 as evidence; the first public release or tag;
  and the portfolio case study built on G1 numbers.
- It is blocking because it is the only check that exercises the product path
  (Check Mesh → Unwrap) on a real asset, and the automated suite does not.

### 3.1 Recorded so far — automated runs and non-gate headless support

Everything in this table exists as a file in the tree or, for the two class (c)
rows, is the operator's dated console transcription quoted verbatim and kept
with the release. None of the automated or headless rows closes a gate: the
automated suites are class (a) structural evidence, and the headless runs are
**class non-gate** by the rule above. Class (c): **G2 PASS and G3 PASS on
Blender 5.2 LTS, both 2026-10-23** (last two rows); G1 and the Blender 4.2 LTS
branch of G3 remain open.

| Evidence | Result as recorded | Artifact | Class |
|---|---|---|---|
| Smoke suite | **14/14**, 0 failed — Blender 5.2.0 LTS, build `fbe6228777e7` (2026-07-14) | `.opencode/tests/test_out.txt` | (a) |
| Pipeline suite | **7/7**, 0 failed — same build; 3 negative paths + native pipeline on cube/cylinder/sphere | `.opencode/tests/pipeline_out.txt` | (a) |
| G1-style headless run | 2026-10-23, 19,985 faces (target matched), Check Mesh **0 blocking / 1 warning / 1 note**, Unwrap `FINISHED` twice at **2.70 s** and **2.58 s**, 0 loops outside the 0–1 tile, 0 collapsed UV faces | `_esperimenti/gates/g1_run/report.md`, `metrics.json`, `console.log` | non-gate |
| G3-style headless run | 2026-10-23, **FAIL at step 5 (Enable)**: `AttributeError: '_RestrictData' object has no attribute 'scenes'`, ZIP sha256 `5860c473…` | `_esperimenti/gates/g3_run/g3_report.md`, `g3_log.txt` | non-gate |
| G2-style headless run | 2026-10-23, export `FINISHED` (15,788 B FBX), RizomUV live link failed (link port 49152 not opened within 180 s), external edit **simulated inside Blender**, import `FINISHED` with 6/6 faces and 24 loops matched on layer `SmartUV`, 0 unmatched | `_esperimenti/gates/g2_run/runs/20261023-181059/log.txt`, `results.json` | non-gate |
| G2 manual round trip on Suzanne (operator, Blender GUI + RizomUV) | **G2 PASS — 2026-10-23 — RizomUV 2025.0.117 — match 500/500.** Export & Open → RizomUV opened on `Suzanne_uv.fbx` → unfold + pack in RizomUV 2025.0.117.g4c8bab02 → save → Import UV from FBX. Console verbatim: `UVs imported from Suzanne_uv.fbx onto 'Suzanne' — layer 'SmartUV', 500/500 faces matched, 1968 loops written.` Match 100%, backup layer `SmartUV_backup` created; the em dash mangled in the console line is encoding-only, cosmetic | Operator console transcription of 2026-10-23, kept with the release per the §3 evidence rule | (c) |
| G3 manual install lifecycle (operator, Blender GUI) | **G3 PASS — 2026-10-23 — Blender 5.2.0 LTS (fbe6228777e7) — ZIP sha256 df81d098...93a1.** Full ZIP sha256 `DF81D09823BE74C512F816E733F02C09516617C7ADE9D9C533CD77EF5CC493A1`; clean install on a fresh config, Intelligent UV panel populated, Check Mesh verbatim: `Mesh is clean: nothing found that would spoil the unwrap.`; disable, re-enable, restart, enable, remove — lifecycle OK, no traceback at any step. Blender 4.2 LTS branch: NOT EXECUTED (4.2 LTS absent on this machine) | Operator console transcription of 2026-10-23, kept with the release per the §3 evidence rule | (c) |

What the G1-style run does and does not support: the measurements are consistent
with the expectations (no blocking check, no out-of-tile loops, no traceback,
small run-to-run variance), but the report itself states the verdict line cannot
be filled, because the add-on was registered in-process from source rather than
installed from the ZIP on a virgin configuration, with no restart and no
interactive session. It is supporting evidence for the manual procedure, not a
G1 result. Its 15.8% UV coverage is an artifact of `--background` (packing
operators fail `poll()` there) and must not be quoted as a quality figure.

What the G3-style run changed: the failure was traced to `register()` reading
`bpy.data.scenes` inside Blender 5.2's `RestrictBlend` sandbox, and fixed in
commit `e91cf4d` by guarding the collection access. The supplementary probe
scripts `50`–`53` in the same folder exercise enable, panel, Check Mesh and
disable/re-enable after that fix, but **their console output was not captured**,
so no dated lifecycle log exists after the fix. G3 therefore had no passing
record on headless evidence until the operator closed it on 2026-10-23 with the
manual lifecycle run on the patched ZIP (class (c) row above). Blender 4.2 LTS
was not executed at all (not installed on the gate machine).

Consequence for this roadmap: the headless runs recorded above are allowed to
inform the procedure, the checklist wording and where to look; they are **not**
citable as gate results and none of their numbers may appear in the README or
release notes.

What the G2-style run does and does not support: it exercises export, import and
Import Last against a real RizomUV 2025.0 install, but the live link never
reached RizomUV (port 49152 not opened within 180 s), so the external editing
step was **simulated inside Blender**. The 6/6 face and 24-loop match therefore
proves the import path, not a RizomUV round trip. G2 stayed open on headless
evidence until the operator closed it on 2026-10-23 with the interactive
desktop session on Suzanne: launch RizomUV from Export & Open, unfold and pack
there, save, import back — 500/500 faces matched, 1968 loops written (class (c)
row above). The earlier Lua-script draft run in the same folder meanwhile
confirms the documented `-cfi` path does not terminate (240 s timeout, empty
log).

---

## 4. Phases, in priority order

Phases are sequential in priority, not in wall-clock time: Phase 3 and the
research in Phase 4 can start while G1 is pending. Nothing after Phase 1 may
publish a quality claim before G1 passes.

### Phase 1 — Release gate on the CC0 rifle asset (blocking)

**Why:** the product is the unwrap, not the registration. The automated suites
run the pipeline only on primitives; nothing runs it on the gate asset, and every
performance figure currently published is class (b). The accepted gate asset is
the CC0 Poly Haven
model **`bolt_action_rifle_7_62`**, expected to report **19,985 faces** — a
number the run confirms, not one assumed here; the production rifle the gate was
first written for no longer exists.

1. Write a short, repeatable gate procedure: exact install step, restart, asset
   download and hash check, file, object, buttons pressed, values recorded. It
   must be executable by someone else without asking questions.
2. Build the installable ZIP from the current tree with
   `.opencode\scripts\package_release.ps1` — output in `dist\`, which is
   **gitignored**, so rebuild it after the documentation commits and immediately
   before the gate. Then install 0.34.0 the documented way (ZIP from Preferences,
   fresh configuration) and **restart Blender**. Record the build hash and add-on
   version; a run without the install and the restart does not satisfy the gate.
3. Re-download the gate asset from <https://polyhaven.com/a/bolt_action_rifle_7_62>
   and verify every file's hash against the table in `_esperimenti/FONTE.md`, then
   run **Check Mesh** on it. Keep the full report, including blockers, warnings
   and the counts it prints. If it blocks, record why and stop; that is a gate
   failure, not a reason to work around the check.
4. Run **Unwrap**. Record wall-clock time, island count, fill/efficiency,
   distortion summary, unsolved-island count and the exact console lines.
5. Do not compare against the figures of the lost rifle: **47k faces, 214
   non-manifold edges, 46 disconnected pieces, 16 of 183 unsolved islands are
   historical figures from the lost asset — informational only, not pass
   criteria**, and they cannot be reproduced because the asset is gone. Instead
   **record what this asset reports**: vertices, faces, pieces, island count and
   unsolved islands as printed by this run, against the expected 19,985 faces.
   If a measured count differs from 19,985, record the measured value and say why
   (asset variant, separate objects joined or left apart).
6. Reproduce or refute **B1** and **B2**: time the island-grouping stage and the
   post-unwrap stage separately on the recorded gate mesh. If the add-on does not
   expose stage timers, run a profiling pass and define the boundaries in the
   log. Check the **0.36 s** endpoint; the 3.78 s baseline is not recoverable
   from this repository.
7. Reproduce or refute **B3** and **B4** with targeted checks: a nested island
   inside another island must be reported as overlapping; an edge at a few
   degrees must not count as creased. Then delete each fix in a scratch copy and
   confirm the check fails.
8. Run Unwrap a second time on the same file and record variance; this is the
   only way to know whether a timing is stable enough to publish.
9. File an issue for every discrepancy between the log, the README and this
   roadmap.

**Done when**

- The gate log exists, is dated, and names build, version, asset source URL plus
  per-file hashes, mesh and stage boundaries.
- Check Mesh and Unwrap both completed, or the failure is written down as the
  result.
- B1–B4 are each marked **reproduced** or **refuted**, with the number that was
  actually measured.
- Either the README figures are backed by this log, or the unbacked sentences
  are removed.

---

### Phase 2 — RizomUV Export & Open / Import as a supported flow

**Why:** the manual round trip is what users actually do, and the automated path
is admitted to be unreliable. The documentation must say exactly which one is
supported.

1. Document the manual flow as the supported path: **Export UV to FBX** with
   *launch RizomUV*, work in RizomUV, then **Import UV from FBX** or **Import
   Last**. State that UVs return by position, not by loop index.
2. Execute **G2** on the RizomUV version recorded in the README (2025.0.117 at
   the time of writing) and attach the dated result. Any claim about a different
   version needs its own run.
3. Decide the fate of the automated engine behind the experimental toggle:
   keep it, clearly labelled experimental and with its failure mode documented,
   or remove it from the panel. Record the decision and its reason; if kept, the
   operator ids stay stable.
4. Keep the attribution accurate: `RizomUVLink` is MIT, **not vendored**, and no
   copy may ship in the ZIP. If that ever changes, an MIT notice must ship with
   it and `THIRD_PARTY.md` must be updated before the change lands.
5. Do not let the README imply cross-platform parity: the live link is
   Windows-only; macOS and Linux keep the manual FBX round trip.

**Done when**

- A dated G2 log exists for a named RizomUV version.
- The README describes the manual flow as supported and the automated one as
  experimental or absent — never as verified.
- `THIRD_PARTY.md` still matches reality: nothing vendored, notice travelling
  with the user's install.

---

### Phase 3 — Licence, attribution and repository baseline

**Why:** a public repository needs a clean starting point, a licence and a real
author, and the licence must not be mistaken for a title audit.

1. Commit `LICENSE` and `THIRD_PARTY.md` together with the README *License &
   attribution* section. They exist in the working tree; they are not in history.
2. Keep the wording that separates **declared** authorship from what inspection
   can verify. The licence records the terms of distribution; it is not proof of
   title over every line, and the source audit in `THIRD_PARTY.md` is an
   inventory with stated limits, not a legal opinion.
3. Re-verify the two recorded SHA-256 digests before committing. If either
   `.opencode/skills/blender-bridge/scripts/` file was edited, the identity claim
   stops applying and the table must change.
4. Replace `"Your Name"` with the real author and add repository/support URLs
   where Blender and GitHub expect them.
5. Commit the register fix, the smoke update and the probe scripts as focused
   commits; do not mix them with documentation or packaging changes.
6. Decide repository visibility from the first push. **It stays private for
   now**, and the owner has chosen a free showcase; the remote is added when
   that changes. Confirm that `AGENTS.md`, `opencode.json`, `__pycache__/` and
   test output stay ignored.
7. `AGENTS.md` is already aligned with the log (**14** checks, `doppio_register`
   verified, baseline 0.34.0); keep it aligned whenever the suite changes.

**Done when**

- `git status` is clean apart from deliberate, documented exceptions.
- Licence and attribution are committed and match the stated terms.
- Digests in `THIRD_PARTY.md` still match the files.
- The author field is real; visibility and remote state are recorded.

---

### Phase 4 — Distribution metadata, before writing any manifest

**Why:** the release format is a decision with a research step in front of it,
not an assumption. A GitHub ZIP and a Blender Extensions package do not have the
same requirements.

1. **Research first, dated.** Read the current Blender Extensions and add-on
   manifest documentation for the target build (5.2) and for the declared
   minimum (4.2). Record the URLs, the access date and the answers to: is a
   `blender_manifest.toml` required for a ZIP installed from Preferences? What
   fields are mandatory? What does the licence field accept? Are platform tags
   needed for a pure-Python add-on? What changes between 4.2 and 5.2?
2. **Do not assume the manifest is required for a GitHub ZIP.** The answer comes
   from step 1, quoted, not from memory. If it is optional, note what is lost by
   omitting it.
3. Decide the target explicitly: release-tested on 5.2 LTS, minimum declared
   4.2. Only builds actually exercised by the suite or the gate may be called
   verified; the minimum declaration is a compatibility statement, not evidence.
4. If a manifest is adopted, create it only after step 1 and keep **one source of
   truth for version, author and minimum Blender**. `bl_info` stays for legacy
   installs; the two must agree or the drift becomes the next bug.
5. If it is not adopted, record that decision with its reason, so the question is
   not reopened by guesswork.

**Outcome (2026-10-22)**

The research in step 1 was executed and recorded in
`.opencode/notes/manifest_research_2026-10-22.md` — access date **2026-10-22**,
nine manual pages (`gs42`/`gs52`, `addons42`/`addons52`, `lic42`/`lic52`,
`pref42`/`pref52`, `prefext52`). The note is internal and non-gate: its
"Documented facts" section is quoted from those pages, its "Recommendation"
section is our own judgement, not a documented requirement.

Answers as recorded in that note:

| Question | Answer in the accessed documentation |
|---|---|
| Is a `blender_manifest.toml` required for a ZIP installed from Preferences? | **No, on the legacy path.** *Install from Disk* also installs legacy add-ons (`.py` or `.zip`) and does not auto-enable them. The manifest is mandatory only for the **extension** format, shared as a `.zip` containing a manifest plus `__init__.py` |
| Mandatory manifest fields | `schema_version` (`1.0.0`), `id`, `version`, `name`, `tagline`, `maintainer`, `type` (`add-on`), `license` (SPDX expression list), `blender_version_min` |
| What the licence field accepts | SPDX expressions; for add-ons the required licence is **GPL-3.0-or-later**, written `license = ["SPDX:GPL-3.0-or-later"]` — confirmed in both 4.2 and 5.2 |
| Are platform tags needed for a pure-Python add-on? | **No, they are optional.** Omit `platforms` and the extension is offered on all operating systems; declared values are `windows-x64`, `windows-arm64`, `macos-x64`, `macos-arm64`, `linux-x64` |
| `tagline` ≤ 64 characters | **Not verified** — the limit was not found in the accessed pages. It is not a fact here and must not be stated publicly without a source |
| What changes between 4.2 and 5.2 | Same required fields, same default `[build] paths_exclude_pattern`, no documented difference on `maintainer`. The pages do differ on an unrelated API spelling: `bpy.app.online_access_overriden` (4.2) vs `bpy.app.online_access_override` (5.2) |

**Decision (2026-10-22) — legacy ZIP, no manifest.** The first release is a
**GitHub release that ships the legacy ZIP without `blender_manifest.toml`.**
Reasons: the documented Preferences install path does not require the manifest
for a legacy add-on; `bl_info` already carries version, author and minimum
Blender; a second metadata source added before it is needed is exactly the drift
step 4 warns about. `blender_manifest.toml` is therefore **deferred to a possible
publication on Blender Extensions**, and would be created only with its own
research/creation pass, keeping `version`, author and minimum Blender aligned
with `bl_info`. `bl_info` is **not** removed while the legacy format ships; the
conversion guide's "remove the `bl_info` information" step applies only to a real
conversion.

**Done when**

- [x] A dated note states what the current documentation requires, with sources
  — `.opencode/notes/manifest_research_2026-10-22.md`, access date 2026-10-22.
- [x] The manifest decision is recorded, with its reason — legacy ZIP without
  manifest; the manifest is deferred to a possible Extensions publication.
- [ ] Any manifest created agrees with `bl_info` on version, author and minimum
  Blender — **not applicable yet**: no manifest exists. It becomes a requirement
  only if and when `blender_manifest.toml` is created; the note records that
  alignment as our recommendation, not a documented rule.

---

### Phase 5 — ZIP and clean-install lifecycle

**Why:** "works in my addons folder" is not a release. The ZIP is the product,
and the restart requirement is part of its contract.

1. Add a repeatable packaging step that stages the add-on as `intelligent_uv/`
   with `__init__.py` at its root.
2. Exclude development files: `.git/`, `.opencode/`, `__pycache__/`, `*.pyc`,
   `AGENTS.md`, `opencode.json`, local test output, screenshots, gate logs.
3. Include `LICENSE`, `README.md`, `CHANGELOG.md` and `THIRD_PARTY.md`; the
   README and the licence both reference the last one, so it must ship.
4. Produce a versioned ZIP whose contents are listable and reproducible, plus a
   checksum and the file list in the release notes.
5. Execute **G3** on a clean Blender 5.2 LTS and a clean Blender 4.2 LTS with a
   fresh configuration:
   - install the ZIP, **restart**, enable, confirm the **Intelligent UV** panel,
     run Check Mesh;
   - disable, then enable again **without** restarting, and record what happens
     (the add-on documents that a stale module pointer cannot be reloaded);
   - restart, enable, confirm the panel is intact, then remove the add-on;
   - read the console at every step; a traceback fails the gate even if the UI
     looks correct.
6. Confirm the restart requirement is reproduced and described, not engineered
   around. No automatic reload gets added in this roadmap.

**Done when**

- The artifact builds from a clean clone without manual copying.
- The lifecycle table for both versions is filled with real console logs.
- The ZIP contains no development files and no gate logs or screenshots.
- Tag, ZIP filename, `bl_info` and changelog carry the same version.

---

### Phase 6 — README for the user flow

**Why:** the README is the public contract. Today it mixes design essays with
instructions, and it carries figures nobody can rerun.

1. Reorganise the user part around the actual flow: **Check Mesh → Unwrap →
   Export/Import**, then quality output.
2. Document the nine primary controls, and for Advanced: each parameter's
   default, when to change it, and what breaks if it is wrong.
3. State the limits plainly: reinstall requires a restart; RizomUV is optional,
   Windows-only and unverified headless; the automated suite does not exercise
   the UV pipeline; only the Blender versions in the test log are verified.
4. Keep the design notes, but separate them from instructions so a new user can
   finish the flow without reading them.
5. Remove or label every performance figure per section 2. A number without a
   log is either deleted or marked as an unreproduced report.
6. Keep this roadmap linked from the README.

**Done when**

- A reader can complete Check Mesh → Unwrap → Export/Import from the README
  alone.
- Every quantitative claim traces to a gate log or is labelled as unverified.
- No document names `tests/test_core.py` or a version that contradicts the code.

---

### Phase 7 — Distribution decision

**Why:** GitHub portfolio and Blender Extensions demand different maintenance and
different review, and the answer changes what Phase 5 ships.

1. Compare the two channels on: installation friction, update cadence, review
   requirements, permission and platform declarations, licence metadata, and
   what each implies for a free showcase.
2. Record the constraints as they are: the repository is **private for now**, and
   the owner has chosen a **free showcase** (no paid distribution) for the
   portfolio.
3. Default to GitHub + free ZIP first, using the Phase 5 artifact; treat Blender
   Extensions as a second channel only if Phase 4's research shows the cost is
   justified. Do not block the first release on it.
4. State what a public repository would expose (history, issues, test tooling)
   and confirm the ignore rules cover development files.

**Done when**

- One channel is chosen for the first release, with reasons and constraints
  written down.
- The chosen channel's inputs all exist (artifact, metadata, notes, checksum).
- The deferred channel has a recorded trigger for reconsideration.

---

### Phase 8 — Portfolio case study on the gate asset

**Why:** a before/after on a real asset is the strongest honest evidence the
project can offer — provided every number comes from a log and the asset is
authorised for publication.

1. Draft the case study around the Phase 1 gate: the mesh as it arrived, what
   Check Mesh reported, what Unwrap changed, and the resulting island count,
   coverage/efficiency and distortion.
2. Use before/after images only after **G4**. No `.blend`, FBX, texture,
   screenshot, log or mesh statistic leaves the machine without explicit owner
   approval. Assume the asset is not yours until told otherwise.
3. Sanitise paths, usernames and file names if any log excerpt is published.
4. Label class (b) numbers as reported or drop them. If B1–B4 were refuted in
   Phase 1, the case study must not resurrect them.
5. Do not present a single asset as a general benchmark. Say what was measured,
   on what, with which build.

**Done when**

- The draft exists with every figure linked to a gate or benchmark log.
- G4 approval is recorded for each published asset and log.
- No unverified number and no unauthorised file appears in the case study.

---

### Phase 9 — CI and the update loop

**Why:** a release that depends on one machine's memory will drift again. This
phase follows the first release, not precedes it.

1. Add a GitHub Actions workflow on a Windows runner that downloads pinned
   Blender builds (4.2 LTS and 5.2 LTS) and runs the headless suite.
2. Upload `.opencode/tests/test_out.txt` as an artifact so a failure is
   diagnosable without rerunning locally.
3. Add a documentation-consistency job: `bl_info` version equals README version
   and the top changelog entry; no reference to a missing file; every version
   claim matches the test log.
4. Add a packaging job that builds the ZIP and checks its file list against the
   exclusion rules.
5. Make these checks required on `main`; use the same list as the release
   checklist.

**Done when**

- A pull request that changes behavior without tests fails CI.
- A version bump that misses the changelog or README fails CI.
- A release can be produced from a tag without local knowledge.

---

## 5. Parallel work the gate does not block

Technical and documentary work allowed while G1 is pending. None of it may be
used to claim quality before the gate passes.

1. **Native pipeline smoke (headless).** Build primitive meshes in background
   Blender, run analysis → curvature → seam planning → region merge → seam
   marking → native unwrap → island extraction → texel density → distortion, and
   assert invariants: no zero-area islands, all UV loops inside the 0–1 tile, no
   reported overlaps, seam read-back matches the plan.
   **Recorded:** `.opencode/tests/pipeline_test.py`, 7 checks, 7/7 on 5.2.0 LTS
   (`.opencode/tests/pipeline_out.txt`). Still open: the same invariants on the
   gate asset, and coverage of the external path.
2. **Negative paths.** No active object, non-mesh object, Edit Mode, missing UV
   layer, degenerate mesh. Each must fail with a reported reason, not a crash or
   a silent success.
   **Recorded:** the first three are in the 7/7 pipeline suite. Edit Mode,
   missing UV layer and degenerate mesh are **not yet covered**.
3. **Version matrix.** Run the suite on 4.2 LTS and 5.2 LTS. The runner defaults
   to a hard-coded 5.2 path, so the executable must be passed explicitly
   elsewhere.
4. **Benchmark harness for section 2.** A script that times the island-grouping
   and post-unwrap stages on a named mesh, writes a dated line with build hash and
   counts, and can be rerun by anyone. This is the artifact that turns B1 and B2
   into class (a) — or deletes them.
5. **Regression checks for B3 and B4**, written so they fail when the fix is
   removed. A test that cannot fail is documentation, not a test.
6. **Packaging dry run** against a clean clone, to catch the file-list mistakes
   before G3 is attempted.

---

## 6. Limits and non-goals

- **No new UV features in this roadmap.** Valley-following seams, packing
  changes and other ideas stay in the README backlog until the release baseline
  is trustworthy.
- **No refactor of working modules.** One module per change remains the rule;
  renames of `intelligent_uv_settings`, `IntelligentUV_*`, operators, panel or
  `bl_category` are out of scope.
- **No automatic module reload.** Reinstalling still requires a Blender restart;
  the roadmap documents that cost instead of engineering around it.
- **No cross-platform RizomUV claim.** The live link is Windows-only and depends
  on a licensed install; macOS and Linux keep the manual FBX round trip.
- **No CI for RizomUV.** It cannot be verified headless here; manual evidence is
  the only honest option.
- **No guarantee for Blender versions outside the test log.** The code targets
  4.2+, but only builds actually exercised by the suite or the gate may be called
  verified.
- **No developer files in the release ZIP**, and no publishing of `AGENTS.md`,
  `opencode.json`, agent configuration or gate logs.
- **A passing smoke test is not evidence for the pipeline.** No release note may
  imply otherwise.
- **No performance claim without a rerunnable log.** B1–B4 are class (b) until
  Phase 1 or the harness in section 5 produces one.
- **No legal audit.** `LICENSE`, `THIRD_PARTY.md` and the README section document
  the terms of distribution and what is known about the ACTD tooling; they do not
  establish copyright title over the whole code base, and the audit behind them
  cannot rule out third-party material.
- **No repo visibility change by inference.** The repository stays private until
  the owner says otherwise; nothing here schedules a push.

Known practical constraints:

- Blender is not on `PATH`; the test runner takes an explicit executable path and
  currently defaults to the local Blender 5.2 install. CI and other machines must
  override it.
- The system `python` is a Microsoft Store stub; project tooling must use
  Blender's bundled interpreter.
- `.opencode/tests/test_out.txt` is git-ignored, so CI must upload it explicitly.
- The repository history currently consists of a single import commit; tags and
  release notes must carry the release history from here on.
- The version labels 0.33.0 and 0.34.0 come from the report described in
  section 0.1. Only 0.34.0 exists in the tree; the changelog cannot confirm the
  earlier boundary.

---

## 7. Public-release checklist

**Blocking gates**

- [ ] **G1** — clean install, Blender restarted, Check Mesh and Unwrap run on the
      CC0 gate asset (`bolt_action_rifle_7_62`, re-downloaded and hash-verified),
      log kept, B1–B4 marked reproduced or refuted.
- [ ] **G4** — owner authorisation recorded for every asset, screenshot and log
      intended for publication.

**Repository and metadata**

- [ ] `LICENSE` and `THIRD_PARTY.md` are committed (present but untracked at the
      time of writing); digests re-checked.
- [ ] Author and repository URLs are real; `bl_info` author replaced.
- [ ] Manifest decision recorded against dated documentation; version, author and
      minimum Blender agree wherever they appear.
- [ ] `bl_info`, README and top changelog entry all say the same version.
- [ ] Smoke suite passes on Blender 4.2 LTS and 5.2 LTS.

**Artifact and install**

- [x] **G3** — on Blender **5.2 LTS**: **G3 PASS — 2026-10-23 — Blender 5.2.0
      LTS (fbe6228777e7) — ZIP sha256 df81d098...93a1**; clean install, panel
      populated, Check Mesh clean, disable/re-enable, restart, enable, remove —
      console clean at every step (class (c), §3.1).
      - [ ] **G3 on Blender 4.2 LTS — NOT EXECUTED** (4.2 LTS absent on this
        machine); the "both target versions" criterion stays open until this
        branch is run and logged.
- [ ] Release ZIP contains only runtime files, licence, user docs and attribution.
- [ ] Tag, release notes, checksum and file list are published together.

**Claims**

- [ ] Every performance or quality figure in README/release notes traces to a
      gate or benchmark log.
- [x] **G2** — RizomUV claims dated and versioned: **G2 PASS — 2026-10-23 —
      RizomUV 2025.0.117 — match 500/500** (Suzanne manual round trip, class
      (c), §3.1); the automated path stays behind the experimental toggle in
      the README.
- [ ] Known limitations are visible in the README.
- [ ] No asset, log or screenshot published without authorisation.

---

## 8. Post-0.34.0 Development & GitHub Publication Plan

This section is **forward-looking and class (c)-pending**: it records intentions,
not results. Nothing here is scheduled, no item is an existing capability, and
none of it may be quoted in public as shipped, tested or measured before the
release checklist in section 7 is satisfied for that item. It does not reopen the
"no new UV features" rule of section 6 for the 0.34.0 baseline: those features
become eligible only **after** the baseline is released.

### 8.1 GitHub Ready — initial publication

Publication of the repository is the first deliverable of this plan, and it
depends on the repository/ metadata items of section 7, not on new code.

| Input | Current state (read from this tree) | Work required before the first public push |
|---|---|---|
| `README.md` | Published user flow still to be reorganised (Phase 6) | Rewrite around Check Mesh → Unwrap → Export/Import; every figure traced to a log or labelled unverified |
| `LICENSE` | GPL-3.0-or-later, committed | Re-read against the chosen release terms; keep the "terms of distribution ≠ title audit" wording |
| `THIRD_PARTY.md` | Exists and is committed; RizomUVLink recorded as MIT and **not vendored** | Re-verify the recorded SHA-256 digests before tagging; update if any audited file changed |
| Showcase assets | None authorised | **G4** approval per asset before any image, `.blend`, FBX or log is published; sanitise paths and names |
| Repository metadata | Private, no remote, author field still `"Your Name"` | Real author, repository/support URLs, visibility decision recorded (section 6 and Phase 3) |

Rules for this sub-item:

- The publication commit set is documentation and metadata only: no add-on code
  changes ride along with the "GitHub ready" milestone.
- The ZIP published with the first tag is the Phase 5 artifact, built from a
  clean clone, with its checksum and file list in the release notes.
- Asset licensing is recorded next to the asset, not inferred from the fact that
  a download was free.

### 8.2 Features to complete or expand

Each item below is a **plan**, with the open question that has to be answered
before implementation. None of them is covered by the current automated suites
(smoke 14/14 and pipeline 7/7 run on primitives only), so each one needs its own
verification before it can be described as working.

| # | Item | Open question to settle first | Verification it would need |
|---|---|---|---|
| F1 | **UDIM and advanced multi-tile packing** — UDIM grid support and automatic multi-material packing | What `udim.py` does today versus what the UI exposes; whether the native unwrap can target a UDIM grid at all | A pipeline case with more than one tile: loops land in the intended tile, no tile collision, stable across reruns |
| F2 | **Bidirectional interactive live bridge with RizomUV** — desktop/socket handshake resolution | Which side fails to open the link port, and whether the documented launch path can be made to report it; the G2-style headless run saw port 49152 not opened within 180 s | **G2** executed interactively first; the bridge is only "interactive" after a real desktop round trip is logged |
| F3 | **Seam pinning and intelligent preservation in Edit Mode** — interactive UV seam editing | How seam state survives the pipeline's seam marking and region merge without being overwritten | Edit Mode negative path (section 5 item 2) plus a preservation case where a pinned seam reappears after Unwrap |
| F4 | **Multi-object batch unwrapping with global texel density preservation** | How texel density is currently computed per object and what "global" means across objects of different scale | A batch run on several objects asserting the density target is met globally, with the measured values recorded |

Constraints that stay in force for F1–F4:

- One module per change; no renames of `intelligent_uv_settings`, the
  `IntelligentUV_*` classes, operator ids, panel or `bl_category`.
- No new dependencies beyond `bpy`, `bmesh`, `mathutils`, `numpy`; RizomUV stays
  optional and lazily imported.
- F2 cannot claim cross-platform parity: the live link remains Windows-only and
  requires a licensed install.
- None of these features may be used to justify a release number bump before the
  gate that exercises it exists.

### 8.3 Validation — G2 and G3 closed in an interactive desktop session

These two gates are closed only by a human on a desk, not by a headless run.
Both were closed that way on 2026-10-23; the verdicts and the dated evidence
are registered in §3 and §3.1.

- **G2 — RizomUV manual round trip: PASS — 2026-10-23 — RizomUV 2025.0.117 —
  match 500/500.** Suzanne desktop round trip: Export & Open → unfold and pack
  in RizomUV 2025.0.117.g4c8bab02 → save → Import UV from FBX; layer
  `SmartUV`, 500/500 faces matched, 1968 loops written, 0 unmatched, backup
  layer `SmartUV_backup` created.
- **G3 — clean install lifecycle: PASS — 2026-10-23 — Blender 5.2.0 LTS
  (fbe6228777e7) — ZIP sha256 df81d098...93a1.** Fresh configuration, ZIP
  install, restart, enable, Check Mesh clean, disable, re-enable, restart,
  enable, remove — console clean at every step. Blender 4.2 LTS branch:
  **NOT EXECUTED** (4.2 LTS absent on this machine) and stays open.
- The dated logs stay with the release; a passing UI is not evidence if the
  console shows a traceback.
- What remains open is G1 and the Blender 4.2 LTS branch of G3. The public
  wording stays "manual, interactive, unverified headless" for the automated
  RizomUV engine (still behind the experimental toggle) and "tested on the
  logged Blender builds only" for the add-on: the PASS verdicts cover the
  manual flow on the named builds, not the headless suites.

---

## Appendix — revision history of this file

**Latest revision** adds section 8, *Post-0.34.0 Development & GitHub
Publication Plan*: the GitHub-ready publication inputs with their current state
(read from the tree), the four planned feature areas (UDIM/multi-tile packing,
interactive RizomUV live bridge, seam pinning in Edit Mode, multi-object batch
unwrapping with global texel density) each with the question to settle before
implementation, and the restatement that G2 and G3 require an interactive
desktop session. That requirement was met on 2026-10-23: both gates closed
with PASS verdicts registered in §3.1 and restated in §8.3 (G2: RizomUV
2025.0.117, match 500/500; G3: Blender 5.2.0 LTS, ZIP sha256 df81d098...93a1 —
the Blender 4.2 LTS branch of G3 was not executed). It is a plan: the feature
items certify no gate and schedule nothing, and it does not lift the section 6
non-goal for the 0.34.0 baseline.

**This revision** restructured the document around three evidence classes and
reordered the phases so the manual release gate comes first. It added: the
handling of the v0.33.0 → v0.34.0 report and its four claims; the RizomUV manual
flow and the decision on the experimental engine; the licence/title distinction
with the audit limits from `THIRD_PARTY.md`; the research-before-manifest rule
and the 5.2/4.2 target statement; the clean-install lifecycle including
disable/enable and console checks; the user-flow README; the distribution
decision with the private-repository and free-showcase constraints; and the
portfolio case study with its authorisation gate. The old phases were not
deleted as work items: repository hygiene moved into Phase 3, documentation into
Phase 6, pipeline coverage into section 5, and CI into Phase 9.

**Before that**, this file was a feature plan written against 0.16.0. It
described `tests/test_core.py` as a 40-check suite at a time when that file no
longer exists, listed symmetry-aware seams and UDIM as future work although
`symmetry.py` and `udim.py` are present and documented, and still called RizomUV
script parameters unverified while later README notes record a
parameter-by-parameter check on 2025.0.117. That content is superseded, not
deleted from history: the changelog remains the record of what was built.
Feature ideas are not scheduled here; if resumed, they must be re-checked
against the code.
