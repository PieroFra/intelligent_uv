# -*- coding: utf-8 -*-
"""Orientamento isole UV (rotating calipers) su una sfera 32x16 (r=1.0).

Un unico controllo: esegue la pipeline UV di default, analizza le isole reali,
applica orient_islands e verifica che l'area UV per isola resti invariata,
che non compaiano coordinate non finite, che l'area del bounding box per isola
non aumenti e che due esecuzioni identiche producano lo stesso risultato.
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


def _island_stats(island_analysis):
    stats = []
    for rec in island_analysis.islands:
        bbox_area = (
            (float(rec["bbox_max_u"]) - float(rec["bbox_min_u"]))
            * (float(rec["bbox_max_v"]) - float(rec["bbox_min_v"]))
        )
        stats.append((float(rec["uv_area"]), bbox_area))
    return stats


def _run_once(obj, settings):
    plan, unwrap = _run_pipeline(obj, settings)
    assert unwrap["unsolved_islands"] == 0 and unwrap["warning"] == "", (
        "unwrap non risolto: unsolved_islands={0}, islands_total={1}, warning={2!r}".format(
            unwrap["unsolved_islands"], unwrap["islands_total"], unwrap["warning"])
    )
    _name, layer = _uv_layer(obj)
    coords_before = _uv_coords(layer)
    for u, v in coords_before:
        assert math.isfinite(u) and math.isfinite(v), (
            "coordinata non finita prima dell'orientamento: ({0}, {1})".format(u, v))

    island_analysis = module("island_extraction").IslandExtractor.analyze(
        obj=obj, settings=settings, region_ids=plan.region_ids,
    )
    assert getattr(island_analysis, "ok", False), (
        "analisi isole fallita: {0}".format(
            "; ".join(getattr(island_analysis, "errors", [])[:3]) or "nessun errore"))
    assert len(island_analysis.islands) > 0, "nessuna isola UV prodotta"

    before_stats = _island_stats(island_analysis)

    orient = module("orientation")
    orient_result = orient.orient_islands(obj.data, layer, island_analysis)

    island_analysis_after = module("island_extraction").IslandExtractor.analyze(
        obj=obj, settings=settings, region_ids=plan.region_ids,
    )
    assert getattr(island_analysis_after, "ok", False), (
        "analisi isole dopo orientamento fallita: {0}".format(
            "; ".join(getattr(island_analysis_after, "errors", [])[:3]) or "nessun errore"))

    after_stats = _island_stats(island_analysis_after)

    assert len(before_stats) == len(after_stats), (
        "numero di isole cambiato: {0} vs {1}".format(len(before_stats), len(after_stats)))
    for i, ((area_before, bbox_before), (area_after, bbox_after)) in enumerate(
            zip(before_stats, after_stats)):
        assert abs(area_before - area_after) <= 1e-4, (
            "area UV isola {0} non invariata: {1} vs {2}".format(i, area_before, area_after))
        assert bbox_after <= bbox_before + 1e-6, (
            "area bounding box isola {0} aumentata: {1} vs {2}".format(
                i, bbox_after, bbox_before))

    _name2, layer2 = _uv_layer(obj)
    coords_after = _uv_coords(layer2)
    for u, v in coords_after:
        assert math.isfinite(u) and math.isfinite(v), (
            "coordinata non finita dopo l'orientamento: ({0}, {1})".format(u, v))

    return coords_after, orient_result, sorted(a for a, _ in after_stats)


def test_orientation():
    addon = importlib.import_module(PACKAGE)
    addon.register()
    objects = []
    try:
        settings = _settings()

        obj1 = _make_sphere()
        objects.append(obj1)
        coords1, result1, areas1 = _run_once(obj1, settings)

        obj2 = _make_sphere()
        objects.append(obj2)
        coords2, result2, areas2 = _run_once(obj2, settings)

        assert len(coords1) == len(coords2), (
            "numero di loop UV diverso: {0} vs {1}".format(len(coords1), len(coords2)))
        # determinismo strutturale (il packing di Blender non garantisce
        # coordinate bit-identiche tra esecuzioni)
        assert len(areas1) == len(areas2), (
            "numero di isole (aree) diverso: {0} vs {1}".format(len(areas1), len(areas2)))
        for i, (a1, a2) in enumerate(zip(sorted(areas1), sorted(areas2))):
            assert abs(a1 - a2) <= 1e-4, (
                "area UV isola {0} non deterministica: {1} vs {2}".format(i, a1, a2))
        for label, coords in (("prima", coords1), ("seconda", coords2)):
            for u, v in coords:
                assert math.isfinite(u) and math.isfinite(v), (
                    "coordinata non finita ({0}): ({1}, {2})".format(label, u, v))
                assert 0.0 - 1e-9 <= u <= 1.0 + 1e-9 and 0.0 - 1e-9 <= v <= 1.0 + 1e-9, (
                    "coordinata fuori [0,1] ({0}): ({1}, {2})".format(label, u, v))

        assert result1.islands == result2.islands, (
            "numero di isole elaborate diverso: {0} vs {1}".format(
                result1.islands, result2.islands))
        assert result1.rotated == result2.rotated, (
            "numero di isole ruotate diverso: {0} vs {1}".format(
                result1.rotated, result2.rotated))
        assert abs(result1.area_before - result2.area_before) <= 1e-6, (
            "area bounding prima diversa: {0} vs {1}".format(
                result1.area_before, result2.area_before))
        assert abs(result1.area_after - result2.area_after) <= 1e-6, (
            "area bounding dopo diversa: {0} vs {1}".format(
                result1.area_after, result2.area_after))

        return (
            "{0} loop UV, isole elaborate {1}, ruotate {2}, area before {3:.6f}, "
            "area after {4:.6f}".format(
                len(coords1), result1.islands, result1.rotated,
                result1.area_before, result1.area_after)
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
        detail = test_orientation()
        passed = 1
        print("CHECK test_orientation PASS {0}".format(detail or ""))
    except Exception:
        failed = 1
        traceback.print_exc()
    print("RISULTATO passati={0} falliti={1} totale=1".format(passed, failed))
