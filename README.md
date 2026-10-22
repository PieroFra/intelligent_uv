# Intelligent UV Mapping — Blender Add-on

Automated UV unwrapping for Blender: curvature-driven seam planning, island
merging, texel density normalization, and an optional bridge to RizomUV.

Version 0.34.0 · targets Blender 4.2+ · tested against Blender 5.2 LTS

---

## Install

Zip the `intelligent_uv` folder and install it via
**Edit > Preferences > Add-ons > Install from Disk**, or drop the folder into
your `scripts/addons` directory. The panel appears in the 3D View sidebar (N)
under the **Intelligent UV** tab.

---

## Quick start

Select a mesh object, press **N** in the 3D View and open the **Intelligent UV**
tab. The whole workflow is in that panel:

1. **Check Mesh** — reads the mesh and reports what would spoil the unwrap,
   each finding with what to do about it. It changes nothing, so it is safe to
   run first and safe to run again.
2. **Unwrap** — runs the full pipeline (`Run Intelligent UV`): preflight, seam
   planning, unwrap, packing and the quality report. **Preview** runs the same
   pipeline but keeps the result pending until you press **Apply** or
   **Discard**.
3. *Only when the packing happens in RizomUV:* **Export & Open** asks where to
   write the FBX (default `<object>_uv.fbx`), unwraps natively first so the
   planned seams travel inside the file as island borders, then launches
   RizomUV on it. Work there and save over that file, or beside it as
   `<name>_import.fbx`.
4. **Import** copies the UVs back from whichever of those two files is newer,
   with no dialog. **Import from...** opens a file browser when the result lives
   somewhere else.

The default view holds nine controls: the preset menu, **Unwrap**, **Preview**,
**Check Mesh**, **Dry Run**, **Resolution**, **Target Islands** (with **Detail**
below it), **All Selected Objects**, and the **External Editor** group — path,
**Export & Open**, **Import**, **Import from...**. Everything else sits behind
**Advanced** at the bottom of the panel; the defaults and the presets are meant
to cover most assets, and those parameters are there for the assets they do not.

---

## Known limitations

- **Reinstalling the add-on requires restarting Blender.** The settings live in
  a `PropertyGroup` that `Scene.intelligent_uv_settings` points at; reloading
  the modules would leave that RNA pointer dangling, which crashes Blender
  instead of raising, so no automatic reload exists. `register()` says so when
  it detects a stale load.
- **RizomUV is optional and the live link is Windows-only.** Rizom-Lab's
  library ships as a Windows wheel, so macOS and Linux fall back to the manual
  round trip. The automated engine — the experimental toggle behind
  **Advanced** — has never completed a round trip reliably; **Export & Open**
  followed by **Import** is the supported flow.
- **The test suite does not cover the UV pipeline.** `.opencode/tests/smoke_test.py`
  runs 14 checks over import, registration, the panel, the operators, the
  properties exposed in the UI and unregister. None of them unwraps a mesh,
  marks a seam, packs a layout or exercises the FBX/RizomUV round trip: a green
  run says the add-on registers, not that the result is good.
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

## Module map

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

---


**The clustering settings are derived, not guessed.** Each has a source. The
tolerance is the Otsu break in the model's own dihedral distribution — the angle
at which the model itself stops being one surface — so a cluster grows across
the smooth side and stops at the sharp side. The minimum island size comes from
the margin, because an island smaller than its own padding is waste whatever the
geometry looks like. The iteration ceilings drop on heavy meshes, since both
loops already exit when nothing moves and the last passes change least.

Crease pull needed an absolute angle, and finding that out cost a test failure
worth keeping: measuring "how many edges are sharp" against the Otsu break
reported 57% creased on a mesh whose sharpest edge was 9 degrees. Otsu splits
whatever it is given, so a relative measure always finds a sharp half. It now
counts edges folding past 30 degrees, which is a fact about the geometry rather
than about the distribution.

The island count is deliberately not derived. How many islands an asset should
have is a judgement about what it is for, so what is computed instead is the
point past which padding costs more than the extra cuts save, reported as a
warning rather than applied behind the user's back.

**The overlap test was indexing the same islands over and over.** Profiling a
315-island layout put five of eight seconds inside the grid build: the index for
island B was constructed fresh for every candidate pair B took part in, so an
island appearing in twenty pairs was hashed twenty times — 3.3 million
dictionary inserts in total. Building it once per island and caching it cut the
run by a third.

