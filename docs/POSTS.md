# POSTS: Intelligent UV Mapping 0.36.0

Drafts for external channels. Facts only from README.md and PROMO.md, no
benchmark numbers. Feedback always points to the GitHub Issues tracker.

---

## Draft 1: Reddit (r/blender, flair "Free Tools & Assets")

### Title (76 chars)

I built an add-on that plans UV seams from curvature, tell me where it fails

### Body (146 words)

When you unwrap a production asset, the seams decide everything: where the
stretching lands, how much packing space you waste, whether the texel density
matches across objects. I kept re-placing the same seams by hand, so I wrote
an add-on that plans them from the mesh instead.

It estimates curvature (Otsu threshold on dihedral angles), grows faces into
clusters whose normals stay within tolerance, cuts along the cluster borders,
merges regions that stay flat enough, then unwraps, normalizes texel density
across a batch of objects and packs, UDIM supported. Seams you placed by hand
survive the pass. There is a preview: the result stays pending until you Apply
or Discard, and Discard restores your previous UV layer exactly.

It is free, GPL, Blender 4.2+ (I run it on 5.2). Repo and issue tracker are in
my comment below, tell me where it breaks on your meshes.

### Comment to paste right after publishing (links live here only)

Repo: https://github.com/PieroFra/intelligent_uv
Feedback and bugs go to the issue tracker: https://github.com/PieroFra/intelligent_uv/issues

---

## Draft 2: Superhive listing

### Short description (46 words)

Intelligent UV Mapping plans and runs UV unwraps from mesh analysis:
curvature-driven seams, island merging, texel density normalization and UDIM
packing, inside Blender or with an optional RizomUV hand-off. One button runs
the whole pipeline; a preview keeps the result pending until you Apply or
Discard.

### Bullet points

- Seams planned from the mesh: curvature estimation with an automatic Otsu
  threshold on dihedral angles, faces grown into clusters whose normals stay
  within tolerance, closed regions that cannot flatten opened along a shortest
  path.
- Your seams survive: hand-placed seams are never overwritten, and the preview
  keeps the result pending until you Apply or Discard, with Discard restoring
  the previous UV layer exactly.
- One texel density for the whole batch: objects at different scales share a
  single world-space density target computed from total area.
- Texture sets and UDIM: per-material images on the shared 0-1 space, or
  multi-tile packing across 1001, 1002, 1003... with collision-free,
  deterministic tile assignment.
- Optional RizomUV round trip: manual Export & Open / Import on every platform,
  plus automated Live Link, Lua Script and Auto modes driven one command per
  tick so Blender stays responsive.

### Requirements

- Blender 4.2.0 or newer (developed and tested on Blender 5.2 LTS).
- No dependencies beyond what Blender ships: bpy, bmesh, mathutils, numpy.
- RizomUV integration is optional and the add-on works fully without it; the
  automated modes (Live Link, Lua Script, Auto) are Windows-only and verified
  with RizomUV 2025.0.117. macOS and Linux keep the manual round trip, which
  needs no external library.
- Reinstalling the add-on requires restarting Blender (the settings pointer on
  Scene survives only across a clean restart).

### Two editions, one source

Both editions are built from the same source tree and run the same pipeline.

- Full edition (GitHub releases): includes the optional RizomUV integration,
  loaded lazily and only when an external engine is requested.
- Blender-only edition (Blender Extensions): the three rizomuv_* modules are
  physically absent from the package and the external engine capability is
  baked off in the artifact, so the external engine is absent, not merely
  disabled.

License: GPL-3.0-or-later. Author: Pierfrancesco Diodato.
Report bugs and feature requests on GitHub Issues:
https://github.com/PieroFra/intelligent_uv/issues
