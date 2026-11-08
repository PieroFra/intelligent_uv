# PROMO: Intelligent UV Mapping 0.36.0

Blurb (EN, dry tone, no em-dashes):

---

## Intelligent UV Mapping 0.36.0

Intelligent UV Mapping is a Blender 4.2+ add-on that plans and executes UV
unwraps from mesh analysis: curvature, seam placement, region clustering and
UDIM-aware packing, either fully inside Blender or with an optional RizomUV
hand-off.

### Highlights

- **Region topology completed off-disk**: the non-disk region completion step
  runs on the mesh topology in memory; island boundaries are derived from the
  seam graph rather than from intermediate disk exports.
- **Curvature-driven clustering**: seam placement and region grouping follow
  the curvature field of the mesh, so coherent surface patches stay together.
- **UDIM support**: multi-tile layouts are packed across UDIM tiles with
  explicit tile assignment in the unwrap plan.

### Two editions, one source tree

- **Full edition (GitHub)**: everything above plus the optional RizomUV
  integration (Live Link, Lua Script and Auto round trips, Windows only,
  loaded lazily and only when an external engine is requested).
- **Blender-only edition (Blender Extensions)**: the same pipeline with the
  RizomUV modules physically absent from the package and the external engine
  capability disabled. No new dependencies: it uses only `bpy`, `bmesh`,
  `mathutils` and `numpy`, which ships with Blender.

The two editions are built from the same source; the native build script
excludes the three `rizomuv_*` modules and pins the external engine off.

### Links

- GitHub release: https://github.com/PieroFra/intelligent_uv/releases/tag/v0.36.0
- Blender Extensions: submitted, status Awaiting Review (permissions: Files
  only). The listing page will be linked here once published.

### Verification summary

- Smoke suite 14/14, regression suite 60/0 on Blender 5.2.0 LTS (headless).
- UI probe: 88 labels, flagged=0, in Italian and English.
- Clean install gate of the native edition passed on the published ZIP.

No benchmark claims: the suites above run on primitives and synthetic
setups; see VERIFICATION.md for what was actually measured and what is
carried over from earlier releases.