The rest went to a filter that costs four comparisons per segment: two outlines
can only cross inside the rectangle their bounding boxes share, and on a packed
layout that strip is a sliver, so most segments are discarded before any grid
lookup. Together: 3.78s to 0.36s on the same data.

The trimmed list is used only for the crossing test. Containment asks whether a
point of A lies inside B, and a trimmed A can have lost exactly the point it
needs — a nested-island case now covers that, because the first version of the
filter broke it silently.

**Every silent exception handler states why it is silent.** There were
twenty-five `except: pass` blocks with nothing explaining them, and they are not
interchangeable: freeing an already-freed bmesh, unregistering a class that was
never registered, and a progress bar with no context to draw in all look
identical in the source and mean completely different things. Each now carries
its own reason, so the next person can tell a deliberate tolerance from a
swallowed bug without running the code.

**The Run operator is composed from mixins, not one 1200-line class.** It had
grown to hold four unrelated jobs: draining a queue of objects, driving an
external process across timer callbacks, running the unwrap pipeline, and
reporting. Each is understandable on its own and unreadable interleaved with the
other three.

They are now `batch.py`, `external.py` and `native.py`, mixed into the operator
in that order. Mixins rather than helper objects because the methods genuinely
share operator state — `self._queue`, `self._bridge_ctx`, `self.report` — and
passing that between separate objects would invent plumbing to avoid a language
feature that fits. The only change to behaviour is that the busy flag is now set
through `type(self)` instead of naming the class, so the queue code no longer has
to import the class it is mixed into.

**Texture sets and UDIM answer the same question differently.** One image is
not enough, and there are two ways out. Texture sets give each material its own
image, all addressed by the same 0-1 coordinates, so the sets sit on top of each
other. UDIM lays the images side by side in one continuous space: tile 1001 is
0-1, 1002 is 1-2 in U, and a renderer handed a filename with a `<UDIM>` token
picks the image from the coordinate itself.

Neither is better. A real-time engine draws one material at a time and a shared
coordinate space costs it nothing, so texture sets are what it wants. Substance
and film renderers address tiles natively, and one layout spilling across four
tiles is simpler to author than four sets.

UDIM runs last, when everything is already packed into 0-1, so moving an island
to tile N is adding an integer and nothing here needs to know how the packing
was decided. Tiles follow material slot order rather than island size: an artist
who reorders their slots expects the tiles to follow, and numbering that
reshuffles whenever a material grows makes it impossible to keep textures
matched. Coverage scaling is skipped on a UDIM layout, since normalising into
the unit square would collapse every tile back onto 1001.

**Each material can own the whole UV square.** An asset with three materials
gets three textures, and every one of them is addressed by the same 0-1
coordinates. Packing all the islands into a single square therefore wastes most
of each image: the metal parts sit in a corner of the metal texture and nothing
uses the rest, while the same corner of the fabric texture is empty.

Packing per material fixes it, and the sets then overlap in UV space — which
looks alarming in the editor and is exactly right, because two faces at the same
coordinate read from different images and cannot collide. The overlap check is
told about this and stops reporting pairs that belong to different sets, so the
warning keeps meaning something.

The packing itself is still Blender's: each set is packed by selecting that
material's faces and packing the selection, rather than reimplementing placement
per group. A slot with no faces is skipped rather than counted, since empty
slots are common and mean nothing.

**Undo is not a safety net here, so the state is captured explicitly.** A run
overwrites two things that are expensive to recreate by hand: the seams on the
mesh and whatever was in the target UV layer. Blender's undo would normally
cover that and does not: the run enters and leaves Edit Mode several times,
calls operators that push their own undo steps, and on the external path shells
out to another process. Ctrl+Z afterwards lands somewhere unpredictable in the
middle of the pipeline rather than before it.

Preview therefore records the seams into a boolean edge attribute — not a Python
list, which would not survive saving the file and reopening it with a preview
still waiting — and copies the UV layer aside. Discard puts both back exactly,
including deleting the layer entirely when the run was the thing that created
it. Apply drops the records and keeps the result. While a preview is pending the
panel shows only Apply and Discard, because deciding on it is the only sensible
next action.

**A symmetric model gets symmetric seams.** Clustering runs over the whole mesh
at once, so the two halves are grown independently and end up cut in subtly
different places — a border sitting on a crease on the left drifts a face off it
on the right, because the running average reached that face from a different
direction. Nothing about it is wrong and it reads as a mistake immediately.

