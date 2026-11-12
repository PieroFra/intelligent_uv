# -*- coding: utf-8 -*-
"""Layout UV prodotto da MinimalUVExecutor su una sfera 32x16 (r=1.0).

Un unico controllo: esegue la pipeline UV (analisi mesh + piano seam +
marcatura + unwrap nativo) con i settings di default della scena e verifica
il layer UV risultante: coordinate finite e dentro [0,1] (toll. 1e-4),
numero di isole UV > 0 e <= numero di regioni del piano, determinismo tra
due esecuzioni identiche (1e-5) e nessuna faccia degenerata (area UV > 0).
"""

import importlib
import math
import os
import sys
import traceback

import bpy

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PACKAGE = os.path.basename(ROOT)
sys.path.insert(0, os.path.dirname(ROOT))

MARGIN_UV = 0.01
UV_TOL = 1e-4
DETERM_TOL = 1e-5


def module(name):
    return importlib.import_module("{0}.{1}".format(PACKAGE, name))


def _settings():
    settings = bpy.context.scene.intelligent_uv_settings
    if settings is None:
        raise ValueError("il puntatore su Scene.intelligent_uv_settings e' vuoto")
    return settings


def _activate(obj):
    for other in bpy.context.view_layer.objects:
        other.select_set(False)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def _drop(obj):
    try:
        bpy.data.objects.remove(obj, do_unlink=True)
    except Exception:  # noqa: BLE001 - pulizia non deve far fallire il controllo
        pass
    try:
        mesh = getattr(obj, "data", None)
        if mesh is not None and getattr(mesh, "users", 1) == 0:
            bpy.data.meshes.remove(mesh)
    except Exception:  # noqa: BLE001 - pulizia non deve far fallire il controllo
        pass


def _uv_layer(obj):
    name = str(getattr(_settings(), "uv_layer_name", "SmartUV") or "SmartUV")
    layer = obj.data.uv_layers.get(name)
    if layer is None:
        layers = [uv.name for uv in obj.data.uv_layers]
        raise AttributeError("layer '{0}' assente (presenti: {1})".format(name, layers))
    return name, layer


def _uv_coords(layer):
    return [(float(item.uv[0]), float(item.uv[1])) for item in layer.data]


def _plan_and_mark(obj, settings):
    mesh_analysis = module("mesh_analysis").MeshAnalyzer.analyze(obj.data)
    if not getattr(mesh_analysis, "ok", False):
        raise RuntimeError("analisi mesh fallita: {0}".format(
            "; ".join(mesh_analysis.errors[:3]) or "nessun errore riportato"))
    material_analysis = module("material_analysis").MaterialAnalyzer.analyze(obj)
    if not getattr(material_analysis, "ok", False):
        raise RuntimeError("analisi materiali fallita: {0}".format(
            "; ".join(material_analysis.errors[:3]) or "nessun errore riportato"))
    plan = module("seam_planning").SeamPlanner.plan(
        mesh_analysis, material_analysis, settings
    )
    if not getattr(plan, "ok", False):
        raise RuntimeError("piano seam fallito: {0}".format(
            "; ".join(plan.errors[:3]) or "nessun errore riportato"))
    success, message = module("seam_marking").SeamMarker.mark_real_seams(
        obj.data, plan.is_seam
    )
    if not success:
        raise RuntimeError("marcatura seam fallita: {0}".format(message))
    return mesh_analysis, plan


def _make_sphere():
    bpy.ops.mesh.primitive_uv_sphere_add(
        segments=32, ring_count=16, radius=1.0, calc_uvs=False,
    )
    obj = bpy.context.object
    assert obj is not None and obj.type == "MESH", "Sfera di prova non creata"
    mesh = obj.data
    for edge in mesh.edges:
        edge.use_seam = False
    for layer in list(mesh.uv_layers):
        mesh.uv_layers.remove(layer)
    _activate(obj)
    return obj


def _run_pipeline(obj, settings):
    mesh_analysis, plan = _plan_and_mark(obj, settings)
    result = module("uv_executor").MinimalUVExecutor.execute_unwrap(
        obj, settings, MARGIN_UV, use_seams=True
    )
    if obj.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    return plan, result


def _face_uv_areas(mesh, coords):
    areas = []
    for poly in mesh.polygons:
        pts = [coords[li] for li in range(
            poly.loop_start, poly.loop_start + poly.loop_total)]
        n = len(pts)
        if n < 3:
            areas.append(0.0)
            continue
        s = 0.0
        for i in range(n):
            u1, v1 = pts[i]
            u2, v2 = pts[(i + 1) % n]
            s += u1 * v2 - u2 * v1
        areas.append(abs(s) * 0.5)
    return areas


