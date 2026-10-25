# Intelligent UV Mapping: Blender Add-on

Automated UV unwrapping for Blender: curvature-driven seam planning, island
merging, texel density normalization, and an optional bridge to RizomUV.

Version 0.35.0 · targets Blender 4.2+ · tested against Blender 5.2 LTS
Author: Pierfrancesco Diodato · License: GPL-3.0-or-later

---

## What It Does

- **One-click unwrap with a non-destructive preview.** A single button runs the
  whole pipeline: analysis, seam planning, unwrap, packing and the quality
  report. Preview keeps the result pending until you Apply or Discard it, and
  Discard restores both the hand-placed seams and the previous UV layer
  exactly.
- **Shape clustering (VSA) and curvature seams.** Faces grow into clusters whose
  normals stay within a tolerance of the cluster's running, area-weighted
  average, so seams follow the real structure of the surface instead of a raw
  angle threshold. Creases are preferred, material boundaries count, and
  regions that cannot flatten are opened along a shortest path.
- **Seam pinning in Edit Mode.** Seams placed by hand survive the pipeline
  instead of being overwritten, and the operators are guarded against being
  invoked in Edit Mode.
- **Global texel density across multi-object batches.** A batch of objects at
  different scales shares one world-space density target computed from the
  total area, so every object ends at the same density instead of each getting
  its own.
- **Texture sets and UDIM multi-tile packing.** Give each material its own
  image on the shared 0-1 space, or spread the layout across UDIM tiles (1001,
  1002, 1003...) in one continuous UV space. Tile assignment is verified
  collision-free and deterministic across re-runs.
- **Four ways to work with RizomUV** (optional; the three automated ones are
  Windows-only):
  - **Manual Export & Open / Import** writes the FBX, lets you unfold, pack and
    save in RizomUV by hand, then reads the UVs back. It needs no external
    library and works on every platform.
  - **Live Link** drives RizomUV through its official Python API
    (`RizomUVLink`) over a local socket, one command per modal tick, so
    Blender stays responsive while RizomUV works.
  - **Lua Script** writes a Lua script and launches RizomUV with it, for
    installs without the Python API.
  - **Auto** uses the Live Link when available and falls back to the Lua
    Script engine otherwise.

---

## Installation

Install the release ZIP (`intelligent_uv-0.35.0.zip`, attached to the v0.35.0
release on the GitHub releases page) through **Edit > Preferences > Add-ons >
Install from Disk**, or copy the `intelligent_uv` folder into your Blender
`scripts/addons` directory. The panel appears in the 3D View sidebar (N) under the
**Intelligent UV** tab.

**Reinstalling requires restarting Blender.** The settings live in a
`PropertyGroup` that `Scene.intelligent_uv_settings` points at; reloading the
modules would leave that RNA pointer dangling, which crashes Blender instead
of raising an error. `register()` warns when it detects a stale load.

---

## Quick Start

Select a mesh object, press **N** in the 3D View and open the **Intelligent UV**
tab. The whole workflow is in that panel:

1. **Check Mesh**: reads the mesh and reports what would spoil the unwrap, each
   finding with what to do about it. It changes nothing, so it is safe to run
   first and safe to run again.
2. **Unwrap / Preview**: **Unwrap** (`Run Intelligent UV`) runs the full
   pipeline: preflight, seam planning, unwrap, packing and the quality report.
   **Preview** runs the same pipeline but keeps the result pending until you
   press **Apply** or **Discard**; while a preview waits, the panel offers only
   those two buttons.
3. **RizomUV bridge / manual round trip** (optional). The **External Editor**
   box holds the RizomUV path, **Export & Open** (writes the FBX, with the
   planned seams traveling inside it as island borders, then launches RizomUV),
   **Import** (reads the UVs back from whichever of the two expected files is
   newer, no dialog) and **Import from...** (file browser for any other
   location). To automate the trip instead, enable **Automated RizomUV** under
   **Advanced > Tools**, inside the **RizomUV Bridge (Windows)** box, choose a
   **Mode** (**Auto**, **Live Link** or **Lua Script**) and set **Optimize in
   RizomUV** and **Keep RizomUV Open** as you prefer.
