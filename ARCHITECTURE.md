# Intelligent UV Mapping: Architecture (Developer Guide)

This file is the developer-facing architecture note for the 0.35.0 tree: how the
pipeline is laid out, what every module owns, and the design decisions a
contributor must know before changing things. The user-facing documentation
lives in [README.md](README.md); the change history lives in
[CHANGELOG.md](CHANGELOG.md) and [ROADMAP.md](ROADMAP.md).

## Pipeline Overview

```
Scene.intelligent_uv_settings (properties.py)
                |
        operators/run.py   (modal Run operator, mixins: batch, external, native)
                |
   +------------+----------------+---------------------+
   |            |                |                     |
 native      external          check / diagnose    preview_ops
 unwrap        |                 (preflight)           |
   |           |                                        |
   |    rizomuv_bridge.py (FBX export, spatial copy-back) |
   |           |          + manual_io.py (Export & Open / Import UV)
   |     rizomuv_link.py (Live Link socket)              |
   |     rizomuv_script.py (Lua -cfi launch)             |
   |           |                                         |
   v           v                                         v
 mesh_analysis -> curvature -> auto_params -> preflight
   |
 symmetry -> vsa (VSA clusters) -> seam_planning -> region_merge
   |                        RegionSplitter -> seam_marking
   v
 uv_executor (unwrap, minimize_stretch, packing)
   |        <- island_extraction + orientation (rotation before packing)
   |
 texel_density (normalize, global target across a batch)
   |        <- udim.py (UDIM tiles), texture_sets.py, stacking.py
   v
 validation -> distortion (coverage vs efficiency) -> margins
```

The pipeline is strictly layered: analysis modules read the mesh and produce
plain data results, planning modules consume those results, and only
`uv_executor` and `seam_marking` write anything back. Every busy step of the Run
operator runs through `modal()`, so the UI stays alive and ESC can abort at any
phase boundary.

## Module Map (41 files)

| File | Responsibility |
|---|---|
| `__init__.py` | `bl_info`, `CLASSES`, `register()`/`unregister()`, reload guard |
| `properties.py` | `PropertyGroup` on `Scene.intelligent_uv_settings`, all user data |
| `ui.py` | `VIEW3D_PT_IntelligentUV` panel, `_EnglishLayout` proxy, credits popup |
| `operators/base.py` | Abstract `IntelligentUVBaseOperator` (never registered) |
| `operators/run.py` | Modal Run operator, composed from the three mixins below |
| `operators/batch.py` | Queue mixin: drain a list of objects, one item per state |
| `operators/external.py` | External mixin: drive the RizomUV round trip across timer callbacks |
| `operators/native.py` | Native mixin: run the unwrap pipeline inline, texel density |
| `operators/preview_ops.py` | Apply / discard operators for the captured preview state |
| `operators/check.py` | `Check Mesh`: actionable mesh check without running the pipeline |
| `operators/diagnose.py` | `Diagnose Mesh API`: API, topology path, thresholds report |
| `operators/seams.py` | Edit-Mode operator that marks planned seam candidates |
| `operators/__init__.py` | Package marker; the concrete operators register from here |
| `mesh_analysis.py` | Bulk geometry reads (`foreach_get`), topology via bmesh |
| `material_analysis.py` | Material slots, face-to-material grouping |
| `curvature.py` | Dihedral angles, curvature distribution, per-edge sharpness |
| `auto_params.py` | Derived settings: Otsu tolerance, crease pull, minimum island size |
| `preflight.py` | Pre-run diagnosis: blockers, warnings, remedies per finding |
| `symmetry.py` | Symmetry plane detection, mirror seam transfer |
| `vsa.py` | Variational shape approximation: clusters whose borders become seams |
| `seam_planning.py` | Region borders plus explicit seam rules into seam decisions |
| `region_merge.py` | Normal-cone merge, region splitter for non-developable regions |
| `seam_marking.py` | Real `use_seam` marking, dangling seam pruning, concave bias |
| `uv_executor.py` | Native unwrap, relaxation, packing with verified layer activation |
| `island_extraction.py` | Island outlines and bounding data for later passes |
| `orientation.py` | Island rotation before packing (rotating calipers, exact fit) |
| `texel_density.py` | Texel density normalization, global target density across a batch |
| `udim.py` | UDIM tile assignment and per-tile offsetting |
| `texture_sets.py` | Per-material texture sets, per-set packing, overlap exemption |
| `stacking.py` | Signature-based island stacking for repeated parts |
| `distortion.py` | Distortion metrics, coverage and efficiency (`measure_fill`) |
| `utils.py` | Shared helpers: logging, geometry utilities, Blender version fallbacks |
| `validation.py` | Post-run quality validation: collapsed islands, overlaps |
| `margins.py` | UV margin computation and edge-length caps |
| `recovery.py` | Re-cut islands the solver failed on, one island at a time |
| `preview.py` | Capture / apply / discard of seams and UV layer state |
| `presets.py` | Inert JSON presets with allow-list validation |
| `manual_io.py` | Manual Export & Open / Import UV from FBX (operator usable alone) |
| `rizomuv_bridge.py` | FBX export, external process phases, spatial UV copy-back |
| `rizomuv_link.py` | Rizom-Lab `RizomUVLink` socket API wrapper (lazy, Windows-only) |
| `rizomuv_script.py` | Generated Lua script path: `-cfi` launch with `ZomQuit` at the end |