The plane is found rather than assumed: all three local axes are tested and the
one that actually pairs faces wins, so a model symmetric about Y, or built
off-centre, needs no configuration. Matching uses position, area and mirrored
normal together, since position alone pairs faces that merely happen to sit
opposite each other. The threshold sits below 1.0 because a real asset carries
asymmetric detail — an ejection port, a charging handle — and a handful of
unpaired faces must not disqualify the model.

One half is then authoritative and its seams are copied across, rather than
taking the union of both: a union keeps every cut either side produced and ends
up with roughly twice the seams the algorithm thought were needed. Hand-placed
seams are never removed on either side. Mirrored halves cut identically also
become stackable, so this and the stacking pass pay for each other.

**Islands are turned before they are packed.** The packer arranges islands; it
never reshapes them. A shell that leaves the unwrap at forty degrees to the axes
carries a bounding rectangle far larger than itself, and that waste is already
baked in whatever the packer decides. Rotating first costs the packer nothing
and gives it strictly more room.

The angle comes from rotating calipers over the convex hull, which is exact: the
minimum-area rectangle around a convex polygon always has one side flush with a
hull edge, so testing every hull edge finds the true optimum. Principal
component analysis is the usual shortcut and is wrong often enough to matter —
it minimises variance rather than enclosing area, and on an L-shaped island it
came out 23% worse in testing. An island already close to aligned is left alone
rather than rotated for a one percent gain that is mostly float noise.

**Repeated parts can share one patch of texture.** A weapon carries the same
screw twenty times and the same rail segment eight; packed normally each repeat
claims its own space. No packer does this automatically, and not because they
are lazy: by the time the packer runs the duplicates are already separate shells
with nothing marking them as related. The information is in the 3D geometry.

Islands are grouped by a signature built only from quantities that survive
moving, rotating and mirroring — face count, total area, and the quantized
distribution of face sizes — then walked in a canonical order that starts at the
largest face and sorts neighbours by area, so two copies produce the same
sequence even though their face indices differ.

The design assumes the matching will sometimes be wrong. Stacking two islands
that are not really identical corrupts a layout in a way nobody notices until
the texture is painted, so every copy is verified afterwards against the
source's UV area and restored exactly if it does not hold. It is off by default:
sharing a texture between repeats is usually what you want and occasionally is
not.

**The panel shows nine controls, not forty-six.** A tool that needs a manual is
not a tool. The default view is a preset menu, an Unwrap button, a resolution,
an island target and the external round trip — which is the whole interaction on
most assets. Everything else has a sensible default and moved behind Advanced,
where it stays available for when the defaults do not fit.

**Presets drive the pipeline that is actually running.** After the move to
clustering the built-in presets still set threshold-era properties, so applying
"Hard Surface" changed parameters the run never read. They now set the method
itself and every parameter that matters for it: a tight tolerance and strong
crease pull for hard surface, a loose one with more refinement for organic, and
a direct island target for the 1K preset, where every island border costs
padding and padding is most of the texture at that size.

**The solver already says which islands it failed on; now something listens.**
Blender prints "Unwrap failed to solve N of M islands, edge seams may need to be
added" and carries on. Those faces come back with no UV area, which is why a
quality report could show thousands of collapsed faces while the rest of the
layout looked fine. The message even names the remedy.

`recovery.py` finds them — UV area against 3D area, so a genuinely tiny face is
not mistaken for a collapsed one, and an island only counts as failed when at
least half of it is flat — then re-cuts each failed island *on its own*, with
adjacency restricted to that island's faces so no neighbour is disturbed.
Widening the cut globally to rescue a handful of islands is how a layout goes
from sixteen bad islands to everything fragmented. Rounds tighten as they go,
because what survived the first pass is by definition the more stubborn
geometry, and the loop stops the moment nothing is left to fix.

**Problems are diagnosed before the run, not reported after it.** Every check in
`preflight.py` came from a real asset: a 47k-face weapon arrived with 214
non-manifold edges, faces folded flat enough to read 180 degrees of dihedral
angle, and 46 disconnected pieces. All three were reported — as warnings among a
dozen others — and the run continued, after which Blender said it could not
solve 16 of 183 islands. The information was there and none of it was
actionable.

Each finding answers what is wrong, why it breaks UVs, and what to do, because a
count alone is not a diagnosis: 2600 boundary edges is alarming on a solid and
entirely normal on a sheet, and only the proportion tells the two apart.
Severity is about consequence — a blocker means the result will be garbage, so
the run stops rather than spending a minute producing it.

