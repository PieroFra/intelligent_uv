# Changelog

## 0.34.0 — Registration is idempotent; face reads portable; overlap checked per region; author and licence recorded

This is the baseline `bl_info` declares. Two limits apply to this entry, and
both are deliberate:

- There is **no 0.18.0 – 0.33.0 history in this file**; the repository begins
  with a single import commit of 0.34.0. Nothing about that span is written here
  because nothing about it can be read from the tree.
- Work that `README.md` describes for this version without a test or a log
  behind it — the island-grouping and post-unwrap timings, the nested-island
  containment fix, the Otsu crease-threshold fix — is recorded in `ROADMAP.md`
  section 2 as **reported, not reproduced**. It is not repeated here as a
  released change until Phase 1 reproduces or refutes it.

**Fixed**

- `register()` is now callable more than once in the same session. The guard
  looked for registered classes under `cls.__name__`, but operators are
  registered under `bl_idname`, so the second call failed part-way and left the
  scene without `Scene.intelligent_uv_settings`. The module now records what it
  registered (`_registered_classes`), removes that list before registering
  again, looks each class up under the name Blender actually uses
  (`_registered_name`) and detaches the Scene pointer before the
  `PropertyGroup` behind it is replaced. Scene settings are snapshotted before
  the pointer is dropped and written back after it is re-attached.
- Face centres and normals are now read portably across Blender 4.2 and 5.2.
  Both were read behind a `hasattr(value, "__iter__")` guard that a
  `mathutils.Vector` does not satisfy on every build (5.2 reports none), and
  the guard failed silently: the analysis kept its all-zero default centres and
  a `(0, 1, 0)` fallback normal per face without a word. With every centre at
  the origin, symmetry detection hashed all faces into a single bucket and
  degraded to comparing every pair, and the seam planner's concave-edge
  preference had no position to work with. The reads are now indexed
  (`value[0..2]`) inside `try/except`, and each pass appends one aggregated
  warning naming how many of the mesh's faces could not be read.
- Overlap verification on the external path now runs at seam-region
  granularity instead of mesh-component granularity. `_analyze_islands`
  validates the planner's per-face `region_ids` against the polygon count and
  uses them whatever the path, since they survive the RizomUV round trip; it
  warns explicitly when it has to fall back to mesh components. Component
  outlines merged unrelated seam regions into a single polygon, which made the
  candidate and containment check of the overlap test meaningless on
  multi-component meshes.

**Changed**

- `bl_info["author"]` is `Pierfrancesco Diodato` instead of the placeholder
  `"Your Name"`.
- Distribution terms are recorded instead of assumed: `LICENSE` states
  GPL-3.0-or-later, `THIRD_PARTY.md` inventories what comes from elsewhere (two
  development scripts carried over from the sibling ACTD project, and
  `RizomUVLink`, MIT and **not vendored**), and `README.md` carries a *License &
  attribution* section pointing at both. The licence states the terms of
  distribution; it is not proof of title over every line, and `THIRD_PARTY.md`
  says so itself.

**Verification**

- Smoke suite `.opencode/tests/smoke_test.py`, run through
  `.opencode/scripts/run_tests.ps1`: **14 checks, 14 passed, 0 failed** on
  Blender 5.2.0 LTS (hash `fbe6228777e7`, built 2026-07-14), unchanged by the
  fixes in this entry. The `doppio_register` and `re-register` checks are the
  ones that exercise the registration fix.
- Pipeline suite `.opencode/tests/pipeline_test.py`, same runner and build:
  **7 checks, 7 passed, 0 failed** — three negative paths (no active object,
  non-mesh object, empty mesh) plus the native pipeline on cube, cylinder and
  sphere, with UV-range, density and angle assertions.
- Scope of the two suites: the smoke suite covers compilation, import,
  `bl_info`, registration and re-registration, the Scene pointer,
  class/operator/property counts, the panel and unregister; the pipeline suite
  covers the native pipeline on primitives only. Neither executes the
  external/RizomUV path, and neither runs on the gate asset.
