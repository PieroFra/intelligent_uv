# -*- coding: utf-8 -*-
"""Stacking di isole duplicate su sfera 32x16: nessun accoppiamento, zero impilate."""

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
UV_TOL = 1e-6


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
    return mesh_analysis, plan, result


def test_stacking():
    addon = importlib.import_module(PACKAGE)
    addon.register()
    objects = []
    try:
        settings = _settings()

        obj = _make_sphere()
        objects.append(obj)

        mesh_analysis, plan, unwrap = _run_pipeline(obj, settings)
        assert unwrap["unsolved_islands"] == 0 and unwrap["warning"] == "", (
            "unwrap non risolto: unsolved_islands={0}, islands_total={1}, warning={2!r}".format(
                unwrap["unsolved_islands"], unwrap["islands_total"], unwrap["warning"])
        )

        _name, layer = _uv_layer(obj)
        coords_before = _uv_coords(layer)

        island_analysis = module("island_extraction").IslandExtractor.analyze(
            obj=obj, settings=settings, region_ids=plan.region_ids,
        )
        assert getattr(island_analysis, "ok", False), (
            "analisi isole fallita: {0}".format(
                "; ".join(getattr(island_analysis, "errors", [])[:3]) or "nessun errore"))
        assert len(island_analysis.islands) > 0, "nessuna isola UV prodotta"
        islands_before = len(island_analysis.islands)

        stacking = module("stacking")

        # Prima chiamata: nessuna isola e' duplicata, quindi nessuna coordinata
        # UV deve cambiare e il conteggio di isole impilate deve essere zero.
        res1 = stacking.stack_duplicates(
            obj.data, layer, island_analysis, mesh_analysis, tolerance=0.02,
        )
        coords_after1 = _uv_coords(layer)
        assert len(coords_before) == len(coords_after1), (
            "numero di loop UV cambiato: {0} vs {1}".format(
                len(coords_before), len(coords_after1)))
        for i, ((u0, v0), (u1, v1)) in enumerate(zip(coords_before, coords_after1)):
            assert abs(u0 - u1) <= UV_TOL and abs(v0 - v1) <= UV_TOL, (
                "coordinata UV cambiata all'isola/loop {0}: ({1}, {2}) vs ({3}, {4})".format(
                    i, u0, v0, u1, v1))
        assert getattr(res1, "stacked", 0) == 0, (
            "isole impilate attese 0, trovate {0}".format(getattr(res1, "stacked", None)))

        island_analysis_after1 = module("island_extraction").IslandExtractor.analyze(
            obj=obj, settings=settings, region_ids=plan.region_ids,
        )
        assert getattr(island_analysis_after1, "ok", False), (
            "analisi isole dopo prima chiamata fallita: {0}".format(
                "; ".join(getattr(island_analysis_after1, "errors", [])[:3]) or "nessun errore"))
        assert len(island_analysis_after1.islands) == islands_before, (
            "numero di isole elaborate cambiato: {0} vs {1}".format(
                len(island_analysis_after1.islands), islands_before))

        # Seconda chiamata: deve dare lo stesso risultato della prima.
        res2 = stacking.stack_duplicates(
            obj.data, layer, island_analysis_after1, mesh_analysis, tolerance=0.02,
        )
        coords_after2 = _uv_coords(layer)
        for i, ((u1, v1), (u2, v2)) in enumerate(zip(coords_after1, coords_after2)):
            assert abs(u1 - u2) <= UV_TOL and abs(v1 - v2) <= UV_TOL, (
                "seconda chiamata ha cambiato coordinate al loop {0}: ({1}, {2}) vs ({3}, {4})".format(
                    i, u1, v1, u2, v2))
        assert getattr(res2, "stacked", 0) == getattr(res1, "stacked", 0), (
            "conteggio isole impilate diverso tra le due chiamate: {0} vs {1}".format(
                getattr(res2, "stacked", None), getattr(res1, "stacked", None)))
        assert getattr(res2, "groups", 0) == getattr(res1, "groups", 0), (
            "gruppi diversi tra le due chiamate: {0} vs {1}".format(
                getattr(res2, "groups", None), getattr(res1, "groups", None)))
        assert getattr(res2, "rejected", 0) == getattr(res1, "rejected", 0), (
            "rifiutati diversi tra le due chiamate: {0} vs {1}".format(
                getattr(res2, "rejected", None), getattr(res1, "rejected", None)))

        return (
            "{0} loop UV, isole {1}, impilate {2}".format(
                len(coords_before), islands_before, getattr(res1, "stacked", 0))
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
        detail = test_stacking()
        passed = 1
        print("CHECK test_stacking PASS {0}".format(detail or ""))
    except Exception:
        failed = 1
        traceback.print_exc()
    print("RISULTATO passati={0} falliti={1} totale=1".format(passed, failed))
