# -*- coding: utf-8 -*-
"""Baseline headless native-only su copie di primitive deterministiche."""

import importlib
import json
import math
import os
import sys
import time
import traceback
from types import SimpleNamespace

import bpy

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(ROOT))
PACKAGE = os.path.basename(ROOT)
OUTPUT = os.path.join(os.path.abspath(os.environ["TEMP"]),
                      "intelligent_uv_native_baseline.json")
RESULTS = []
MEASUREMENTS = {}


def module(name):
    return importlib.import_module(PACKAGE + "." + name)


class NativeRunner(module("operators.native").NativePipelineMixin):
    """Usa la pipeline reale senza dispatch verso RizomUV."""

    def __init__(self):
        self.messages = []
        self.failures = []

    def _report(self, level, message):
        self.messages.append({"level": level, "message": message})

    def _mark_failed(self, name, message):
        self.failures.append({"object": name, "message": message})


def snapshot(obj):
    mesh = obj.data
    return {
        "matrix": tuple(tuple(row) for row in obj.matrix_world),
        "vertices": tuple(tuple(v.co) for v in mesh.vertices),
        "edges": tuple((tuple(e.vertices), e.use_seam) for e in mesh.edges),
        "faces": tuple((tuple(p.vertices), p.material_index) for p in mesh.polygons),
        "uv": tuple((layer.name, tuple(tuple(item.uv) for item in layer.data))
                    for layer in mesh.uv_layers),
        "active_uv": mesh.uv_layers.active_index,
        "materials": tuple(mesh.materials),
    }