## Design Notes

### VSA regions and the Otsu threshold

`vsa.py` grows faces into clusters whose normals stay within a tolerance of the
cluster's running, area-weighted average normal; the borders between clusters
are the seams. The tolerance is not a magic constant: `auto_params.py` computes
it as the Otsu break in the model's own dihedral distribution, which is the
angle at which the mesh itself stops being one surface. The minimum island size
is derived from the margin instead, since an island smaller than its own padding
is waste whatever the geometry looks like. A relative measure versus the Otsu
break was deliberately rejected for crease pull: Otsu splits whatever it is
given, so it always finds a sharp half. Crease pull counts edges folding past
30 degrees, which is a fact about the geometry rather than about the
distribution.

### Overlap spatial filter and the nested-island check

The overlap build once priced 3.3 million dictionary inserts on a 315-island
layout because the segment index for island B was rebuilt for every candidate
pair. It is now built once per island and cached. A cheap filter then discards
most segments before any grid lookup: two outlines can only cross inside the
rectangle their bounding boxes share, and on a packed layout that strip is a
sliver, four comparisons per segment. Its measured effect was 3.78s to 0.36s on
the same data. The trimmed list is used only for the crossing test;
containment keeps the full data, because a nested island may contain exactly
the point a trimmed island lost, a case the first version of the filter broke
silently. Point contacts (islands touching at a margin) are not overlaps.

### The Run operator mixins: `batch.py`, `external.py`, `native.py`

One 1200-line operator used to hold four unrelated jobs: draining a queue of
objects, driving an external process across timer callbacks, running the unwrap
pipeline, and reporting. They now live in three mixins mixed into the operator
in that order. Mixins rather than helper objects because the methods genuinely
share operator state (`self._queue`, `self._bridge_ctx`, `self.report`), and
passing that between separate objects would invent plumbing to avoid a language
feature that fits. The busy flag is set through `type(self)` so the queue code
does not import the class it is mixed into. `modal_handler_add` runs once per
batch, not once per object: the handler is already registered when the queue
chains forward from inside `modal()`, and every relevant event would be
delivered twice.

### Texture sets versus UDIM tiles