4. **License & Credits**: the button at the bottom of the panel opens the
   author, the licence, a quick guide and links to the GitHub repository, the
   Discord profile, the full GPL-3.0 text and the local README, CHANGELOG and
   LICENSE files.

The default view holds the preset menu, **Unwrap**, **Preview**, **Check
Mesh**, **Dry Run**, the **Layout** box (**Tex Size**, **Target Islands** with
**Detail** below it, **All Selected Objects**), the **External Editor** box
(path, **Export & Open**, **Import**, **Import from...**) and the **License &
Credits** button with the version. Everything else sits behind **Advanced** at
the bottom of the panel; the defaults and the presets are meant to cover most
assets, and those parameters are there for the assets they do not.

---

## RizomUV Integration: How to Choose the Right Mode

RizomUV (Rizom-Lab) is optional and the add-on works fully without it. All four
modes below were verified on Windows with RizomUV 2025.0.117; the automated
ones are Windows-only.

| Mode | What it does | When to use it |
|---|---|---|
| **Manual Round Trip** (`Export & Open` to `Import` / `Import from...`) | Exports `<name>_uv.fbx` with the planned seams already cut (they travel as UV island borders, because the FBX format has no seam flag) and opens it in RizomUV for hand work. **Import** reads the UVs back onto the `SmartUV` layer, saving the previous one in `SmartUV_backup`. | Works on every platform with no extra setup, and it is the easiest way to diagnose. This is the default behaviour. |
| **Automated: Live Link** | Drives RizomUV 2025+ through its official Python API (`RizomUVLink`) over a local socket, step by step (`Load` to `Set` to `Unfold` to `Optimize` to `Pack` to `Save`), one command per modal tick so Blender stays responsive while RizomUV works. Options: **Optimize in RizomUV** and **Keep RizomUV Open**. | One click, watched all the way. Windows only; RizomUV's Python API (`RizomUVLink`, included in the install) must be present. |
| **Automated: Lua Script** | Generates a `.lua` script and launches `rizomuv.exe` headless with `rizomuv.exe -cfi`, and the script closes the session itself at the end. | Installations of RizomUV whose version ships without the `RizomUVLink` Python API. |
| **Automated: Auto** | Uses the Live Link automatically when it is available and falls back to the Lua Script engine otherwise. | The recommended setting. Enable **Automated RizomUV** under **Advanced > Tools**, inside the **RizomUV Bridge (Windows)** box. |

The automated modes live behind the **Automated RizomUV** toggle, which is off
by default: the manual round trip leaves the external process entirely alone,
so a RizomUV crash cannot affect Blender.

---

## Advanced Controls Guide

Everything on the default panel has a sensible default. The sections below sit
behind **Advanced** at the bottom of the panel, for the assets where the
defaults do not fit.

- **Seams**: pick the seam **Method**. Shape Clustering (VSA) grows faces into
  clusters whose normals stay within a tolerance and cuts along the borders,
  with controls for refinement (**Refine**, **Smooth Borders**, **Hide in
  Creases**, **Min Faces**). Curvature uses an angle threshold with **Prefer
  Concave** (seams hide in valleys instead of showing on ridges),
  **Split Wrapped Regions** with a **Wrap Limit** (it opens closed shapes such
  as cylinders along a shortest path), and island merging with **Flatness**,
  **Absorb Micro Islands** and **Min Faces**. Both methods share **Symmetrize
  Seams** (the two halves of a symmetric model are cut identically), **Preserve
  Existing Seams** (hand-placed seams are never overwritten), **Separate by
  Material** and **Prune Dangling Seams**.
- **Result**: how the output is measured and laid out. **Run Preflight** with
  **Stop on Blockers** diagnoses the mesh before touching anything, and
  **Recover Failed Islands** re-cuts islands the solver could not flatten, on
  their own and without touching their neighbours. **Minimize Stretch** relaxes
  the interior of each island after the unwrap. For multi-material assets,
  **Texture Sets (per Material)** gives each material its own image addressed
  by the same 0-1 UV coordinates, which is what real-time engines want, since
  they draw one material at a time; **UDIM Tiles** instead spreads the layout
  across tiles 1001, 1002, 1003... in one continuous space with **Max Tiles**,
  which is what Substance and film renderers address natively. Then **Orient
  Islands** (islands are rotated before packing), **Stack Duplicates**
  (repeated parts share one patch of texture), **Normalize Texel Density**, the
  island **Margin**, **Coverage**, the **Backup UV Layer** with its **UV Layer**
  name, the distortion report and the overlap check.