**Packing is measured, not assumed.** Distortion says whether the texture is
stretched; it says nothing about how much of the texture the asset never
touches. `measure_fill` reports two numbers because they call for opposite
fixes: coverage is island area over the unit square, which decides how much
resolution the asset actually gets, while efficiency is island area over the
area the layout occupies. A layout at 21% coverage and 92% efficiency is packed
well and scaled too small — repacking it would achieve nothing. A layout at 8%
and 8% is genuinely sprawling.

**The packer is Blender's, with its best options turned on.** `uv.pack_islands`
is C and packs against the real island outline; a Python reimplementation would
be slower by orders of magnitude and worse. What was missing was the arguments:
`shape_method='CONCAVE'` packs against the outline rather than the bounding box,
which matters because a UV shell is almost never rectangular and AABB packing
reserves every island's empty corners. The fallback chain sheds the newest
keywords one tier at a time, so an older build still gets rotation and correct
scale behaviour instead of dropping to a bare call.

**Cluster borders are smoothed onto creases.** Growing regions judges each face
by proxy fit alone, so a border wanders: a face surrounded on three sides by
another cluster stays put because its normal matched first. The outline packs
badly and the visible cut lands arbitrarily. A smoothing pass reconsiders only
border faces, scoring a move by how many neighbours already belong to the
candidate cluster — which straightens the outline — and by how creased the edges
that would become the new border are, which moves the cut into a fold. Measured
on a deliberately zig-zagged two-panel border: 34 border edges down to 12, the
minimum, with all 12 landing on the crease where none had been before. A face
only moves when the candidate is strictly better, so a pass cannot oscillate.

**The RizomUV round trip is manual by default.** Export writes the FBX and hands
the path to the executable, nothing more: no Lua script, no `-cfi` remote file,
no socket, no polling, no modal operator. Those exist to automate the round trip
and every one of them is a way for the run to hang. The process is left entirely
alone, so RizomUV crashing cannot affect Blender. The automated engine is still
there behind an experimental toggle, labelled as such, because it has never
completed a round trip reliably.

**Clustering is refined, not taken on the first pass.** Growing regions once is
order-dependent: a face joins whichever cluster reaches it first and never
leaves, so the partition depends on which seed happened to start. Lloyd
relaxation alternates fit and partition — each proxy moves to the area-weighted
average of what it captured, then every face is re-assigned from a single global
priority queue — until the assignment stops changing. Borders straighten and a
cluster stops trailing into its neighbour.

**Island count can be the control instead of the tolerance.** An artist thinks
in islands, not in degrees of normal deviation, and the relation between the two
changes with every mesh. With a target set, farthest-point seeding places that
many proxies across the surface and Lloyd arranges them; the tolerance becomes a
consequence rather than an input.

**Sliver absorption needs a fit guard, not just a size test.** Clusters below the
minimum are folded into the neighbouring proxy that fits best — but only if it
fits at all. Without the deviation guard a cube face folds into a perpendicular
neighbour and the flat partition is destroyed; a sliver with no plausible home is
better left as its own island.

**Seams come from regions, not from edges.** A curvature threshold asks only
"does the surface bend sharply here?". It cannot see that a smooth cylinder must
be cut even though no edge on it bends, nor that a bevel chain belongs with the
panel beside it. On a real asset both mistakes appear together: lowering the
threshold to open the cylinder shatters the panels first. `vsa.py` grows faces
into clusters whose normals stay within a tolerance of the cluster's running,
area-weighted average, and the borders between clusters are the seams.

**Topology decides what clustering cannot.** A cluster can still be a ring, and
no unwrap flattens a ring. The Euler characteristic X = V - E + F settles it
without geometric guesswork: X = 1 is a disc, X <= 0 is a ring or has holes.
Those clusters are opened along a shortest path between two boundary loops,
found with Dijkstra over the cluster's own interior edges. The path cost is
euclidean length scaled by flatness, so the cut drifts into a crease where it
is least visible rather than running straight across a smooth surface.

**Clustering is linear; the merger is not.** Measured on synthetic meshes,
clustering runs O(n) and finishes a 47k-face mesh in about 0.6 seconds. The
region merger on the same scale runs for minutes. Under VSA the merger is off by
default: clustering already produces coherent regions, so it has nothing to
repair and only costs time.

## Design decisions worth knowing before changing things