- Release gates are **not** closed by these suites. G1 and G3 have dated
  headless exploratory runs (2026-10-23) that are non-gate by the project rule;
  G2 needs an interactive desktop session with RizomUV. The evidence and the
  remaining work are listed in `ROADMAP.md` §3.1.

**Formal gate closure**

- **G2 PASS — 2026-10-23 — RizomUV 2025.0.117 — match 500/500.** Manual round
  trip on Suzanne (Blender GUI + RizomUV): Export & Open, unfold and pack in
  RizomUV, save, Import UV from FBX — layer `SmartUV`, 500/500 faces matched,
  1968 loops written, 0 unmatched, backup layer `SmartUV_backup` created.
  Class (c) verdict, registered in `ROADMAP.md` §3/§3.1.
- **G3 PASS — 2026-10-23 — Blender 5.2.0 LTS (fbe6228777e7) — ZIP sha256
  df81d098...93a1.** Clean install lifecycle on a fresh configuration: install,
  restart, enable (Intelligent UV panel populated, Check Mesh clean), disable,
  re-enable, restart, enable, remove — no traceback at any step. Blender 4.2
  LTS branch: NOT EXECUTED (4.2 LTS absent on this machine). Class (c) verdict,
  registered in `ROADMAP.md` §3/§3.1.

## 0.17.2 — Nothing ever lands outside the 0-1 tile

**Fixed**

- UVs overflowing the tile after a RizomUV run: when the layout does not
  fit, RizomUV's packer grows the packing box instead of shrinking the
  islands, and the post-layout scaling that would force a fit
  (`LayoutScalingMode`) is not reachable through the 2025.0 link API
  (rejected in `Global`, absent from the RootGroup/Tile property tables).
  `import_uvs_from_fbx` now checks the copied UVs against the tile and
  uniformly rescales and recentres the layout into it — margins respected,
  island proportions preserved — on every path: live link, Lua script and
  manual FBX import. Verified on a 47k-face production mesh: bounds went
  from U [-0.56, 3.96] to U [0.003, 0.997], zero loops outside.
- Live link startup: when the RizomUV launch wait timed out, the
  half-started instance was left running and every later launch timed out
  as well. The bridge now picks the link port itself, kills the orphaned
  instance on startup failure and tells the user to close other RizomUV
  instances.

**Added**

- Unfold failures are now surfaced: RizomUV reports islands it cannot
  flatten (`BijectionFailedIslandIDs`, typically non-manifold or
  degenerate geometry) through the command payload, not as an error, so
  they used to pass silently. The run report now warns how many islands
  kept their pre-computed UVs.
- Pre-flight mesh-quality warning: after the mesh analysis, the operator
  reports the non-manifold edge count and points to Mesh > Clean Up >
  Merge by Distance and Select > All by Trait > Non Manifold.

## 0.17.1 — Correct RizomUV packing at any texture resolution

**Fixed**

- RizomUV packs were executed with whatever padding, margin and map
  resolution the previous RizomUV session had stored: the `MarginSize`
  passed to `Pack` is a UV-unit value that RizomUV ignores while
  `UsePixelUnit` is on (its factory default), so a 4K target got the
  margins of a 2K session — or none at all. The bridge now writes
  `MapResolution`, `UsePixelUnit`, `PaddingSizePx`, `MarginSizePx` and
  `Scaling.Mode` directly into the document at
  `Lib.Mesh.RootGroup.Properties.Pack` (verified against RizomUV
  2025.0.117) before packing, on both the live-link and the Lua-script
  engine.
- `Scaling.Mode` is now explicitly `0` (OFF): RizomUV no longer
  re-averages island scales during the pack, so the texel-density
  normalization computed by the add-on is preserved instead of being
  silently replaced. (Side effect: RizomUV's density-spread metric in the
  stress test moved from 10.3% to 80.6% — the old number was RizomUV
  overriding our normalization; the new one is comparable to the native
  one and driven by the same degenerate-face outliers.)
- Lua script engine: the generated script now ends the process cleanly
  (`ZomSet` + corrected `ZomPack` parameters; previously it hung until
  killed at the timeout).

## 0.17.0 — Crash-proof RizomUV live link

**Fixed (freeze)**

