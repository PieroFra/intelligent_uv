# Verification Record: Intelligent UV Mapping 0.36.0

This file is the release verification record for v0.36.0: what was packaged
and which automated suites ran against it. Every number below is read from a
real log, hash file or verdict line, and each one names its source.

## Release Artifact (GitHub edition)

| Item | Value |
|---|---|
| ZIP | `dist/intelligent_uv-0.36.0.zip` (236990 bytes) |
| SHA-256 | `d62457832b7e242ab4db284c3356b2f8353af91faf4c7d777c4183ee42b01936` |
| Hash check | value in `dist/intelligent_uv-0.36.0.sha256` |
| Files | 56 total: 52 `.py` (33 root modules + 10 in `operators/` + 9 in `tests/`) + 4 docs (`LICENSE`, `README.md`, `CHANGELOG.md`, `THIRD_PARTY.md`) |
| File list | `dist/intelligent_uv-0.36.0.files.txt` (header: `bl_info.version (0, 36, 0)`, `generated 2026-11-08T21:00:57+01:00 deterministic build`) |

The `dist/` directory is gitignored on purpose: no binary artifacts are
versioned in the repository.

## Native Extension Artifact (Blender Extensions edition)

| Item | Value |
|---|---|
| ZIP | `dist/intelligent_uv-0.36.0-nativo-extension.zip` (213688 bytes) |
| SHA-256 | `9dd0ccc55c23a93e13e4c1849f468e53eb6691ea29470b347579128fbf594f33` (matches `dist/intelligent_uv-0.36.0-nativo-extension.sha256`; the staging variant `dist/intelligent_uv-0.36.0-nativo.zip` has a different hash, `2a1ff221c4cd...e7fad`, and is not the published artifact) |
| Published as | Blender Extensions 0.36.0, status **Awaiting Review**, requested permissions: **Files** only |
| Files | 53 total: 49 `.py` + 4 docs — `rizomuv_bridge.py`, `rizomuv_link.py` and `rizomuv_script.py` are physically absent (file list: `dist/intelligent_uv-0.36.0-nativo.files.txt`) |

## Automated Headless Suites (Blender 5.2.0 LTS, build `fbe6228777e7`)

**Smoke suite** (`.opencode/tests/test_out.txt`, run 2026-11-08 21:05):

```
RISULTATO passati=14 falliti=0 totale=14
```

**Regression suite** (`.opencode/verdict.txt`, task `iuv-0360-regression-1108-a`,
run `20261108210226-c5be38f2`):

```
VERIFY_OK | passed=60 | failed=0 | diff=45 | index=UPDATED | build=SKIPPED
```

**UI probe** (`%TEMP%/opencode/iuv_gui/ui_report.txt`, run 2026-11-08 19:51,
labels measured with `blf.dimensions`):

```
UI_SUMMARY labels=88 flagged=0 region_width=561 min_safe_width=422
```

Identical result on `it_IT` and `en_US` (`PROBE it ... labels=88 flagged=0`,
`PROBE en ... labels=88 flagged=0`): the panel labels are drawn in English in
code, so the layout metric is the same in both interface languages.

## Clean Install of the Native Extension (gate G3)

**PASS for the 0.36.0 native artifact**: the gate script
`.opencode/scripts/gate_g3_native_install.ps1` installed
`dist/intelligent_uv-0.36.0-nativo-extension.zip` (SHA-256
`9dd0ccc55c23a93e13e4c1849f468e53eb6691ea29470b347579128fbf594f33`) on a
clean Blender profile; its verdict line is `G3_NATIVE OK` (last line of the
gate run).

## Carried Evidence from 0.35.1

The following proofs were produced against the v0.35.1 artifact and are NOT
re-certified for 0.36.0; they document behavior of the shared pipeline code
that was verified interactively in that cycle:

- Clean install from the v0.35.1 GitHub ZIP (2026-10-25): 7 automated steps,
  0 failures, `bl_info["version"] (0, 35, 1)`.
- Release audit: secrets and PII at HEAD and over full history (2026-10-25):
  0 credential hits, PII only in commit metadata.
- Interactive desktop session with RizomUV 2025.0.117 (2026-10-25): Live Link,
  Lua Script and Auto round trips, face match 100% on `Suzanne` (500/500,
  1968 loops) and `G2TestCube` (6/6, 24 loops).
- Pipeline suite 13/13 (2026-10-25, `.opencode/tests/pipeline_out.txt`).

Re-running these against 0.36.0 is pending and required before claiming the
corresponding gates for this release.

## Gate Summary

| Gate | Verdict |
|---|---|
| G1 smoke + regression on 0.36.0 | **PASS**, 2026-11-08 (14/14 smoke, 60/0 regression) |
| G3 clean install of the native extension | **PASS**, `G3_NATIVE OK` on `dist/intelligent_uv-0.36.0-nativo-extension.zip` (SHA-256 `9dd0ccc55c23a93e13e4c1849f468e53eb6691ea29470b347579128fbf594f33`) |
| G2 manual RizomUV round trip on 0.36.0 | **NOT RE-RUN** (0.35.1 evidence: PASS, 2026-10-23) |
| Pipeline suite on 0.36.0 | **NOT RE-RUN** (0.35.1 evidence: 13/13, 2026-10-25) |