**Geometry is read with `foreach_get`, topology with bmesh.** Face areas,
normals and vertex coordinates come from bulk `foreach_get` reads into float32
buffers (numpy when available, `array.array` otherwise), which avoids one RNA
call per element. Edge-to-face connectivity has no practical `foreach_get`
equivalent, so it still comes from `bmesh.edge.link_faces`. The float32 buffers
introduce a relative error around 1e-10 on areas and 3e-6 degrees on dihedral
angles — far below the planner's 1e-4 degree epsilon, and measured not to change
any seam or merge decision.

**`face_normals` must stay a list of tuples.** Seam planning, curvature
estimation and region merging all index into it as tuples. The vectorized path
converts explicitly rather than handing back a numpy array.

**bmesh is the primary topology source.** Direct mesh attributes
(`MeshLoop.edge_index`, `MeshPolygon.loop_total`) have been reshaped across
Blender releases; bmesh has not. Two fallbacks exist, and if all of them fail
the analysis raises a clear error rather than silently reporting zero seams.

**FBX cannot carry Blender UV seams.** There is no seam flag in the format.
The RizomUV bridge therefore unwraps natively *first* — that unwrap does honour
`use_seam` — so the cuts travel as UV island borders inside the FBX. Loop
topology is untouched, which keeps the UV copy-back valid.

**The native engine uses `uv.unwrap`, not Smart UV Project.** Smart UV Project
ignores seams entirely, which would make the planned regions disagree with the
actual islands and corrupt texel density normalization. Smart UV Project remains
only as a fallback when no seam was planned at all.

**External engine failures degrade, they do not cancel.** Returning `CANCELLED`
from an operator with `{'REGISTER', 'UNDO'}` makes Blender discard the seams and
unwrap already written to the mesh. The bridge keeps its work and reports a
warning instead.

**The external process is polled, not waited on.** `subprocess.run` on Blender's
main thread freezes the UI for the whole run. The bridge is split into phases and
the Run operator is modal, polling at 250 ms with ESC to abort.

**Island merging uses the normal cone, not trial unwraps.** The maximum angle
between a region's area-weighted mean normal and its face normals predicts
whether the patch flattens well, and is cheap to evaluate incrementally.
Trial-unwrapping every candidate pair would be correct but far too slow.

**Micro-island absorption only merges small into large.** Merging two micro
islands with each other lets a small mesh — where every region counts as micro —
collapse into a single shell.

**`operators` is a package, not a module.** It was split because a single
757-line file concentrated a quarter of the project's branching. If an old
`operators.py` is ever left beside the `operators/` folder, Python silently
loads the package and ignores the file — edits to it will appear to do nothing.

**`IntelligentUVBaseOperator` must never be registered.** It is abstract and has
no `bl_idname`; only the three concrete operators go into `register()`.

**Some regions must be cut open, and no angle threshold will do it.** A
cylinder has no sharp edge anywhere: lowering the curvature threshold enough to
catch its gentle bend shatters every other part of the model first. Yet it must
be cut, because unwrapping a closed tube asks the solver to flatten a loop and
it gives up — Blender reports "Unwrap failed to solve N of M islands" and those
faces come back with zero UV area. `RegionSplitter` uses the signal already
available, the region's normal cone: a region whose normals span more than
about 100 degrees has wrapped too far to flatten, whatever its dihedral angles
say. It gets a much lower threshold applied to its interior edges only, so the
rest of the model keeps the seams that were asked for. Splitting runs *before*
merging, or the merger would fuse those regions into something even less
developable.

**There is no automatic module reload, on purpose.** Reloading submodules on
re-import looks convenient and crashes Blender: `properties.py` defines the
PropertyGroup that `bpy.types.Scene.intelligent_uv_settings` points at, so
reloading it builds a new class while RNA still references the old one. Once the
old module is collected that pointer dangles, and Blender dies outright rather
than raising. The same applies to every registered operator and panel.
Reinstalling requires restarting Blender; `register()` says so when it detects a
stale load.

**Face centres are not read through `foreach_get`.** `area` and `normal` are
cross-checked against bmesh and agree exactly, but `center` is a computed
property with no such confirmation. If RNA reports a different element count
than the allocated buffer, `foreach_get` writes past the end and corrupts the
heap — a crash, not an exception. Centres are filled from `poly.center` in a
plain loop, which cannot overflow.