def baseline(kind):
    if kind == "cube":
        bpy.ops.mesh.primitive_cube_add(size=2.0, location=(0, 0, 0))
    elif kind == "cylinder":
        bpy.ops.mesh.primitive_cylinder_add(vertices=32, radius=1.0, depth=2.0,
                                            end_fill_type='NOTHING', location=(0, 0, 0))
    else:
        bpy.ops.mesh.primitive_uv_sphere_add(segments=32, ring_count=16,
                                             radius=1.0, location=(0, 0, 0))
    source = bpy.context.object
    original_mesh = source.data
    before = snapshot(source)
    copy = source.copy()
    copy.data = source.data.copy()
    bpy.context.scene.collection.objects.link(copy)
    smart_copy = source.copy()
    smart_copy.data = source.data.copy()
    bpy.context.scene.collection.objects.link(smart_copy)
    unwrap_copies = {}
    for method in ('ANGLE_BASED', 'CONFORMAL'):
        obj = source.copy()
        obj.data = source.data.copy()
        bpy.context.scene.collection.objects.link(obj)
        unwrap_copies[method] = obj
    runner = NativeRunner()
    parameters = {"texture_resolution": 1024, "margin_uv": 0.01,
                  "margin_px": 10.24, "matrix_world": before["matrix"],
                  "timing_scope": "method pipeline excluding measurement and copying"}
    row = {"messages": runner.messages, "failures": runner.failures,
           "parameters": dict(parameters),
           "overlap_control": "incomplete; checked=0 does not prove absence of overlap"}
    MEASUREMENTS[kind] = {"native": row, "smart_uv": {}}
    row["steps"] = ["native seam planning", "full native pipeline including postprocessing"]
    row["comparison_limit"] = "Full pipeline, not an isolated planner or unwrap measurement"
    row["parameters"]["timing_scope"] = (
        "mesh/material analysis, seam planning and marking plus native processing; "
        "excludes comparison pipelines, copying, context setup and external measurements")
    row["timing_history"] = (
        "Previous native elapsed times included both unwrap comparisons and their "
        "measurements; contaminated timing, not evidence of a native regression")
    try:
        assert copy.data is not source.data, "La copia condivide la mesh sorgente"
        for obj in bpy.context.view_layer.objects:
            obj.select_set(False)
        copy.select_set(True)
        bpy.context.view_layer.objects.active = copy
        settings = bpy.context.scene.intelligent_uv_settings
        started = time.perf_counter()
        mesh_analysis = module("mesh_analysis").MeshAnalyzer.analyze(copy.data)
        assert mesh_analysis.ok, "Analisi mesh fallita"
        material_analysis = module("material_analysis").MaterialAnalyzer.analyze(copy)
        assert material_analysis.ok, "Analisi materiali fallita"
        plan = module("seam_planning").SeamPlanner.plan(
            mesh_analysis, material_analysis, settings)
        assert plan.ok, "Piano seam fallito"
        success, message = module("seam_marking").SeamMarker.mark_real_seams(
            copy.data, plan.is_seam)
        assert success, "Marcatura seam fallita: " + message
        row["seam_planning_seconds"] = time.perf_counter() - started
        planned_seams = tuple(edge.use_seam for edge in copy.data.edges)
        for method, obj in unwrap_copies.items():
            method_row = {}
            MEASUREMENTS[kind][method.lower()] = method_row
            unwrap_baseline(obj, source, original_mesh, before, settings,
                            method_row, parameters, method, planned_seams)
        for obj in bpy.context.view_layer.objects:
            obj.select_set(False)
        copy.select_set(True)
        bpy.context.view_layer.objects.active = copy
        state = {"obj": copy, "settings": settings, "seam_plan": plan,
                 "mesh_analysis": mesh_analysis, "material_analysis": material_analysis,
                 "margin_result": SimpleNamespace(margin_uv=0.01, margin_px=10.24,
                                                   texture_resolution=1024)}
        started = time.perf_counter()
        try:
            assert runner._run_native(bpy.context, state), "Pipeline nativa fallita"
        finally:
            row["native_processing_seconds"] = time.perf_counter() - started
            row["elapsed_seconds"] = (
                row["seam_planning_seconds"] + row["native_processing_seconds"])
        assert not runner.failures, "La pipeline ha registrato errori"
        name = str(getattr(settings, "uv_layer_name", "SmartUV") or "SmartUV")
        layer = copy.data.uv_layers.get(name)
        assert layer is not None, "Layer UV richiesto assente"
        coords = [tuple(item.uv) for item in layer.data]
        assert len(coords) == len(copy.data.loops) and coords, "Loop UV mancanti"
        assert all(math.isfinite(v) for uv in coords for v in uv), "UV non finite"
        assert source.data is original_mesh, "Mesh sorgente sostituita"
        assert snapshot(source) == before, "Sorgente modificato dalla pipeline"
        row.update({"uv_layer": name, "uv_loops": len(coords),
                    "vertices": len(copy.data.vertices), "faces": len(copy.data.polygons),
                    "seams": len(plan.seam_edges), "margin_uv": 0.01})
        analyzer = module("distortion").DistortionAnalyzer
        try:
            distortion = analyzer.analyze(copy.data, layer, mesh_analysis)
            row["distortion"] = {key: getattr(distortion, key) for key in (
                "ok", "density_min", "density_max", "density_mean", "density_deviation",
                "angle_error_mean", "angle_error_max", "faces_measured")}
            islands = state.get("island_analysis")
            if islands is not None and islands.ok:
                row["fill"] = analyzer.measure_fill(copy.data, layer, islands)
                row["per_island"] = analyzer.per_island_report(
                    copy.data, layer, mesh_analysis, islands)
                overlaps, checked, gave_up = analyzer.find_real_overlaps(
                    copy.data, layer, islands)
                row["overlaps"] = {"pairs": overlaps, "checked": checked,
                                   "gave_up": gave_up}
        except Exception as exc:
            row["measurement_error"] = str(exc)
        smart_uv_baseline(smart_copy, source, original_mesh, before,
                          settings, MEASUREMENTS[kind]["smart_uv"], parameters)
    finally:
        if bpy.context.object and bpy.context.object.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        for obj in (*unwrap_copies.values(), smart_copy, copy, source):
            mesh = obj.data
            bpy.data.objects.remove(obj, do_unlink=True)
            if mesh.users == 0:
                bpy.data.meshes.remove(mesh)


