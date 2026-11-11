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

## Superhive listing

Not pursued: distribution stays free on Blender Extensions and GitHub;
selling is out of scope.
