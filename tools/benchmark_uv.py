# -*- coding: utf-8 -*-
"""
Reproducible UV Benchmark (B1/B2) for Intelligent UV (Blender-only Native pipeline).

Run headless via Blender:
    blender --background --factory-startup --python tools/benchmark_uv.py

Compares Intelligent UV Native against Blender Smart UV Project across
deterministic meshes (Cube, Cylinder, UV Sphere, Torus, Suzanne), reporting:
  - island count
  - UV coverage (%)
  - texel density spread (%)
  - mean / max angular distortion (deg)
  - overlapping island pairs
  - runtime (ms)
"""

import importlib
import json
import os
import sys
import tempfile
import time

import bpy

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(ROOT))
PACKAGE = os.path.basename(ROOT)


def _mod(name):
    return importlib.import_module(PACKAGE + "." + name)


def _make_mesh(kind):
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
    if kind == "cube":
        bpy.ops.mesh.primitive_cube_add(size=2.0)
    elif kind == "cylinder":
        bpy.ops.mesh.primitive_cylinder_add(vertices=32, radius=1.0, depth=2.0)
    elif kind == "uv_sphere":
        bpy.ops.mesh.primitive_uv_sphere_add(segments=32, ring_count=16, radius=1.0)
    elif kind == "torus":
        bpy.ops.mesh.primitive_torus_add(major_segments=32, minor_segments=16)
    elif kind == "suzanne":
        bpy.ops.mesh.primitive_monkey_add(size=2.0)
    else:
        raise ValueError(f"Unknown mesh kind: {kind}")
    return bpy.context.active_object


def _measure(obj, uv_name):
    mesh_analysis = _mod("mesh_analysis").MeshAnalyzer.analyze(obj.data)
    uv_layer = obj.data.uv_layers.get(uv_name) or (
        obj.data.uv_layers[0] if len(obj.data.uv_layers) else None
    )
    island_res = _mod("island_extraction").IslandExtractor.analyze(
        obj, uv_name, mesh_analysis
    )
    dist_res = _mod("distortion").DistortionAnalyzer.analyze(
        obj.data, uv_layer, mesh_analysis
    )
    overlap_res = _mod("distortion").DistortionAnalyzer.check_overlaps(
        obj.data, uv_layer, island_res
    ) if hasattr(_mod("distortion").DistortionAnalyzer, "check_overlaps") else None

    total_uv_area = float(getattr(island_res, "total_uv_area", 0.0) or 0.0)
    overlaps = 0
    if overlap_res is not None:
        overlaps = len(getattr(overlap_res, "overlaps", []) or [])
    else:
        overlaps = getattr(dist_res, "overlapping_pairs", 0)

    return {
        "faces": len(obj.data.polygons),
        "islands": len(getattr(island_res, "islands", [])),
        "coverage_pct": round(total_uv_area * 100.0, 2),
        "td_spread_pct": round(getattr(dist_res, "density_deviation", 0.0) * 100.0, 2),
        "angle_mean_deg": round(getattr(dist_res, "angle_error_mean", 0.0), 2),
        "angle_max_deg": round(getattr(dist_res, "angle_error_max", 0.0), 2),
        "overlaps": overlaps,
    }


def _run_native(obj):
    settings = bpy.context.scene.intelligent_uv_settings
    settings.use_rizomuv = False
    uv_name = str(getattr(settings, "uv_layer_name", "SmartUV") or "SmartUV")

    class _Runner(_mod("operators.native").NativePipelineMixin):
        def __init__(self):
            self.messages = []
            self.failures = []

        def _report(self, level, msg):
            self.messages.append((level, msg))

        def _mark_failed(self, name, msg):
            self.failures.append((name, msg))

    t0 = time.perf_counter()
    ma = _mod("mesh_analysis").MeshAnalyzer.analyze(obj.data)
    mata = _mod("material_analysis").MaterialAnalyzer.analyze(obj)
    margin = _mod("margins").MarginCalculator.calculate(settings)
    plan = _mod("seam_planning").SeamPlanner.plan(ma, mata, settings)
    _mod("seam_marking").SeamMarker.mark_real_seams(obj.data, plan.is_seam)
    runner = _Runner()
    state = {
        "obj": obj,
        "settings": settings,
        "mesh_analysis": ma,
        "material_analysis": mata,
        "seam_plan": plan,
        "margin_result": margin,
    }
    ok = runner._run_native(bpy.context, state, skip_unwrap=False)
    elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 1)
    m = _measure(obj, uv_name)
    m["ok"] = bool(ok)
    m["time_ms"] = elapsed_ms
    return m


def _run_smart_uv(obj):
    uv_name = "SmartUV"
    if uv_name not in obj.data.uv_layers:
        obj.data.uv_layers.new(name=uv_name)
    obj.data.uv_layers.active = obj.data.uv_layers[uv_name]
    t0 = time.perf_counter()
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.uv.smart_project(angle_limit=1.1519, island_margin=0.01)
    bpy.ops.object.mode_set(mode='OBJECT')
    elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 1)
    m = _measure(obj, uv_name)
    m["ok"] = True
    m["time_ms"] = elapsed_ms
    return m


def main():
    addon = importlib.import_module(PACKAGE)
    addon.register()
    meshes = ["cube", "cylinder", "uv_sphere", "torus", "suzanne"]
    report = {}

    print("\n| Mesh | Engine | Islands | Coverage % | TD Spread % | Angle Mean | Angle Max | Overlaps | Time (ms) |")
    print("|---|---|---:|---:|---:|---:|---:|---:|---:|")
    for kind in meshes:
        obj_nat = _make_mesh(kind)
        res_nat = _run_native(obj_nat)
        obj_smt = _make_mesh(kind)
        res_smt = _run_smart_uv(obj_smt)
        report[kind] = {"native": res_nat, "smart_uv": res_smt}
        for label, r in (("IUV Native", res_nat), ("Smart UV", res_smt)):
            print(
                f"| {kind} | {label} | {r['islands']} | {r['coverage_pct']:.1f}% | "
                f"{r['td_spread_pct']:.1f}% | {r['angle_mean_deg']:.2f}° | "
                f"{r['angle_max_deg']:.2f}° | {r['overlaps']} | {r['time_ms']:.1f} |"
            )

    out_path = os.path.join(tempfile.gettempdir(), "intelligent_uv_benchmark.json")
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2)
    print(f"\nBENCHMARK_OK | json={out_path}")


if __name__ == "__main__":
    main()