def smart_uv_baseline(obj, source, original_mesh, before, settings, row, parameters):
    """Confronta Smart UV Project e Pack Islands su una copia indipendente."""
    row.update({"parameters": dict(parameters),
                "overlap_control": "incomplete; checked=0 does not prove absence of overlap"})
    row["parameters"].update({"angle_limit": math.radians(66.0),
                              "area_weight": 0.0, "correct_aspect": True,
                              "scale_to_bounds": False, "project_margin": 0.0,
                              "pack_rotate": True, "pack_scale": True,
                              "pack_margin_method": "FRACTION"})
    assert obj.data is not source.data, "La copia Smart UV condivide la mesh sorgente"
    assert snapshot(obj) == before, "La copia Smart UV non parte dalla stessa fixture"
    for item in bpy.context.view_layer.objects:
        item.select_set(False)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    name = str(getattr(settings, "uv_layer_name", "SmartUV") or "SmartUV")
    layer = obj.data.uv_layers.get(name) or obj.data.uv_layers.new(name=name)
    obj.data.uv_layers.active = layer
    started = time.perf_counter()
    try:
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_all(action='SELECT')
        assert bpy.ops.uv.smart_project(
            angle_limit=math.radians(66.0), island_margin=0.0, area_weight=0.0,
            correct_aspect=True, scale_to_bounds=False) == {'FINISHED'}, "Smart UV Project fallito"
        assert bpy.ops.uv.pack_islands(
            rotate=True, scale=True, margin_method='FRACTION',
            margin=parameters["margin_uv"]) == {'FINISHED'}, "Pack Islands fallito"
    finally:
        if obj.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        row["elapsed_seconds"] = time.perf_counter() - started
    layer = obj.data.uv_layers.get(name)
    assert layer is not None, "Layer UV Smart UV richiesto assente"
    coords = [tuple(item.uv) for item in layer.data]
    assert len(coords) == len(obj.data.loops) and coords, "Loop Smart UV mancanti"
    assert all(math.isfinite(v) for uv in coords for v in uv), "Smart UV non finite"
    assert source.data is original_mesh, "Mesh sorgente sostituita da Smart UV"
    assert snapshot(source) == before, "Sorgente modificato da Smart UV"
    row.update({"uv_layer": name, "uv_loops": len(coords),
                "vertices": len(obj.data.vertices), "faces": len(obj.data.polygons),
                "seams": sum(edge.use_seam for edge in obj.data.edges), "margin_uv": 0.01})
    try:
        mesh_analysis = module("mesh_analysis").MeshAnalyzer.analyze(obj.data)
        assert mesh_analysis.ok, "Analisi mesh Smart UV fallita"
        analyzer = module("distortion").DistortionAnalyzer
        distortion = analyzer.analyze(obj.data, layer, mesh_analysis)
        row["distortion"] = {key: getattr(distortion, key) for key in (
            "ok", "density_min", "density_max", "density_mean", "density_deviation",
            "angle_error_mean", "angle_error_max", "faces_measured")}
        islands = NativeRunner()._analyze_islands(
            {"obj": obj, "settings": settings, "mesh_analysis": mesh_analysis}, native=False)
        if islands is not None and islands.ok:
            row["fill"] = analyzer.measure_fill(obj.data, layer, islands)
            row["per_island"] = analyzer.per_island_report(obj.data, layer, mesh_analysis, islands)
            overlaps, checked, gave_up = analyzer.find_real_overlaps(obj.data, layer, islands)
            row["overlaps"] = {"pairs": overlaps, "checked": checked, "gave_up": gave_up}
        else:
            row["measurement_error"] = "Analisi isole Smart UV incompleta"
    except Exception as exc:
        row["measurement_error"] = str(exc)


def unwrap_metrics(obj, settings, name):
    """Misura gli stessi indicatori senza modificare UV o seam."""
    layer = obj.data.uv_layers.get(name)
    assert layer is not None, "Layer UV unwrap assente"
    coords = [tuple(item.uv) for item in layer.data]
    assert len(coords) == len(obj.data.loops) and coords, "Loop unwrap mancanti"
    assert all(math.isfinite(v) for uv in coords for v in uv), "Unwrap non finite"
    result = {"uv_layer": name, "uv_loops": len(coords),
              "vertices": len(obj.data.vertices), "faces": len(obj.data.polygons),
              "seams": sum(edge.use_seam for edge in obj.data.edges), "margin_uv": 0.01}
    try:
        analysis = module("mesh_analysis").MeshAnalyzer.analyze(obj.data)
        assert analysis.ok, "Analisi mesh unwrap fallita"
        analyzer = module("distortion").DistortionAnalyzer
        distortion = analyzer.analyze(obj.data, layer, analysis)
        result["distortion"] = {key: getattr(distortion, key) for key in (
            "ok", "density_min", "density_max", "density_mean", "density_deviation",
            "angle_error_mean", "angle_error_max", "faces_measured")}
        islands = NativeRunner()._analyze_islands(
            {"obj": obj, "settings": settings, "mesh_analysis": analysis}, native=False)
        if islands is not None and islands.ok:
            result["fill"] = analyzer.measure_fill(obj.data, layer, islands)
            result["per_island"] = analyzer.per_island_report(obj.data, layer, analysis, islands)
            overlaps, checked, gave_up = analyzer.find_real_overlaps(obj.data, layer, islands)
            result["overlaps"] = {"pairs": overlaps, "checked": checked, "gave_up": gave_up}
        else:
            result["measurement_error"] = "Analisi isole unwrap incompleta"
    except Exception as exc:
        result["measurement_error"] = str(exc)
    return result