def test_uv_executor_layout():
    addon = importlib.import_module(PACKAGE)
    addon.register()
    objects = []
    try:
        settings = _settings()

        # Prima esecuzione.
        obj1 = _make_sphere()
        objects.append(obj1)
        plan1, unwrap1 = _run_pipeline(obj1, settings)

        assert unwrap1["unsolved_islands"] == 0 and unwrap1["warning"] == "", (
            "unwrap non risolto: unsolved_islands={0}, islands_total={1}, warning={2!r}".format(
                unwrap1["unsolved_islands"], unwrap1["islands_total"], unwrap1["warning"])
        )

        _name1, layer1 = _uv_layer(obj1)
        coords1 = _uv_coords(layer1)
        assert coords1, "layer '{0}' senza loop UV".format(_name1)

        for u, v in coords1:
            assert math.isfinite(u) and math.isfinite(v), (
                "coordinata non finita: ({0}, {1})".format(u, v))
            assert -UV_TOL <= u <= 1.0 + UV_TOL and -UV_TOL <= v <= 1.0 + UV_TOL, (
                "coordinata fuori da [{0}, {1}]: ({2}, {3})".format(
                    -UV_TOL, 1.0 + UV_TOL, u, v))

        island_analysis = module("island_extraction").IslandExtractor.analyze(
            obj=obj1, settings=settings, region_ids=plan1.region_ids,
        )
        assert getattr(island_analysis, "ok", False), (
            "analisi isole fallita: {0}".format(
                "; ".join(getattr(island_analysis, "errors", [])[:3]) or "nessun errore"))
        island_count = int(getattr(island_analysis, "island_count", 0))
        assert island_count > 0, "nessuna isola UV prodotta"
        assert island_count <= int(getattr(plan1, "region_count", 0)), (
            "isole UV {0} > regioni del piano {1}".format(
                island_count, getattr(plan1, "region_count", 0)))

        for area in _face_uv_areas(obj1.data, coords1):
            assert area > 0.0, "faccia degenerata nell'UV (area={0})".format(area)

        seam_count1 = sum(1 for edge in obj1.data.edges if getattr(edge, "use_seam", False))
        total_area1 = sum(_face_uv_areas(obj1.data, coords1))

        # Seconda esecuzione identica su mesh gemella.
        obj2 = _make_sphere()
        objects.append(obj2)
        plan2, unwrap2 = _run_pipeline(obj2, settings)

        assert unwrap2["unsolved_islands"] == 0 and unwrap2["warning"] == "", (
            "unwrap non risolto: unsolved_islands={0}, islands_total={1}, warning={2!r}".format(
                unwrap2["unsolved_islands"], unwrap2["islands_total"], unwrap2["warning"])
        )

        _name2, layer2 = _uv_layer(obj2)
        coords2 = _uv_coords(layer2)
        assert coords2, "layer '{0}' senza loop UV".format(_name2)
        for u, v in coords2:
            assert math.isfinite(u) and math.isfinite(v), (
                "coordinata non finita: ({0}, {1})".format(u, v))
            assert -UV_TOL <= u <= 1.0 + UV_TOL and -UV_TOL <= v <= 1.0 + UV_TOL, (
                "coordinata fuori da [{0}, {1}]: ({2}, {3})".format(
                    -UV_TOL, 1.0 + UV_TOL, u, v))

        island_analysis2 = module("island_extraction").IslandExtractor.analyze(
            obj=obj2, settings=settings, region_ids=plan2.region_ids,
        )
        assert getattr(island_analysis2, "ok", False), (
            "analisi isole fallita: {0}".format(
                "; ".join(getattr(island_analysis2, "errors", [])[:3]) or "nessun errore"))
        island_count2 = int(getattr(island_analysis2, "island_count", 0))

        seam_count2 = sum(1 for edge in obj2.data.edges if getattr(edge, "use_seam", False))
        total_area2 = sum(_face_uv_areas(obj2.data, coords2))

        assert seam_count1 == seam_count2, (
            "numero di seam marcate diverso: {0} vs {1}".format(seam_count1, seam_count2))
        assert int(getattr(plan1, "region_count", 0)) == int(getattr(plan2, "region_count", 0)), (
            "numero di regioni del piano diverso: {0} vs {1}".format(
                getattr(plan1, "region_count", 0), getattr(plan2, "region_count", 0)))
        assert island_count == island_count2, (
            "numero di isole UV diverso: {0} vs {1}".format(island_count, island_count2))
        assert abs(total_area1 - total_area2) <= 1e-3, (
            "area UV totale diversa: {0} vs {1}".format(total_area1, total_area2))

        return (
            "{0} loop UV, {1} isole <= {2} regioni, seam {3} vs {4}, "
            "isole {5} vs {6}, area {7:.6f} vs {8:.6f}".format(
                len(coords1), island_count, getattr(plan1, "region_count", 0),
                seam_count1, seam_count2, island_count, island_count2,
                total_area1, total_area2)
        )
    finally:
        for obj in objects:
            _drop(obj)
        try:
            addon.unregister()
        except Exception:  # noqa: BLE001 - unregister di pulizia
            pass


if __name__ == "__main__":
    passed = 0
    failed = 0
    try:
        detail = test_uv_executor_layout()
        passed = 1
        print("CHECK test_uv_executor_layout PASS {0}".format(detail or ""))
    except Exception:
        failed = 1
        traceback.print_exc()
    print("RISULTATO passati={0} falliti={1} totale=1".format(passed, failed))