**Every output states the add-on version.** The diagnostic header, the run
summary and the panel all print it. Without that there is no way to tell from a
log whether a fix is actually running: a stale install and a fix that did not
work produce identical output, and the difference costs a round trip to find.

**The reload guard discovers submodules from `sys.modules`.** A hand-written
list goes stale the moment a module is added, and the symptom is a fix that
appears not to work because Blender kept serving the cached old code. Modules
are reloaded deepest-path first, and a failed reload is reported rather than
swallowed.

**Import needs no file dialog in the common case.** An external editor is
normally pointed at the exported file and told to save over it or beside it, so
the path is already known. `last_import_candidate` checks both conventions —
`<name>.fbx` saved in place and `<name>_import.fbx` saved alongside — and picks
whichever is newer. The button is disabled rather than erroring when neither
exists.

**The seam margin is capped by the real edge lengths.** The filter refuses to
cut edges shorter than about one margin's worth of texels, which is sensible in
isolation but scales with 1/sqrt(mesh area). A 47k-face weapon measuring 10
square units saw 68% of its edges excluded before the planner looked at a single
angle, which left whole cylinders uncuttable at any curvature threshold — the
same island stayed at 14336 faces whether the threshold was 75 or 39 degrees.
The threshold is now clamped to the 15th percentile of actual edge lengths when
it would exclude more than that, and the run reports when it had to.

**`-cfi` is not a batch flag; `-id <port>` is.** The Lua script path never
completed because `-cfi <script>` attaches a *remote file* that RizomUV watches
for changes — the process sits waiting and the run times out, whatever the
script ends with. The headless invocation is `-id <port>`, which is what the
official API's `RunRizomUV` uses.

**The live link uses Rizom-Lab's own API, not a generated script.**
`RizomUVLink` is published by Rizom-Lab under MIT and exposes the real commands
(`Load`, `Unfold`, `Optimize`, `Pack`, `Save`, `Quit`) over a local socket, so
nothing about the syntax has to be guessed. It ships as a Windows-only wheel, so
`is_available()` gates the whole path and macOS and Linux fall back to the
manual Export/Import round trip, which needs no external library.

**The link runs one command per modal tick.** Every API call is synchronous, and
unfolding or packing a dense mesh in a single call would freeze Blender for its
whole duration. Stepping through the sequence keeps the UI alive and lets ESC
abort between commands.

**Unwrap is followed by a relaxation pass.** `uv.unwrap` solves for angle
preservation and stops; it never evens out the stretch that remains, which is
what leaves a checker pattern sheared on long or twisted shapes even when the
seams are right. `uv.minimize_stretch` relaxes the interior of each island
without moving its boundary, so it improves the result without changing what was
cut. It runs before packing, because it moves UVs inside islands.

**Overlaps are verified by edge intersection, not bounding boxes.** Two islands
can have intersecting boxes and never touch — the normal case for any
non-rectangular shell. One run reported 433 intersecting boxes, most of them
harmless, which buries the real ones. Boxes are still the first filter because
they are cheap, but survivors get a segment intersection test. Islands merely
touching at the margin are not overlaps.

**Seams prefer valleys over ridges.** `angle_between_degrees` is unsigned, so a
90 degree cube corner and a 90 degree interior crease look identical to it — yet
a seam on the corner runs along the silhouette where it shows, while a seam in
the crease is hidden. `edge_is_concave` recovers the sign by comparing the
direction to the neighbouring face centre against the first face's normal.
`concave_seam_bias` then lowers the threshold in valleys and raises it on
ridges, which is what an artist does by hand. This is why `face_centers` is
carried on the analysis result.

**Dangling seams are pruned.** A seam only separates geometry when it runs
boundary to boundary or closes a loop. An edge whose endpoint no other seam
touches cuts nothing, and only adds a spur to the island outline that wastes
packing space. Pruning iterates, because removing a spur can expose the next
one, and real mesh boundaries count as valid endpoints.

**Every operator that writes UVs must activate its target layer first.**
`uv.pack_islands` acts on the *active* layer while the rest of the pipeline
reads the layer *by name*. Creating the backup layer steals the active slot, so
without an explicit activation the packer rearranges `SmartUV_backup` and leaves
`SmartUV` unpacked — visible only as hundreds of overlapping islands, while
every step still reports success. `pack_islands` takes `uv_layer_name` and
refuses to run rather than packing the wrong layer.