- Live link commands (`Load`, `Unfold`, `Optimize`, `Pack`, `Save`) now run
  on a worker thread instead of Blender's UI thread. Previously a RizomUV
  crash mid-command left Blender parked forever inside a blocking socket
  call; the modal timeout could only fire *between* commands.
- The bridge finds the RizomUV PID from the link port and watches it on
  every modal tick: if RizomUV dies or is closed mid-run, the failure is
  reported and the native unwrap is kept — no freeze, no zombie wait.
- A single command that exceeds the timeout now kills the hung RizomUV
  process and degrades to the native result.
- ESC and the overall timeout hard-kill the link process (a graceful `Quit`
  would block on a busy app); `Quit` is skipped when the process is already
  gone.

**Added**

- New "Keep RizomUV Open" option: leaves RizomUV running after the run so
  the result can be inspected in its viewport. Off by default (RizomUV is
  closed automatically, and the completion message now says so explicitly).
- Per-step progress messages ("RizomUV: unfolding islands…") so a long run
  shows what it is doing.
- Early warning when the target mesh exceeds 1M faces: RizomUV may take a
  long time or run out of memory.

## 0.16.0 — Stability & performance

**Fixed (crash / hang / data loss)**

- RizomUV bridge: stdout/stderr now go to a log file instead of an undrained
  `subprocess.PIPE`; a full pipe buffer blocked the child process and every
  run died at the timeout. The log is read back on failure and kept with the
  temp files.
- `cancel()` dispatches on the bridge mode; the live-link RizomUV instance is
  no longer left running when a run is cancelled.
- Modal polling failure path returns `FINISHED` instead of `CANCELLED`, so
  Blender no longer discards seams and UVs already written to completed
  objects (UNDO semantics).
- FBX import cleanup no longer lets a `ReferenceError` from a removed object
  mask the real exception.
- Batch queue: objects deleted after the queue was built are reported as
  failed instead of raising `ReferenceError`.
- Overlap test: island outlines only + uniform-grid broad phase + hard
  comparison cap. The previous all-edges O(n·m) test froze Blender for
  minutes on large islands.
- `_segments_intersect`: point contacts (shared endpoints, touching borders)
  are no longer reported as overlaps.

**Performance**

- Bulk `foreach_get`/`foreach_set` for UV backup, coverage scaling, texel
  density normalization, island extraction, distortion analysis, FBX UV
  copy-back, seam marking, material grouping and edit-mode selection.
- Union-find for connected components and post-cut regions (was set
  adjacency + flood fill).
- Queue-driven O(E) dangling-seam pruning (was O(E²)).
- Vectorized numpy dihedral angles in the curvature estimator and the seam
  planner, via `face_normals_np` on the analysis result (scalar fallback
  kept).
- Region merging concatenates face lists in place.

**Added**

- `tests/test_core.py`: 44-check suite for the pure-logic modules, runnable
  outside Blender (`python tests/test_core.py`).
- `tests/e2e_smoke.py`: end-to-end smoke test running inside Blender
  (registration, full pipeline on cube/cylinder/Suzanne/66k-face grid, batch,
  dry run, diagnostics).
- `tests/rizomuv_roundtrip_test.py` and `tests/rizomuv_api_probe.py`: live
  RizomUV round-trip test and API parameter probe.
- `ROADMAP.md`: phased improvement plan.

**RizomUV integration (verified against RizomUV 2025.0.117)**

- Live link command parameters probed empirically and fixed: `Unfold` no
  longer sends `ProcessNonFlats`/`ProcessSelection`, `Pack` no longer sends
  `SpacingSize`; Load/Save use the flat dotted keys from Rizom-Lab's official
  examples; `Quit({})` matches the examples. Full round trip passes with 100%
  face matching.
- The RizomUVLink module bundled in the RizomUV install folder is now added
  to `sys.path` automatically (exe-dir first, then the standard install
  root), so the live link works without manual Python path setup.
- Seam planner: the concave ridge bias can no longer push the effective
  threshold past the mesh's sharpest dihedral angle — a cube (uniform 90°
  edges, 81° fallback threshold, +15° bias) previously got zero seams.