Neither is better. Texture sets give each material its own image addressed by
the same 0 to 1 coordinates, so the sets overlap in UV space without colliding,
which is what a real-time engine that draws one material at a time wants, and
the overlap check is told to skip pairs belonging to different sets. UDIM lays
the images side by side in one continuous space, tile 1001 is 0 to 1, 1002 is
1 to 2 in U, which Substance and film renderers address natively. UDIM runs
last, when packing already finished inside 0 to 1: moving an island to tile N
is just adding an integer, so nothing in the packer needs to know how packing
was decided. Tiles follow material slot order, not island size, because
reordering slots must not reshuffle the texture the artist already matched.
Coverage scaling is skipped on a UDIM layout, since normalizing into the unit
square would collapse every tile back onto 1001.

### Non-destructive Preview state

Undo is not a safety net here: the run enters and leaves Edit Mode several
times, calls operators that push their own undo steps, and on the external path
shells out to another process, so Ctrl+Z lands somewhere unpredictable in the
middle of the pipeline. `preview.py` therefore captures state explicitly: the
seams go into a boolean edge attribute (not a Python list, which would not
survive saving and reopening the file with a preview still pending) and the
target UV layer is copied aside. Discard restores both exactly, including
deleting the layer entirely when the run was what created it. Apply drops the
records and keeps the result. While a preview is pending the panel shows only
Apply and Discard.

### RizomUV Live Link socket versus Lua `-cfi` with `ZomQuit`

Both engines reach the same `rizomuv_bridge.py` round trip. The Live Link path
uses Rizom-Lab's own published API, `RizomUVLink`, which exposes the real
commands (`Load`, `Unfold`, `Optimize`, `Pack`, `Save`, `Quit`) over a local
socket, so no syntax is guessed; it ships as a Windows-only wheel, and
`is_available()` gates the whole path so macOS and Linux fall back to the
manual Export/Import route, which needs no external library. The link runs one
command per modal tick because every API call is synchronous. The Lua Script
path launches RizomUV with `-cfi <script>`; that flag attaches a remote file
the process watches for changes, so in a headless run nothing would exit and
the run dies at `rizomuv_timeout`, whatever the script ends with. In desktop
sessions the generated script now closes the program itself with `ZomQuit` at
the end, and the bridge ends the external process at the timeout whenever it
never reaches that point. The external output goes to a log file, never to an
undrained `subprocess.PIPE`, which would fill its 64 KB buffer and block the
child forever.

### The `_EnglishLayout` proxy

The panel must read in one language. Part-translated labels appeared on
non-English Blender setups, because technical terms inside `label` strings went
through Blender's translation catalog. `_EnglishLayout` wraps the layout that
draws the panel and writes every string with `translate=False`, so labels and
operator descriptions stay in English whatever the interface language. The UI
probe measures all 86 panel labels with `blf.dimensions` and reports
`flagged=0`.

### Why there is no automatic reload

Reloading submodules on re-import looks convenient and crashes Blender:
`properties.py` defines the `PropertyGroup` that
`bpy.types.Scene.intelligent_uv_settings` points at, so reloading it builds a
new class while RNA still references the old one. Once the old module is
collected, that pointer dangles and Blender dies outright rather than raising.
The same applies to every registered operator and panel. Reinstalling the
add-on requires restarting Blender, and `register()` says so when it detects a
stale load. The reload guard discovers submodules from `sys.modules` (a
hand-written list goes stale the moment a module is added) and reports a failed
reload instead of swallowing it.

## Verification

Automated headless suites: `.opencode/tests/smoke_test.py` (14 checks:
registration, panel, operators, properties, unregister) and
`.opencode/tests/pipeline_test.py` (13 checks: negative paths, native unwrap on
primitives, UDIM tiling, seam preservation, Edit Mode guard, global texel
density, bridge contract, English UI and credits). The RizomUV round trip is
not verified headlessly: it is closed in interactive desktop sessions, recorded
with dated evidence in [VERIFICATION.md](VERIFICATION.md) and
[ROADMAP.md](ROADMAP.md).