**Packing must not rescale when density was normalized.** Blender's
`uv.pack_islands` rescales islands to fill the square by default. Running it
after texel density normalization silently undoes the normalization: the islands
are made uniform, then resized again to fit. `pack_islands(preserve_scale=True)`
passes `scale=False` so the packer only translates and rotates. The operator
sets it from `normalize_texel_density`.

**Activating a UV layer is verified, never assumed.** `uv.unwrap` and
`uv.pack_islands` write to whatever layer is *active*, while the analysis reads
the layer *by name*. If the activation silently fails, the tool unwraps into one
layer and measures another: every island reports near-zero UV area, texel
density normalization is skipped, and coverage scaling reports degenerate
bounds — all while the operators report success. `set_active_uv_layer` tries
direct assignment, falls back to `active_index`, reads the result back, and
raises if neither worked. Creating the backup layer steals the active slot, so
the backup restores it through the same verified path.

**The manual round trip and the automated bridge share one code path.**
`RizomUVBridge.export_object_fbx` and `import_uvs_from_fbx` are used by both, so
the manual Export writes the same file the bridge writes and the manual Import
uses the same spatially matched copy-back. This is what makes the manual pair
useful for diagnosis: if the hand round trip is clean and the automated one is
not, the fault is in the automation, not in the export or the copy-back.

**UVs come back by position, never by loop index.** RizomUV reorders geometry
during unwrap and packing, and the FBX roundtrip does not preserve vertex, face
or loop order. Copying `loop N -> loop N` scatters the UVs across the mesh — the
observed symptom was a checker pattern landing on the wrong faces. Faces are
paired by centroid through a spatial hash, then loops are matched inside each
paired face by vertex position. Centroids rather than normals: a seam across a
flat surface has identical normals on both sides, so normals cannot
disambiguate it, while a centroid is unique per face regardless of flatness.
Above 1% unmatched faces the copy-back fails rather than writing a half-random
layout.

**The batch queue drains in a loop, not one item per call.** `_process_current`
handles a single object; `_drain_queue` is what keeps going. The native path
would otherwise stop after the first object, since nothing would call it again.

**`modal_handler_add` is called once per batch, not once per object.** When the
queue chains to the next external object from inside `modal()`, the handler is
already registered; registering again would deliver every event twice. That is
what the `already_modal` flag guards.

**`_prepare_write` returns a bool.** Returning the state dict in the dry-run
branch reads as "keep going" at the call site, and the run writes UVs anyway.

**Presets are JSON, not Python.** Blender's `AddPresetBase` writes presets as
executable scripts, so applying one means running code from disk. The preset
module stores inert JSON instead and validates it against an allow-list
(`PRESET_KEYS`) before writing anything, so a preset cannot set the RizomUV
executable path or the temp-file flags. Unknown keys are skipped with a warning
rather than raising, so presets survive version changes.

**`minimum_island_face_count` above ~5 is destructive.** With
`absorb_micro_islands` enabled it is the size below which an island is folded
into a neighbour. Measured on a 384-face sphere, higher values start absorbing
islands that were never fragments. No built-in preset exceeds 5.

**Broad `except Exception` in cleanup paths is deliberate.** Handlers that run
from a `finally` block — restoring the selection, restoring Object Mode, cleaning
up after a failed import — must catch everything. `bpy.ops` raises `RuntimeError`
on a bad context, and letting that escape a cleanup path replaces the real error
with a meaningless one. Everywhere else, handlers catch the specific exceptions
they expect and either log with an `[IUV_*]` prefix or record a warning.

**`pack_islands` needs a UV editor context.** It polls for one, so the executor
searches the window manager for an `IMAGE_EDITOR` area and overrides the context.
Without an open UV editor the operation is skipped with an explicit warning.

---

## Known open issues

**RizomUV live link verified against 2025.0.117.** The link command sequence
(Load / Unfold / Optimize / Pack / Save / Quit) was probed parameter by
parameter against RizomUV 2025.0.117: `Unfold` rejects `ProcessNonFlats` and
`ProcessSelection`, `Pack` rejects `SpacingSize`/`Margin`/`MarginPX`/`MapSize`
(`MarginSize` alone is accepted), and Load/Save use the flat dotted keys from
Rizom-Lab's own examples. The full round trip — start, load, unfold, optimize,
pack, save, spatial copy-back, quit — passes with 100% of faces matched. The
API ships inside the RizomUV install folder, which the add-on now adds to
`sys.path` automatically.

