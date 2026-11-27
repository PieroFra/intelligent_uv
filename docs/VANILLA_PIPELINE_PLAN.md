# Vanilla / Blender-Only UV Pipeline Improvement Plan

## 1. Blender Extensions Compliance (Completed in `build_extension_native.ps1`)
- The Native extension build (`dist/intelligent_uv-0.36.3-nativo-extension.zip`) now strips all RizomUV and `ExternalEngine` leftovers during staging:
  - Excludes `rizomuv_bridge.py`, `rizomuv_link.py`, `rizomuv_script.py`, and `operators/external.py`.
  - Removes `ExternalEngineMixin` from `operators/run.py` and stubs `_start_external` to `None`.
  - Removes `rizomuv_path` (EXE picker) and all `rizomuv_*` / `use_rizomuv` / `link_*` properties from `properties.py` and their UI blocks from `ui.py`.
  - Removes `rizomuv_bridge` imports and `rizomuv_path` reads from `manual_io.py`.
  - Enforces a ZIP-wide static regex gate (`ExternalEngine|rizomuv_bridge|rizomuv_link|rizomuv_script|rizomuv_path|rizomuv_exe`) so no residue can ever ship to Blender Extensions.
- **Note for re-submission on Blender Extensions:** since the old 0.36.0 listing was marked "will not be reviewed again", publish the clean Native ZIP as a fresh Blender-only extension submission (with a clean description and manifest mentioning Blender-only native UV unwrapping).

## 2. Concrete Plan to Strengthen the Vanilla / Blender-Only Pipeline
Grounded in the current modules (`seam_planning.py`, `region_merge.py`, `uv_executor.py`, `texel_density.py`, `distortion.py`):

1. **Multi-Pass Unwrap + Distortion-Guided Seam Refinement (`uv_executor.py` + `distortion.py`)**
   - After the first native ABF/LSCM unwrap (`bpy.ops.uv.unwrap`), measure per-island angular and area distortion via `distortion.py`.
   - For any island exceeding a configurable stretch threshold (or failing unwrap), automatically insert a secondary relief cut along the longest interior high-curvature edge path and re-unwrap only that island.
2. **Island Straightening for Cylindrical / Strip Shells (`uv_executor.py`)**
   - Detect quad-grid / cylindrical UV islands (common on hard-surface props like barrels, pipes, grips) and apply a native follow-active-quads / rectilinear straightening pass before packing to dramatically improve packing efficiency and reduce aliasing.
3. **Orientation & Gravity Alignment (`orientation.py` + `uv_executor.py`)**
   - Align major UV islands to their principal 3D axis (world Z-up / longest edge) before `bpy.ops.uv.pack_islands` so wood grain, brushed metal, and decals flow consistently without manual rotation.
4. **Adaptive Packing with Overlap Self-Check (`uv_executor.py` + `distortion.py`)**
   - Use Blender 4.2+/5.2's native `pack_islands(shape_method='CONCAVE', margin_method='FRACTION', rotate=True)` when available (with fallback), then run the B3 containment/overlap detector (`test_overlap_containment.py` logic) to catch and separate any nested or overlapping islands automatically.
5. **Deterministic Benchmark (`tools/benchmark_uv.py`)**
   - Track coverage %, texel density variance, angular stretch, overlap count, and runtime across standard meshes (Suzanne, Cylinder, Torus, and `bolt_action_rifle_7_62`) on every change to prove vanilla quality gains quantitatively.
