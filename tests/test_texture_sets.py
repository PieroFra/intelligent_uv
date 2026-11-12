# -*- coding: utf-8 -*-
"""Texture sets: raggruppamento per materiale e pack per materiale su cubo a due materiali."""

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
        if obj is not None:
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


def _make_cube_two_materials():
    bpy.ops.mesh.primitive_cube_add(size=2.0, location=(0, 0, 0))
    obj = bpy.context.object
    assert obj is not None and obj.type == "MESH", "Cubo di prova non creato"
    mesh = obj.data
    mat0 = bpy.data.materials.new(name="MatTextureSet0")
    mat1 = bpy.data.materials.new(name="MatTextureSet1")
    obj.data.materials.append(mat0)
    obj.data.materials.append(mat1)
    polygons = list(mesh.polygons)
    half = len(polygons) // 2
    for i, poly in enumerate(polygons):
        poly.material_index = 0 if i < half else 1
    for layer in list(mesh.uv_layers):
        mesh.uv_layers.remove(layer)
    _activate(obj)
    return obj


def _setup_uv(obj, settings):
    mesh = obj.data
    layer_name = str(getattr(settings, "uv_layer_name", "SmartUV") or "SmartUV")
    for layer in list(mesh.uv_layers):
        mesh.uv_layers.remove(layer)
    layer = mesh.uv_layers.new(name=layer_name)
    mesh.uv_layers.active = layer
    _activate(obj)
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.smart_project()
    bpy.ops.object.mode_set(mode="OBJECT")


def _island_areas(island_analysis):
    return {frozenset(rec["faces"]): float(rec["uv_area"]) for rec in island_analysis.islands}


def test_texture_sets():
    addon = importlib.import_module(PACKAGE)
    addon.register()
    objects = []
    try:
        settings = _settings()
        layer_name = str(getattr(settings, "uv_layer_name", "SmartUV") or "SmartUV")

        # --- island_material_groups: ogni isola assegnata, unione completa ---
        obj0 = _make_cube_two_materials()
        objects.append(obj0)
        _setup_uv(obj0, settings)

        material_analysis0 = module("material_analysis").MaterialAnalyzer.analyze(obj0)
        assert getattr(material_analysis0, "ok", False), (
            "analisi materiali fallita: {0}".format(
                "; ".join(getattr(material_analysis0, "errors", [])[:3]) or "nessun errore"))

        island_analysis0 = module("island_extraction").IslandExtractor.analyze(
            obj=obj0, settings=settings, material_analysis=material_analysis0,
        )
        assert getattr(island_analysis0, "ok", False), (
            "analisi isole fallita: {0}".format(
                "; ".join(getattr(island_analysis0, "errors", [])[:3]) or "nessun errore"))
        assert len(island_analysis0.islands) > 0, "nessuna isola UV prodotta"

        groups = module("texture_sets").island_material_groups(
            island_analysis0, material_analysis0,
        )
        island_ids = [rec["id"] for rec in island_analysis0.islands]
        assert isinstance(groups, dict), "island_material_groups non ha restituito un dict"
        for island_id in island_ids:
            assert island_id in groups, (
                "isola {0} non assegnata a nessun gruppo".format(island_id))

        by_group = {}
        for island_id, group in groups.items():
            by_group.setdefault(group, []).append(island_id)
        union = set()
        for group, ids in by_group.items():
            assert not (union & set(ids)), (
                "isola duplicata tra gruppi diversi: {0}".format(union & set(ids)))
            union |= set(ids)
        assert union == set(island_ids), (
            "l'unione dei gruppi non copre tutte le isole: {0} vs {1}".format(
                sorted(union), sorted(island_ids)))

        # --- pack_per_material: nessuna isola persa, coordinate finite in [0,1] ---
        total_after_preserve_true = None
        for preserve in (True, False):
            obj = _make_cube_two_materials()
            objects.append(obj)
            _setup_uv(obj, settings)

            material_analysis = module("material_analysis").MaterialAnalyzer.analyze(obj)
            assert getattr(material_analysis, "ok", False), (
                "analisi materiali fallita: {0}".format(
                    "; ".join(getattr(material_analysis, "errors", [])[:3]) or "nessun errore"))

            island_before = module("island_extraction").IslandExtractor.analyze(
                obj=obj, settings=settings, material_analysis=material_analysis,
            )
            assert getattr(island_before, "ok", False), (
                "analisi isole prima del pack fallita: {0}".format(
                    "; ".join(getattr(island_before, "errors", [])[:3]) or "nessun errore"))
            areas_before = _island_areas(island_before)

            result = module("texture_sets").pack_per_material(
                obj, 0.01, layer_name, preserve_scale=preserve, report=None,
            )
            assert result is not None, "pack_per_material non ha restituito un risultato"

            _name, layer = _uv_layer(obj)
            coords = _uv_coords(layer)
            assert coords, "layer '{0}' senza loop UV dopo il pack".format(_name)
            for u, v in coords:
                assert math.isfinite(u) and math.isfinite(v), (
                    "coordinata non finita dopo il pack: ({0}, {1})".format(u, v))
                assert -UV_TOL <= u <= 1.0 + UV_TOL and -UV_TOL <= v <= 1.0 + UV_TOL, (
                    "coordinata fuori da [0,1] dopo il pack: ({0}, {1})".format(u, v))

            island_after = module("island_extraction").IslandExtractor.analyze(
                obj=obj, settings=settings, material_analysis=material_analysis,
            )
            assert getattr(island_after, "ok", False), (
                "analisi isole dopo il pack fallita: {0}".format(
                    "; ".join(getattr(island_after, "errors", [])[:3]) or "nessun errore"))
            assert len(island_after.islands) == len(island_before.islands), (
                "isole perse dal pack: {0} vs {1}".format(
                    len(island_after.islands), len(island_before.islands)))
            areas_after = _island_areas(island_after)
            assert set(areas_after.keys()) == set(areas_before.keys()), (
                "insieme delle isole cambiato dal pack")

            ratios = [
                areas_after[key] / areas_before[key]
                for key in areas_before
                if areas_before[key] > 0.0 and key in areas_after
            ]
            assert ratios, "nessun rapporto area calcolabile per il pack"

            if preserve:
                assert max(ratios) - min(ratios) <= 1e-3, (
                    "con preserve_scale=True i rapporti aree_after/aree_before "
                    "non sono uniformi: min={0} max={1}".format(min(ratios), max(ratios)))
                factor = sum(ratios) / len(ratios)
                assert factor <= 1.0 + 1e-9, (
                    "con preserve_scale=True il fattore di scala deve essere <= 1: {0}".format(factor))
                total_after_preserve_true = sum(areas_after.values())
            else:
                total_before = sum(areas_before.values())
                total_after = sum(areas_after.values())
                assert (
                    abs(total_after - total_before) > 1e-6
                    or (total_after_preserve_true is not None
                        and abs(total_after - total_after_preserve_true) > 1e-6)
                ), (
                    "con preserve_scale=False il pack non ha cambiato il layout: "
                    "total_before={0} total_after={1} total_preserve_true={2}".format(
                        total_before, total_after, total_after_preserve_true))

        return (
            "isole={0}, gruppi={1}, pack verificato per preserve_scale True/False".format(
                len(island_ids), len(by_group))
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
    tests = (test_texture_sets,)
    for test in tests:
        try:
            detail = test()
            passed += 1
            print("CHECK {0} PASS {1}".format(test.__name__, detail or ""))
        except Exception:
            failed += 1
            traceback.print_exc()
    print("RISULTATO passati={0} falliti={1} totale={2}".format(passed, failed, len(tests)))