- **Tools**: **Mark Seams** (only the seam planning step), **Diagnose Mesh API**
  (which mesh APIs this Blender build exposes, which topology path succeeded
  and where the pipeline would break; output goes to the System Console and to
  an `IntelligentUV_Diagnostic` text block), and the **RizomUV Bridge
  (Windows)** box: **Mode**, a live availability check for the Python API,
  **Optimize in RizomUV**, **Keep RizomUV Open**, **Timeout (s)** and **Keep
  Temp Files**.

---

## Verification & Status

- Smoke suite: **14/14**, 0 failed on Blender 5.2.0 LTS
  (`.opencode/tests/test_out.txt`) over import, registration including a second
  `register()` call in the same session, the panel, the operators, the
  properties exposed in the UI and unregister.
- Pipeline suite: **12/12**, 0 failed (`.opencode/tests/pipeline_out.txt`):
  the native pipeline on primitives, plus UDIM multi-tile packing, seam
  preservation, the Edit Mode guard, global texel density across a batch and
  the RizomUV link bridge contract.
- UI probe: **86 labels measured with `blf.dimensions`, flagged=0** in Italian
  and English (`.opencode/scripts/run_ui_probe.ps1`).
- **G2 PASS, 2026-10-23**: manual RizomUV round trip on Suzanne with RizomUV
  2025.0.117, 500/500 faces matched, 1968 loops written.
- **G3 PASS, 2026-10-23**: clean install lifecycle on a fresh Blender 5.2 LTS
  configuration with the release ZIP (sha256 `df81d098...93a1`).
- **RizomUV automated bridge, 2026-10-25**: the operator exercised **Auto**,
  **Live Link** and **Lua Script** in a real desktop session on Blender 5.2.0
  LTS with RizomUV 2025.0.117, with the headless `pipeline_link_bridge_contract`
  check passing alongside it.

The suites above run on primitives and synthetic multi-material setups; the
release gate on the CC0 gate asset (G1, `ROADMAP.md` section 3) and the Blender
4.2 LTS branch of G3 are still open. Dates, evidence classes and log paths for
everything listed here are in `ROADMAP.md` sections 3 and 8.

---

## Known limitations

- **RizomUV is optional, and the Live Link, Lua Script and Auto modes are
  Windows-only.** Rizom-Lab's library ships as a Windows wheel, so macOS and
  Linux keep the manual Export & Open / Import round trip, which needs no
  external library. The manual round trip (G2, 500/500 faces matched) and the
  automated bridge in all three modes were verified on Windows with RizomUV
  2025.0.117.
- **Only Blender 5.2.0 LTS is covered by the logs here.** 4.2.0 is the minimum
  declared in `bl_info` and the code carries fallbacks for the differences
  between the two, but that version has not been exercised.
- **Numbers quoted in this document are development measurements.** Timings and
  island counts in the notes below come from runs on specific meshes while the
  features were written; the test suite does not reproduce them, so read them
  as reports rather than as guarantees.

---

## Pipeline

```
ContextGuard          validate object, mode, mesh data
      |
MeshAnalyzer          areas, normals, edge lengths, edge->face connectivity
      |               (bmesh first; falls back to direct attrs, then vertex pairs)
MaterialAnalyzer      material groups + material-boundary edges
      |
MarginCalculator      texture resolution -> margin px -> margin UV -> seam margin
      |
CurvatureEstimator    automatic threshold via Otsu on dihedral angles
      |
SeamPlanner           seam candidates = curvature + material boundaries
      |
RegionMerger          dissolve seams whose merged island stays flat enough
      |
SeamMarker            write edge.use_seam (verified by read-back)
      |
   +--+--------------------------+
   |                             |
MinimalUVExecutor           RizomUVBridge
uv.unwrap (honours seams)   pre-unwrap -> FBX -> Lua -> poll -> copy UVs back
   |                             |
IslandExtractor             (RizomUV packs internally)
   |
TexelDensityNormalizer      scale islands to a uniform density
   |
pack_islands + coverage
   |
DistortionAnalyzer          density spread, angular error, overlap check
```