def unwrap_baseline(obj, source, original_mesh, before, settings, row,
                    parameters, method, planned_seams):
    """Confronta unwrap puro e pack Blender sulle seam native pre-pipeline."""
    assert obj.data is not source.data, "La copia unwrap condivide la mesh sorgente"
    assert snapshot(obj) == before, "La copia unwrap non parte dalla stessa fixture"
    assert len(obj.data.edges) == len(planned_seams), "Topologia seam incompatibile"
    for edge, seam in zip(obj.data.edges, planned_seams):
        edge.use_seam = seam
    assert tuple(edge.use_seam for edge in obj.data.edges) == planned_seams, "Seam non copiate"
    row.update({"parameters": dict(parameters),
                "seam_source": "native planner, explicitly copied before native pipeline",
                "seam_edge_indices": [i for i, seam in enumerate(planned_seams) if seam],
                "steps": ["Blender unwrap only", "Blender Pack Islands only"],
                "native_postprocessing": False,
                "overlap_control": "incomplete; checked=0 does not prove absence of overlap"})
    row["parameters"].update({"method": method, "fill_holes": True,
                              "correct_aspect": True, "use_subsurf_data": False,
                              "unwrap_margin": 0.0, "pack_rotate": True,
                              "pack_scale": True, "pack_margin_method": "FRACTION",
                               "timing_scope": "unwrap and pack operator calls separately; total is their sum; excludes mode changes, selection, copying and measurements; measurements timed separately"})
    for item in bpy.context.view_layer.objects:
        item.select_set(False)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    name = str(getattr(settings, "uv_layer_name", "SmartUV") or "SmartUV")
    layer = obj.data.uv_layers.get(name) or obj.data.uv_layers.new(name=name)
    obj.data.uv_layers.active = layer
    for stage in ("unwrap_only", "packed"):
        try:
            bpy.ops.object.mode_set(mode='EDIT')
            bpy.ops.mesh.select_all(action='SELECT')
            started = time.perf_counter()
            try:
                if stage == "unwrap_only":
                    assert bpy.ops.uv.unwrap(
                        method=method, fill_holes=True, correct_aspect=True,
                        use_subsurf_data=False, margin=0.0) == {'FINISHED'}, "Unwrap Blender fallito"
                else:
                    assert bpy.ops.uv.pack_islands(
                        rotate=True, scale=True, margin_method='FRACTION',
                        margin=parameters["margin_uv"]) == {'FINISHED'}, "Pack unwrap fallito"
            finally:
                row[stage + "_seconds"] = time.perf_counter() - started
        finally:
            if obj.mode != 'OBJECT':
                bpy.ops.object.mode_set(mode='OBJECT')
        started = time.perf_counter()
        try:
            row[stage] = unwrap_metrics(obj, settings, name)
        finally:
            row[stage + "_measurement_seconds"] = time.perf_counter() - started
    row.update(row["packed"])
    row["elapsed_seconds"] = row["unwrap_only_seconds"] + row["packed_seconds"]
    assert tuple(edge.use_seam for edge in obj.data.edges) == planned_seams, "Seam modificate dall'unwrap"
    assert source.data is original_mesh, "Mesh sorgente sostituita dall'unwrap"
    assert snapshot(source) == before, "Sorgente modificato dall'unwrap"


def test_cube():
    baseline("cube")


def test_cylinder():
    baseline("cylinder")


def test_sphere():
    baseline("sphere")


def json_safe(value):
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [json_safe(v) for v in value]
    return value


if __name__ == "__main__":
    addon = importlib.import_module(PACKAGE)
    addon.register()
    try:
        for test in (test_cube, test_cylinder, test_sphere):
            try:
                test()
                RESULTS.append({"test": test.__name__, "passed": True})
            except Exception:
                RESULTS.append({"test": test.__name__, "passed": False,
                                "error": traceback.format_exc()})
        with open(OUTPUT, "w", encoding="utf-8") as handle:
            json.dump(json_safe({"blender": bpy.app.version_string, "native_only": False,
                                  "methods": ["native", "smart_uv", "angle_based", "conformal"],
                                 "results": RESULTS, "measurements": MEASUREMENTS}),
                      handle, ensure_ascii=False, indent=2, allow_nan=False)
    finally:
        addon.unregister()
    passed = sum(result["passed"] for result in RESULTS)
    print("JSON: " + OUTPUT)
    print(f"RISULTATO passati={passed} falliti={len(RESULTS) - passed} totale={len(RESULTS)}")
