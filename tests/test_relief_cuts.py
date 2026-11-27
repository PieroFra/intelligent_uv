# -*- coding: utf-8 -*-
"""Test relief cuts guidati dalla distorsione sulla pipeline nativa (Suzanne)."""

import importlib
import math
import os
import sys
import traceback
from types import SimpleNamespace

import bpy

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(ROOT))
PACKAGE = os.path.basename(ROOT)

RESULTS = []


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


def _remove(obj):
    try:
        if obj is not None:
            bpy.data.objects.remove(obj, do_unlink=True)
    except Exception:
        pass
    try:
        mesh = getattr(obj, "data", None)
        if mesh is not None and getattr(mesh, "users", 1) == 0:
            bpy.data.meshes.remove(mesh)
    except Exception:
        pass


def _suzanne():
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    bpy.ops.mesh.primitive_monkey_add(size=2.0, location=(0.0, 0.0, 0.0))
    obj = bpy.context.object
    assert obj is not None and obj.type == "MESH", "Suzanne di prova non creata"
    return obj


def _run_native_pipeline(obj, settings):
    """Esegue la pipeline nativa completa su obj e restituisce (runner, state)."""
    for other in bpy.context.view_layer.objects:
        other.select_set(False)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj

    mesh_analysis = module("mesh_analysis").MeshAnalyzer.analyze(obj.data)
    assert getattr(mesh_analysis, "ok", False), "Analisi mesh fallita"
    material_analysis = module("material_analysis").MaterialAnalyzer.analyze(obj)
    assert getattr(material_analysis, "ok", False), "Analisi materiali fallita"
    seam_plan = module("seam_planning").SeamPlanner.plan(
        mesh_analysis, material_analysis, settings
    )
    assert getattr(seam_plan, "ok", False), "Piano seam fallito"

    runner = NativeRunner()
    state = {
        "obj": obj,
        "settings": settings,
        "seam_plan": seam_plan,
        "mesh_analysis": mesh_analysis,
        "material_analysis": material_analysis,
        "margin_result": SimpleNamespace(
            margin_uv=0.01, margin_px=10.24, texture_resolution=1024
        ),
    }
    assert runner._run_native(bpy.context, state), "Pipeline nativa fallita"
    assert not runner.failures, "La pipeline ha registrato errori"
    return runner, state


def _measure(obj, state):
    """Distorsione angolare media e overlap reali dopo la pipeline."""
    settings = state["settings"]
    name = str(getattr(settings, "uv_layer_name", "SmartUV") or "SmartUV")
    layer = obj.data.uv_layers.get(name)
    assert layer is not None, "Layer UV richiesto assente"
    coords = [tuple(item.uv) for item in layer.data]
    assert len(coords) == len(obj.data.loops) and coords, "Loop UV mancanti"
    assert all(math.isfinite(v) for uv in coords for v in uv), "UV non finite"

    mesh_analysis = module("mesh_analysis").MeshAnalyzer.analyze(obj.data)
    assert getattr(mesh_analysis, "ok", False), "Analisi mesh di misura fallita"
    analyzer = module("distortion").DistortionAnalyzer
    distortion = analyzer.analyze(obj.data, layer, mesh_analysis)
    assert getattr(distortion, "ok", False), "Analisi distorsione fallita"

    islands = state.get("island_analysis")
    if islands is None or not getattr(islands, "ok", False):
        islands = runner_analyze(obj, settings, mesh_analysis)
    pairs, checked, gave_up = analyzer.find_real_overlaps(
        obj.data, layer, islands
    )
    return {
        "angle_error_mean": float(distortion.angle_error_mean),
        "angle_error_max": float(distortion.angle_error_max),
        "overlaps": len(pairs),
        "gave_up": int(gave_up),
        "seams": sum(1 for edge in obj.data.edges if edge.use_seam),
    }


def runner_analyze(obj, settings, mesh_analysis):
    return NativeRunner()._analyze_islands(
        {"obj": obj, "settings": settings, "mesh_analysis": mesh_analysis},
        native=False,
    )


def test_relief_cuts_reduce_mean_angular_distortion():
    obj_on = None
    obj_off = None
    settings = bpy.context.scene.intelligent_uv_settings
    # Isola il contributo dei relief cuts: straightening e recovery spenti.
    saved = (
        bool(settings.distortion_relief_cuts),
        bool(settings.straighten_quad_strips),
    )
    try:
        settings.straighten_quad_strips = False

        settings.distortion_relief_cuts = True
        obj_on = _suzanne()
        runner_on, state_on = _run_native_pipeline(obj_on, settings)
        metrics_on = _measure(obj_on, state_on)

        settings.distortion_relief_cuts = False
        obj_off = _suzanne()
        runner_off, state_off = _run_native_pipeline(obj_off, settings)
        metrics_off = _measure(obj_off, state_off)

        assert any(
            "Relief cuts" in record.get("message", "")
            for record in runner_on.messages
        ), (
            "Relief cuts attivi ma nessun messaggio 'Relief cuts' nel report: %s"
            % repr(runner_on.messages)
        )
        assert not any(
            "Relief cuts" in record.get("message", "")
            for record in runner_off.messages
        ), (
            "Relief cuts disattivati ma il report ne parla: %s"
            % repr(runner_off.messages)
        )

        assert metrics_on["overlaps"] == 0, (
            "Relief cuts attivi: overlap reali rilevati (%s)"
            % repr(metrics_on)
        )
        assert metrics_on["gave_up"] == 0, (
            "Controllo overlap incompleto con relief cuts attivi (%s)"
            % repr(metrics_on)
        )
        assert metrics_off["overlaps"] == 0, (
            "Relief cuts disattivati: overlap reali rilevati (%s)"
            % repr(metrics_off)
        )

        assert metrics_on["seams"] >= metrics_off["seams"], (
            "Relief cuts attivi ma meno seam del run senza (%s vs %s)"
            % (metrics_on["seams"], metrics_off["seams"])
        )
        assert metrics_on["angle_error_mean"] < metrics_off["angle_error_mean"], (
            "Relief cuts attivi non riducono la distorsione angolare media: "
            "ON=%s OFF=%s"
            % (metrics_on, metrics_off)
        )
    finally:
        try:
            settings.distortion_relief_cuts = saved[0]
            settings.straighten_quad_strips = saved[1]
        except Exception:
            pass
        _remove(obj_on)
        _remove(obj_off)


def main():
    addon = importlib.import_module(PACKAGE)
    addon.register()
    try:
        test_relief_cuts_reduce_mean_angular_distortion()
        RESULTS.append({"test": "test_relief_cuts_reduce_mean_angular_distortion",
                        "passed": True})
    except Exception:
        tb = traceback.format_exc()
        RESULTS.append({"test": "test_relief_cuts_reduce_mean_angular_distortion",
                        "passed": False, "error": tb})
        print("".join(tb.strip().splitlines(keepends=True)[-10:]))
    finally:
        addon.unregister()
    passed = sum(result["passed"] for result in RESULTS)
    print(f"RISULTATO passati={passed} falliti={len(RESULTS) - passed} "
          f"totale={len(RESULTS)}")


main()
