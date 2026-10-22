# pylint: disable=invalid-name
"""Intelligent UV Mapping — diagnostic operator."""

import bpy

from ..curvature import CurvatureEstimator
from ..distortion import DistortionAnalyzer
from ..island_extraction import IslandExtractor
from ..margins import MarginCalculator
from ..material_analysis import MaterialAnalyzer
from ..mesh_analysis import MeshAnalyzer, MeshAnalysisResult
from ..seam_planning import SeamPlanner
from ..uv_executor import MinimalUVExecutor
from ..validation import ContextGuard


class IntelligentUV_OT_Diagnose(bpy.types.Operator):
    """Reports which mesh APIs this Blender build exposes."""

    bl_idname = "intelligent_uv.diagnose"
    bl_label = "Diagnose Mesh API"
    bl_description = (
        "Inspects the mesh API of this Blender version and prints a report "
        "to the System Console (Window > Toggle System Console)."
    )
    bl_options = {'REGISTER'}

    def execute(self, context):
        obj = ContextGuard.get_context_object(context)

        if not obj or obj.type != 'MESH':
            self.report({'ERROR'}, "Select a mesh object first.")
            return {'CANCELLED'}

        if context.mode != 'OBJECT':
            try:
                bpy.ops.object.mode_set(mode='OBJECT')
            except Exception:
                # A: mode_set refuses when no object is active. The caller checks
                # the mode it actually got rather than trusting this to succeed.
                pass

        mesh = obj.data
        lines = []

        def add(text):
            lines.append(text)

        # The add-on version goes in the header: without it there is no way to
        # tell from a log whether a fix is actually running, and a stale install
        # looks identical to a fix that did not work.
        try:
            from .. import bl_info as _bl_info
            version = ".".join(str(n) for n in _bl_info.get("version", ()))
        except Exception:
            version = "unknown"

        add("=" * 62)
        add("INTELLIGENT UV — MESH API DIAGNOSTIC")
        add(f"Add-on: v{version}  |  Blender: {bpy.app.version_string}")
        add(f"Object: {obj.name}")
        add("=" * 62)

        # --- Raw counts -------------------------------------------------
        for name in ("vertices", "edges", "polygons", "loops"):
            coll = getattr(mesh, name, None)
            try:
                add(f"mesh.{name:<10} : {len(coll)}")
            except Exception as exc:
                add(f"mesh.{name:<10} : UNAVAILABLE ({exc})")

        # --- Attribute probes -------------------------------------------
        add("-" * 62)
        add("Attribute probes:")

        try:
            poly = mesh.polygons[0]
            for attr in ("index", "vertices", "loop_start", "loop_total", "normal", "area"):
                value = getattr(poly, attr, "<MISSING>")
                if attr == "vertices" and value != "<MISSING>":
                    try:
                        value = list(value)
                    except Exception:
                        value = "<UNREADABLE>"
                add(f"  polygon.{attr:<12} = {value}")
        except Exception as exc:
            add(f"  polygon probe failed: {exc}")

        try:
            loop = mesh.loops[0]
            for attr in ("index", "edge_index", "vertex_index", "edge"):
                add(f"  loop.{attr:<15} = {getattr(loop, attr, '<MISSING>')}")
        except Exception as exc:
            add(f"  loop probe failed: {exc}")

        try:
            edge = mesh.edges[0]
            for attr in ("index", "vertices", "use_seam"):
                value = getattr(edge, attr, "<MISSING>")
                if attr == "vertices" and value != "<MISSING>":
                    value = list(value)
                add(f"  edge.{attr:<15} = {value}")
        except Exception as exc:
            add(f"  edge probe failed: {exc}")

        try:
            names = [a.name for a in mesh.attributes]
            add(f"  mesh.attributes      = {names}")
        except Exception as exc:
            add(f"  mesh.attributes      : UNAVAILABLE ({exc})")

        # UV layers: which exist, which is active, and whether the target layer
        # actually holds coordinates. An unwrap that writes to one layer while
        # the analysis reads another reports zero UV area everywhere.
        add("-" * 62)
        try:
            uv_layers = mesh.uv_layers
            active = getattr(uv_layers, "active", None)
            add(f"UV layers             : {[l.name for l in uv_layers]}")
            add(f"  active              = {getattr(active, 'name', '<NONE>')}")

            settings = context.scene.intelligent_uv_settings
            target = str(getattr(settings, "uv_layer_name", "SmartUV") or "SmartUV")
            add(f"  target (settings)   = {target}")

            if active is not None and getattr(active, "name", None) != target:
                add(
                    "  MISMATCH: the active layer is not the target layer. "
                    "Unwrapping writes to the active one while the analysis "
                    "reads the target one."
                )

            for layer in uv_layers:
                data = getattr(layer, "data", [])
                min_u = min_v = float("inf")
                max_u = max_v = -float("inf")
                for item in data:
                    u, v = float(item.uv[0]), float(item.uv[1])
                    min_u, max_u = min(min_u, u), max(max_u, u)
                    min_v, max_v = min(min_v, v), max(max_v, v)

                if min_u == float("inf"):
                    add(f"  '{layer.name}': empty")
                else:
                    span = max(max_u - min_u, max_v - min_v)
                    flag = "  <-- DEGENERATE (all coordinates equal)" if span < 1e-8 else ""
                    add(
                        f"  '{layer.name}': {len(data)} loops, "
                        f"u [{min_u:.4f}, {max_u:.4f}] v [{min_v:.4f}, {max_v:.4f}]{flag}"
                    )
        except Exception as exc:
            add(f"UV layers             : UNAVAILABLE ({exc})")

        # --- bmesh path --------------------------------------------------
        add("-" * 62)
        probe = MeshAnalysisResult()
        bmesh_ok = MeshAnalyzer._analyze_with_bmesh(mesh, probe)
        add(f"bmesh path            : {'OK' if bmesh_ok else 'FAILED'}")
        if bmesh_ok:
            pairs = sum(1 for f in probe.faces_per_edge if len(f) == 2)
            add(f"  edges linking 2 faces = {pairs} / {probe.edge_count}")
            add(f"  total area            = {probe.total_area:.6f}")
        for warning in probe.warnings:
            add(f"  warning: {warning}")

        # --- Full analysis -----------------------------------------------
        add("-" * 62)
        ma = MeshAnalyzer.analyze(mesh)
        add(f"MeshAnalyzer.ok       : {ma.ok}   (source: {ma.topology_source})")
        add(f"  faces/edges           = {ma.face_count} / {ma.edge_count}")
        add(f"  manifold edges        = {ma.manifold_edge_count}")
        add(f"  boundary edges        = {len(ma.boundary_edges)}")
        add(f"  components            = {ma.component_count}")
        for err in ma.errors:
            add(f"  ERROR: {err}")
        for warning in ma.warnings:
            add(f"  warning: {warning}")

        # --- Angles and seams ---------------------------------------------
        if ma.ok:
            angles = CurvatureEstimator.collect_angles(ma)
            add("-" * 62)
            if angles:
                add(
                    f"Dihedral angles       : {len(angles)} samples, "
                    f"min {min(angles):.1f}, max {max(angles):.1f}, "
                    f"mean {sum(angles)/len(angles):.1f}"
                )
            else:
                add("Dihedral angles       : NONE (this is why no seam is found)")

            settings = context.scene.intelligent_uv_settings
            estimate = CurvatureEstimator.estimate(
                ma, fallback=settings.curvature_threshold
            )
            add(f"Auto curvature        : {estimate.threshold:.1f} ({estimate.method})")

            material_analysis = MaterialAnalyzer.analyze(obj, ma)
            margin = MarginCalculator.calculate(settings, ma, max(1, ma.component_count))
            add(
                f"Margin                : {margin.margin_px}px @ "
                f"{margin.texture_resolution} ({margin.margin_uv:.5f} UV)"
            )
            add(f"Min seam edge length  : {margin.min_seam_edge_length:.6f}")

            short_edges = sum(
                1 for length in ma.edge_lengths
                if length < margin.min_seam_edge_length
            )
            pct = 100.0 * short_edges / max(1, ma.edge_count)
            flag = "  <-- these edges are invisible to the seam planner" if pct > 20 else ""
            add(f"  edges below that      = {short_edges} / {ma.edge_count} ({pct:.0f}%){flag}")

            if getattr(margin, "seam_margin_capped", False):
                add("  seam margin was CAPPED to keep the planner usable")
            for warning in getattr(margin, "warnings", []) or []:
                add(f"  warning: {warning}")

            method = str(getattr(settings, "seam_method", "THRESHOLD") or "THRESHOLD")
            add(f"Seam method           : {method}")

            if method == 'VSA':
                from .. import vsa as _vsa
                vres = _vsa.plan_seams(ma, material_analysis, settings)
                add(
                    f"VSA clusters          : {vres.cluster_count}, "
                    f"{len(vres.seam_edges)} seams "
                    f"({vres.boundary_seam_count} borders, "
                    f"{vres.topology_seam_count} from paths)"
                )
                add(
                    f"  topology            : {vres.discs} discs, "
                    f"{vres.non_discs} non-discs, {vres.rings_resolved} opened"
                )
                for w in vres.warnings[:4]:
                    add(f"  warning: {w}")

            plan = SeamPlanner.plan(ma, material_analysis, settings, margin)
            add(
                f"SeamPlanner.ok        : {plan.ok} -> "
                f"{len(plan.seam_edges)} seams, {plan.region_count} regions"
            )
            for err in plan.errors:
                add(f"  ERROR: {err}")

            # Per-island breakdown of the CURRENT layout, which is what tells
            # whether collapsed faces are concentrated or spread everywhere.
            add("-" * 62)
            try:
                uv_layer = MinimalUVExecutor.get_uv_layer(
                    mesh,
                    str(getattr(settings, "uv_layer_name", "SmartUV") or "SmartUV"),
                )
                islands = IslandExtractor.analyze(
                    obj=obj, settings=settings,
                    material_analysis=material_analysis,
                    region_ids=plan.region_ids,
                )

                target_name = str(
                    getattr(settings, "uv_layer_name", "SmartUV") or "SmartUV"
                )
                measured = getattr(uv_layer, "name", None)

                if uv_layer is None or not islands.ok:
                    add("Per-island report     : unavailable")
                elif measured != target_name:
                    # get_uv_layer falls back to the first layer when the target
                    # is missing, so the numbers would silently describe some
                    # other layout — typically the one the model shipped with.
                    add(
                        f"Per-island report     : SKIPPED. '{target_name}' does "
                        f"not exist yet; the only layer is '{measured}', which "
                        "was not produced by this add-on. Run Intelligent UV "
                        "first, then run this diagnostic again."
                    )
                else:
                    rows = DistortionAnalyzer.per_island_report(
                        mesh, uv_layer, ma, islands, worst=12
                    )
                    total_collapsed = sum(r["collapsed"] for r in rows)
                    add(
                        f"Per-island report     : layer '{measured}', "
                        f"{islands.island_count} islands, {total_collapsed} "
                        f"collapsed faces in the worst {len(rows)}"
                    )
                    add("  id   faces  collapsed  density(x mean)  uv_area")
                    for r in rows:
                        add(
                            f"  {r['id']:<4} {r['faces']:>6} {r['collapsed']:>10}"
                            f"  {r['relative']:>14.2f}  {r['uv_area']:.6f}"
                        )
            except Exception as exc:
                add(f"Per-island report     : failed ({exc})")

        add("=" * 62)

        report_text = "\n".join(lines)
        print("\n" + report_text + "\n")

        # Also store it in a text datablock so it can be copied out easily.
        try:
            text_name = "IntelligentUV_Diagnostic"
            text_block = bpy.data.texts.get(text_name) or bpy.data.texts.new(text_name)
            text_block.clear()
            text_block.write(report_text)
            self.report(
                {'INFO'},
                f"Diagnostic written to the System Console and to the "
                f"'{text_name}' text block.",
            )
        except Exception:
            self.report({'INFO'}, "Diagnostic printed to the System Console.")

        return {'FINISHED'}
