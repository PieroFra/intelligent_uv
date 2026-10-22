# Intelligent UV Mapping — Improvement Roadmap

This document tracks where the add-on is going: what was just fixed, what
comes next, and in which order. It is written to be shown — each phase lists
the *why*, not just the *what*, so it can double as a technical breakdown for
a portfolio piece.

Current version: **0.16.0** · targets Blender 4.2+

---

## Phase 0 — Stability & performance foundation (DONE, 0.16.0)

The goal of this phase was simple: nothing may crash, hang, or silently
corrupt data, and the pipeline must stay interactive on production-density
meshes (100k–1M faces).

**Crash / hang fixes**

| Issue | Root cause | Fix |
|---|---|---|
| RizomUV run always died at timeout | `subprocess.PIPE` never drained → child blocks at ~64 KB of output | stdout/stderr redirected to a log file, read back on failure |
| Live-link RizomUV leaked on cancel | `cancel()` called the script engine's `terminate` on a link context | mode-dispatched terminate + cleanup |
| Real error masked on FBX import | `imported_obj.name` raises `ReferenceError` inside `finally` | guarded name access |
| Completed work lost on modal failure | exception path returned `CANCELLED` with `UNDO` enabled | returns `FINISHED` after cleanup |
| Blender froze minutes on overlap check | O(n·m) segment test over *all* face edges | outline-only segments + uniform-grid broad phase + comparison cap |
| False overlap reports | zero orientation treated as a side in the sign test | strict orientation-product test |

**Performance work**

- Every per-element RNA loop replaced by bulk `foreach_get`/`foreach_set`
  (UV backup, coverage scaling, texel density, island extraction, distortion
  analysis, FBX copy-back, seam marking, material grouping). One RNA call per
  attribute instead of one per loop/edge/face.
- Connected components and post-cut regions: set-adjacency + flood fill →
  single-pass union-find.
- Dangling-seam pruning: O(E²) valence rebuild → O(E) queue-driven pruning.
- Dihedral angles: per-edge Python → one vectorized numpy pass over
  `face_normals_np` (scalar fallback kept, tested to agree within 1e-6°).
- Region merging: O(F²) list copies → in-place `extend`.

**Verification**

- `tests/test_core.py`: 40 checks over the pure-logic modules, runnable with
  a plain Python interpreter (no Blender needed) via a `bpy` stub.

---

## Phase 1 — Seam quality (next)

Seam placement is the single biggest quality lever; everything downstream
(unwrap, packing, density) only executes what the planner decided.

1. **Valley-following seams.** Replace the hard per-edge angle threshold with
   a path-based planner: build the dual graph of the mesh, weight edges by
   dihedral angle × concavity × length, and grow seams along minimum-cost
   paths between feature points — the way an artist runs a seam along a
   crease instead of cutting every edge above N degrees.
2. **Symmetry-aware seams.** Detect the mesh's mirror plane (vertex-position
   voting is enough for hard-surface assets) and mirror seam candidates across
   it, so mirrored assets get identical islands on both sides.
3. **Smarter non-developable splitting.** The current splitter cuts the
   sharpest interior edges; for tubes it should find the *shortest ring* of
   edges around the axis (a min-cycle in the dual graph), which produces the
   clean, single straight cut an artist would make.
4. **Seam preview overlay.** Draw planned seams in the viewport *before*
   writing them (gpu module), with live update while sliders move. Turns
   tuning from guess-run-undo into direct feedback. Strong demo material.

## Phase 2 — Layout quality

1. **Real fill-efficiency metric.** Report actual UV space usage (sum of
   island areas / used tiles) instead of bounding-box coverage, and warn when
   packing efficiency drops below a threshold.
2. **UDIM support.** Multi-tile layouts when islands overflow one tile, with
   per-tile density accounting. Required for film/VFX workflows; game
   workflows stay single-tile.
3. **Per-group texel density targets.** Let material groups carry a density
   multiplier (hero parts at 2×, hidden parts at 0.5×) instead of one global
   uniform density.
4. **Oriented packing hints.** Align dominant island axes before packing
   (PCA on island UVs) to improve fill on hard-surface assets.

## Phase 3 — RizomUV integration hardening

1. **Verify the Lua API against a real install.** The script path is still
   unverified (see README known issues); validate `ZomLoad/ZomPack/ZomSave`
   parameters against the installed version's documentation and record the
   working set per RizomUV version.
2. **Prefer the live link everywhere it exists**, keep the script path only
   as a documented fallback; auto-detect the RizomUV executable in standard
   install locations instead of shipping a hard-coded path.
3. **Round-trip groups.** Export material groups as FBX groups so RizomUV
   sees the same grouping the planner used.
4. **Cancellation propagation.** ESC currently abandons the external process;
   the link path should also send a Cancel command so RizomUV stops its own
   solve immediately.

## Phase 4 — Engineering & distribution

1. **Headless CI.** Run the test suite plus an end-to-end smoke test
   (`blender -b -P tests/e2e_smoke.py`: primitive meshes → full pipeline →
   assert islands, density spread, no overlaps) on GitHub Actions across
   Blender 4.2 / 4.5 / 5.x.
2. **Benchmark harness.** Timed runs on reference meshes (1k / 50k / 500k
   faces) stored as JSON history, so performance regressions show up in
   review instead of in user reports.
3. **Typed results.** Convert the result classes (`MeshAnalysisResult`,
   `SeamPlanResult`, …) to dataclasses with slots — less memory, attribute
   typos become errors instead of silent `getattr` defaults.
4. **Blender Extensions format.** Ship as a `blender_manifest.toml`
   extension (the 4.2+ standard) in addition to the legacy zip, enabling
   one-click install and updates from a repository.

## Phase 5 — Portfolio packaging (ArtStation)

1. **Before/after gallery.** Same asset: Blender Smart UV Project vs this
   pipeline vs hand-placed seams — islands count, density spread, angle
   error, packing efficiency side by side.
2. **Annotated breakdown.** One hero asset walked through the pipeline stages
   (seam plan → merge → unwrap → density → pack) with the overlay from
   Phase 1.4 as the key visual.
3. **Short demo video.** 60–90 s: hard-surface asset and organic asset,
   real-time seam preview, one-click run, RizomUV round trip.
4. **Technical write-up.** The design decisions in the README (normal-cone
   merging, spatial copy-back, why FBX can't carry seams) are already written
   like a postmortem — they adapt directly into the project description.

---

## Working agreements

- Every user-facing output keeps stating the add-on version.
- New geometry access is bulk-first (`foreach_get`/`foreach_set`) with a
  documented fallback; no new per-element RNA loops.
- New pure logic ships with tests in `tests/`; the suite must pass before a
  version bump.
- External-process work stays phased and modal; nothing blocks Blender's
  main thread.