---

## Module Map

| File | Responsibility |
|---|---|
| `utils.py` | Version-tolerant mesh API helpers, shared geometry maths, UV editor context override |
| `properties.py` | Every user setting, as one `PropertyGroup` |
| `validation.py` | `ValidationResult`, `ContextGuard` |
| `mesh_analysis.py` | Topology and geometry: vectorized `foreach_get` first, then bmesh, then two fallbacks |
| `material_analysis.py` | Material groups, material-boundary edges |
| `margins.py` | Single source of truth for margins (native engine and RizomUV agree) |
| `curvature.py` | Otsu threshold estimation, with degenerate-case handling |
| `seam_planning.py` | Seam candidates and post-cut region computation |
| `region_merge.py` | Normal-cone merging and splitting of non-developable regions |
| `distortion.py` | Texel density spread, angular error, bbox overlap detection |
| `seam_marking.py` | `edge.use_seam` writing with read-back verification |
| `uv_executor.py` | Unwrap, pack, coverage scaling, UV layer backup |
| `island_extraction.py` | Per-island faces, UV area, centroid, bbox, dominant material |
| `texel_density.py` | Per-island scaling toward uniform density |
| `manual_io.py` | Manual FBX export/import, for round-tripping UVs by hand |
| `rizomuv_link.py` | Live link through RizomUV's official Python API (Windows) |
| `rizomuv_bridge.py` | Phased external engine: `prepare` / `launch` / `finalize` / `cleanup` |
| `operators/base.py` | `IntelligentUVBaseOperator`: the shared analysis pipeline |
| `operators/run.py` | Modal Run operator (unwrap, texel density, packing, reporting) |
| `operators/seams.py` | Seam-only operator |
| `operators/diagnose.py` | Mesh API diagnostic operator |
| `presets.py` | Named setting bundles stored as JSON, plus the preset menu |
| `ui.py` | Sidebar panel |


The full development diary (design decisions, stability and performance notes, diagnostics history) lives in [ARCHITECTURE.md](ARCHITECTURE.md).

---

## License & Credits

**Author:** Pierfrancesco Diodato.

`intelligent_uv` is released under the **GNU General Public License, version 3 or
later** (GPL-3.0-or-later). Copyright (C) 2026 Pierfrancesco Diodato.

The full licence text is in [LICENSE](LICENSE). The **License & Credits** button
at the bottom of the panel (`intelligent_uv.show_info`) opens the same
information from inside Blender: version, author, licence, a quick guide, and
links to the GitHub repository (https://github.com/PieroFra/intelligent_uv), the
Discord profile (https://discord.com/users/1176582483165327382), the full
GPL-3.0 text and the local README.md, CHANGELOG.md and LICENSE files.

What comes from elsewhere, and what does not:

- **Two development scripts** under `.opencode/skills/blender-bridge/scripts/`
  (`blender_bridge.py`, `bridge_call.py`) are byte-for-byte identical to the
  same-named files in the sibling `ACTD` project and are carried here under the
  same GPL-3.0-or-later terms. They are tooling for agents working on this
  repository, not part of the add-on: nothing in the package imports them, and
  `.opencode/` is excluded from the release archive.
- **RizomUVLink** (MIT, Rizom-Lab) is **not vendored**. No copy of it, no wheel
  and no binary is in this repository. `rizomuv_link.py` imports it lazily from
  the RizomUV installation on your machine, where the MIT notice travels with it;
  it stays under Rizom-Lab's own MIT licence and is not covered by this project's
  GPL-3.0-or-later. RizomUV itself is commercial software from Rizom-Lab and is
  not distributed with this add-on.
- Runtime dependencies are otherwise only what Blender ships: `bpy`, `bmesh`,
  `mathutils` and `numpy` (bundled with Blender).

[THIRD_PARTY.md](THIRD_PARTY.md) records the evidence behind each statement above
(sizes, SHA-256 digests, usage paths), separates what the owner declares from
what an inspection of this tree can verify, and names what the audit does not
establish. It is a factual record, not a legal opinion.
