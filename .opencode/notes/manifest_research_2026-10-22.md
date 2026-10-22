# Manifest research — Intelligent UV

Access date: **2026-10-22**
Status: internal note, non-gate. Evidence reported as collected; no new research was performed
while writing this file.

Everything under "Documented facts" comes from the official Blender manual pages listed below.
Everything under "Recommendation" is our own judgement and is **not** a documented requirement.

---

## Sources accessed (2026-10-22)

| ID | URL |
|---|---|
| `gs42` | https://docs.blender.org/manual/en/4.2/advanced/extensions/getting_started.html |
| `gs52` | https://docs.blender.org/manual/en/5.2/advanced/extensions/getting_started.html |
| `addons42` | https://docs.blender.org/manual/en/4.2/advanced/extensions/addons.html |
| `addons52` | https://docs.blender.org/manual/en/5.2/advanced/extensions/addons.html |
| `lic42` | https://docs.blender.org/manual/en/4.2/advanced/extensions/licenses.html |
| `lic52` | https://docs.blender.org/manual/en/5.2/advanced/extensions/licenses.html |
| `pref42` | https://docs.blender.org/manual/en/4.2/editors/preferences/addons.html |
| `pref52` | https://docs.blender.org/manual/en/5.2/editors/preferences/addons.html |
| `prefext52` | https://docs.blender.org/manual/en/5.2/editors/preferences/extensions.html |

---

## Documented facts

### 1. Installing from Preferences: no manifest needed for the legacy path

The Preferences → Add-ons page documents the classic install flow and explicitly includes
legacy add-ons (`pref42`, `pref52`, same wording):

> "Install from Disk … can also be used to install legacy Add-ons"

> "Installing Legacy Add-ons: … select the add-on's .py file (if it has only one such file) or its
> .zip file. The add-on will not be automatically enabled after installation."

The manifest is mandatory only for the **extension** format (`gs42`, `gs52`):

> "An extension is shared as a .zip archive containing a manifest file"

> "Add-ons need at least the manifest and an `__init__.py` file"

Current state of this project: a **legacy add-on** (flat package, registered by `bl_info`),
installed from its `.py` file or its folder. It is therefore not required to ship a manifest in
order to be installable from Preferences.

### 2. Manifest fields (`gs42`, identical in 4.2 and 5.2)

Required:

| Field | Documented requirement |
|---|---|
| `schema_version` | `1.0.0` |
| `id` | unique identifier of the extension |
| `version` | semantic versioning |
| `name` | display name |
| `tagline` | short description, no ending punctuation |
| `maintainer` | maintainer entry |
| `type` | `add-on` |
| `license` | SPDX expression list |
| `blender_version_min` | "use at least 4.2.0" |

Optional:

| Field | Documented note |
|---|---|
| `blender_version_max` | upper bound |
| `website` | project URL |
| `copyright` | copyright line |
| `tags` | list of tags |
| `platforms` | "If omitted, the extension will be available in all operating systems"; values `windows-x64`, `windows-arm64`, `macos-x64`, `macos-arm64`, `linux-x64` |
| `wheels` | bundled Python wheels |
| `permissions` | `files`, `network`, `clipboard`, `camera`, `microphone`, each with a short explanation |
| `[build] paths_exclude_pattern` | glob patterns excluded at build time |

General rule stated on the same page: every value that is present must be filled in; omit the key
rather than leaving it empty.

### 3. Integrity note — tagline length

The limit "tagline ≤ 64 characters" was **not found** in the manual pages accessed above.
Report it as *not found in the accessed manual pages; unverified*. Do not repeat it as a fact
without a source.

### 4. License (`lic42` and `lic52`, identical)

> "For add-ons, the required license is GNU General Public License v3.0 or later"

Example form (`gs42`) uses the SPDX prefix:

```toml
license = ["SPDX:GPL-3.0-or-later"]
```

For assets the corresponding requirement is CC0.

### 5. Blender 4.2 vs 5.2

- Default `[build] paths_exclude_pattern`, under the sentence
  "If the [build] table isn't declared the following default is used":

  ```toml
  paths_exclude_pattern = [
    "__pycache__/",
    ".*",
    "*.zip",
  ]
  ```

  Same default in both versions.
- API spelling difference: `bpy.app.online_access_overriden` (4.2) vs
  `bpy.app.online_access_override` (5.2). Anything relying on that flag needs an explicit
  fallback.
- `maintainer` examples are identical in the pages read, so **no documented difference** on
  `maintainer` between 4.2 and 5.2.

### 6. `bl_info` during conversion (`gs42`, `gs52`)

Conversion guide steps, same wording in both versions:

> "Create a manifest file."

> "Remove the bl_info information (this is now in the manifest)."

No automatic consistency rule between `bl_info` and the manifest is documented anywhere in the
pages read.

---

## Recommendation (ours, not documented)

1. For the first GitHub ZIP release, the **legacy path is enough**: the manifest is not required,
   and the existing `bl_info` keeps the add-on installable from Preferences → Add-ons →
   Install from Disk.
2. If the target becomes Blender Extensions, add a `blender_manifest.toml` with all the required
   fields from section 2, plus:
   - `license = ["SPDX:GPL-3.0-or-later"]`
   - `blender_version_min = "4.2.0"`
3. In that case we would keep `version`, `author` and `min` aligned with the current `bl_info`
   values (0.34.0 / Pierfrancesco Diodato / 4.2.0). **This alignment is our recommendation, not a
   documented requirement.**
4. Remove `bl_info` only when the add-on is really converted to an extension; there is no
   documented reason to delete it while shipping the legacy format.
5. Do not assert the 64-character tagline limit (section 3) in any public documentation until a
   source is found.
