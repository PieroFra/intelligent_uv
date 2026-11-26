# Gate G1 — Interactive Verification Checklist (`bolt_action_rifle_7_62`)

## Asset
- **Model:** `bolt_action_rifle_7_62` (Poly Haven CC0 — download from Poly Haven if not yet in your local library; do not commit the `.blend` or textures to Git).
- **Environment:** Blender 5.2 LTS (with `intelligent_uv` installed from `feat/0.37-gate-catchup` or the Native ZIP `dist/intelligent_uv-0.36.3-nativo-extension.zip`).

## Manual Steps (No Video Required)
1. Open `bolt_action_rifle_7_62` in Blender 5.2 and select the main mesh object(s).
2. Open **View3D > Sidebar (N) > Intelligent UV**.
3. Verify the UI layout is clean (in the Native build, confirm there is no RizomUV path picker or External Editor box).
4. Run **Diagnose** / **Auto Params** and note the derived tolerance and crease weight.
5. Click **Run Intelligent UV** (native Blender-only pipeline).
6. In the **UV Editor**:
   - Enable **Display Stretch (Angle/Area)** and confirm no severely inverted or collapsed islands.
   - Check **Select Overlap** (`UV > Select Overlap`) and confirm `0` overlapping faces.
   - Verify texel density consistency across receiver, barrel, and stock.
7. Record the verdict (`PASS` / `FAIL`, coverage %, overlap count, and any visual notes) in `VERIFICATION.md`.
