# Third-party material and attribution

This file records what in this repository comes from somewhere else, how that
was established, and what ships with the add-on.

It is a factual record, not a legal opinion. Where a question is open, it says
so instead of answering it.

---

## 1. Verified: two development scripts copied from the ACTD project

Two files under `.opencode/skills/blender-bridge/scripts/` are byte-for-byte
identical to the same-named files in the sibling project `ACTD`
(`..\ACTD\.opencode\skills\blender-bridge\scripts\`), which is distributed under
GPL-3.0-or-later.

| File in this repository | Size | SHA-256 |
|---|---|---|
| `.opencode/skills/blender-bridge/scripts/blender_bridge.py` | 3702 bytes | `DC00EA2A9F2EAB4D61DB9E3A79326BDE4409C7D9692373EBD9B4779462EC283D` |
| `.opencode/skills/blender-bridge/scripts/bridge_call.py` | 1658 bytes | `559DB13426A5FA70888E7BB2D89320ED247DA4BD42037B952A702FE3688207C6` |

The pairs were hashed on 2026-10-22 with SHA-256; for each file the digest of
this copy and the digest of the copy in `ACTD` are equal, and so are the byte
lengths. Identical bytes are the whole of the evidence: nothing here claims
history beyond that comparison.

What these two files are:

- `blender_bridge.py` — a local TCP bridge that runs Python inside a running
  Blender instance, in the main thread, and returns stdout and errors.
- `bridge_call.py` — the client side of that bridge: sends a snippet or a file
  and prints the response.

Where they are used, and what that implies:

- They are development tooling. They are read by the `blender-bridge` skill in
  `.opencode/skills/`, which an agent may load to inspect a live Blender UI.
- They are **not** part of the Blender add-on. Nothing in the package imports
  them, and the add-on cannot reach them at runtime.
- `.opencode/` is excluded from the release archive, together with `.git`,
  `__pycache__` and the local test files, so these scripts are not distributed
  in a release of the add-on.
- The origin project is stated as GPL-3.0-or-later and this project is stated
  as GPL-3.0-or-later, so the two files are carried here under the same terms
  as their origin. The licence text is in [LICENSE](LICENSE).
- The `SKILL.md` beside them is not one of the two identical files: it is
  written for this project (it documents a different default port, for
  instance, so two projects can keep a bridge open at once).

If a future copy of either script is edited here, the identity recorded above
stops applying and the table must be updated or the entry removed.

---

## 2. Not vendored: RizomUVLink (MIT, Rizom-Lab)

`RizomUVLink` is the official Python API published by Rizom-Lab under the MIT
licence. `rizomuv_link.py` uses it to drive a RizomUV installation over a local
socket.

Its status is different from the section above in every respect that matters:

- **No copy of it is in this repository.** There is no `RizomUVLink` package,
  wheel, `.pyd` or `.dll` here; a search of the tree finds none. Nothing of MIT
  code is redistributed with this add-on.
- It is imported lazily, at runtime, from the RizomUV installation itself: the
  module probes the install folder (`<install dir>\RizomUVLink`) and adds it to
  `sys.path` before importing. Where it is absent — macOS, Linux, or Windows
  without RizomUV installed — the import fails quietly and the add-on falls back
  to the manual FBX Export/Import round trip.
- It stays under **its own** MIT licence, held by Rizom-Lab. It is not covered
  by this project's GPL-3.0-or-later and this project's licence text does not
  extend to it.
- Because nothing is vendored, there is no MIT notice to reproduce here; the
  notice travels with the RizomUV installation that supplies the module.

RizomUV itself is commercial software from Rizom-Lab and is not distributed
with this add-on. Installing it is the user's own step.

---

## 3. Everything else

This section separates a **declaration by the owner** from what an inspection of
this tree can actually verify. They are not the same kind of statement.

**Declared by the owner.** The add-on is described by its author as a personal
project, developed under his own direction and supervision with AI assistance
(Claude Pro), and offered under GPL-3.0-or-later together with its documentation.
That is the author's account of how the code came to exist; it is not something
the repository can be used to prove.

**Verified by inspection.** What this tree shows:

- No file at the repository root or in `operators/` carries a copyright notice,
  SPDX identifier or licence header attributing it to another party. A search for
  `copyright`, `SPDX` and `GPL` over the `*.py` files returns no such notices.
- No third-party Python package is vendored or redistributed. The package imports
  only `bpy`, `bmesh`, `mathutils` and `numpy`, and `numpy` is bundled with
  Blender; there is no `requirements.txt`, wheel, `.pyd` or `.dll` here.
- The only file in `.opencode/` whose external provenance is recorded is the pair
  of ACTD scripts in section 1. Everything else in that folder is development-only
  and is not part of the distributed add-on.

**Not established.** The checks above are an inventory, not a legal audit. They
cannot show that the owner holds copyright in every line, cannot detect material
copied from a source that carries no notice, and cannot exclude contributions made
elsewhere. Where the provenance of a specific file matters, it has to be
established from that file's own history, not from this document. Nothing in
`LICENSE` changes that: choosing a licence states the terms of distribution, it
does not verify title.

---

Copyright (C) 2026 Pierfrancesco Diodato.

Licence text: [LICENSE](LICENSE).