**The `-cfi` script path hangs by design.** Confirmed empirically on
2025.0.117: launched with `-cfi <script>`, RizomUV never exits on its own.
The bridge now kills it cleanly at the timeout and keeps the process log, but
the script path remains a fallback — use the live link (AUTO) wherever
possible. The Lua parameters (`ZomLoad`/`ZomPack`/`ZomSave`) are still
unverified.

**Suzanne produces many islands.** Better than before merging, but seam
placement is still threshold-driven rather than following curvature valleys.

---

## Stability and performance notes (0.16.0)

**RizomUV output goes to a log file, not a pipe.** `subprocess.PIPE` that is
never drained fills its OS buffer (~64 KB on Windows) and the child blocks on
its next write: the process never exits and the run dies at the timeout.
Chatty RizomUV builds hit this on every run. stdout/stderr now go to
`iuv_<name>_rizomuv.log` in the temp folder, read back on failure and kept
with the other temp files for diagnosis.

**The modal operator never returns CANCELLED on failure.** With `UNDO`
enabled, CANCELLED makes Blender discard the seams and UVs already written to
completed objects. The polling-loop failure path now cleans up and returns
FINISHED, matching the batch abort path.

**`cancel()` dispatches on the bridge mode.** It used to call the script
engine's `terminate` unconditionally; on a live-link context that is a no-op
and the RizomUV instance launched via `RunRizomUV` stayed alive forever.

**UV and attribute access is bulk (`foreach_get`/`foreach_set`).** Backup,
coverage scaling, texel density normalization, island extraction, distortion
analysis, FBX copy-back, seam marking and material grouping used to make one
RNA call per loop/edge/face — millions of calls on dense meshes. Each now
reads or writes the whole attribute in one call, with the per-element path
kept as a fallback.

**Overlap testing uses island outlines and a grid broad phase.** The precise
test used to compare every face edge of one island against every face edge of
the other — O(n·m) with tens of thousands of segments per side, which froze
Blender for minutes on large islands. Interior edges cannot cross another
island, so only outline segments are tested, hashed into a uniform grid, with
a containment check for islands sitting entirely inside another's outline.

**Point contacts are not overlaps.** `_segments_intersect` compared
`(d > 0)` signs, which classifies a zero orientation (shared endpoint,
touching borders) as a side and reported point contacts as crossings. It now
requires strictly opposite orientation products.

**Region and component detection is union-find.** Connected components and
post-cut regions were built as Python set adjacencies plus flood fill; both
are now single-pass union-find, and dangling-seam pruning is queue-driven
O(E) instead of rebuilding the valence map over every edge after each pass.

**Dihedral angles are vectorized.** The mesh analyzer keeps a numpy copy of
the face normals (`face_normals_np`), and the curvature estimator and seam
planner compute every dihedral angle in one numpy pass. The scalar path is
kept and tested to agree within 1e-6 degrees.

**There is a smoke test.** `.opencode/tests/smoke_test.py` runs inside Blender
and performs **14 checks** on import, registration, the panel, the operators,
the properties exposed in the UI and unregister. It writes
`.opencode\tests\test_out.txt` and finishes with a
`RISULTATO passati=X falliti=Y totale=N` line. Run it from the project root:

```
powershell -NoProfile -ExecutionPolicy Bypass -File .opencode\scripts\run_tests.ps1
```

It does **not** cover the UV pipeline: unwrap, seams, packing, texel density
and the FBX/RizomUV round trip are not exercised by the suite.

---

## Ideas not yet implemented

- Seams following curvature valleys instead of a hard angle threshold
- Symmetry-aware seams for mirrored assets
- Packing with real fill-efficiency evaluation
- UDIM / multi-tile layouts

See `ROADMAP.md` for the full improvement plan.

---

## Diagnostics

The **Diagnose Mesh API** button reports which mesh APIs this Blender build
exposes, which topology path succeeded, the dihedral angle distribution, the
computed thresholds, and where the pipeline would break. Output goes to the
System Console and to a text block named `IntelligentUV_Diagnostic`.

Use **Dry Run** to plan without writing anything to the mesh.

---

## License & attribution

`intelligent_uv` is released under the **GNU General Public License, version 3 or
later** (GPL-3.0-or-later). Copyright (C) 2026 Pierfrancesco Diodato.

The full licence text is in [LICENSE](LICENSE).

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
— sizes, SHA-256 digests, usage paths — separates what the owner declares from
what an inspection of this tree can verify, and names what the audit does not
establish. It is a factual record, not a legal opinion.
