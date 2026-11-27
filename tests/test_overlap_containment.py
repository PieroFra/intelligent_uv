# -*- coding: utf-8 -*-
"""Regression suite B3: UV island overlap detection including nested containment.

Verifies `DistortionAnalyzer.find_real_overlaps`, `_island_boundary_segments_bulk`,
`_segment_sets_cross`, and `_point_in_boundary` on deterministic Blender meshes:
  1. Nested containment without crossing edges is detected (`find_real_overlaps`).
  2. Multi-face 2x2 outer island strips interior edges in bulk boundary extraction
     and still detects nested containment.
  3. Adjacent (edge-touching) and disjoint islands produce zero overlaps.
  4. Concave U-shaped outer island with an inner island in its open pocket
     generates a bbox candidate (`find_overlaps`) but clears containment
     (even ray-crossing parity -> 0 real overlaps).
  5. Properly crossing edges are detected.
  6. An island flush against the outer border (touching along a shared seam)
     is NOT flagged: the containment probe sits on the boundary and reads as
     outside, while a 0.01-gap island in the same spot stays contained.

Usage:
    blender --factory-startup --background --python tests/test_overlap_containment.py

Last line: RISULTATO passati=X falliti=Y totale=N
"""

import importlib
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PACKAGE = os.path.basename(ROOT)
sys.path.insert(0, os.path.dirname(ROOT))

import bmesh  # noqa: E402
import bpy  # noqa: E402


def _drop(obj):
    if obj is None:
        return
    mesh = getattr(obj, "data", None)
    try:
        if obj.name in bpy.data.objects:
            bpy.data.objects.remove(obj, do_unlink=True)
    except Exception:
        pass
    if mesh is not None:
        try:
            if mesh.users == 0 and mesh.name in bpy.data.meshes:
                bpy.data.meshes.remove(mesh)
        except Exception:
            pass


def _build_islands_mesh(name, island_quads, uv_name="SmartUV"):
    """Build a single Mesh object with disconnected 3D islands and exact UVs.

    Within each island, adjacent quads sharing UV corner coordinates share the
    same Blender vertices/edges so bulk boundary extraction strips interior edges.
    """
    mesh = bpy.data.meshes.new(name + "_mesh")
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)

    bm = bmesh.new()
    uv_layer = bm.loops.layers.uv.new(uv_name)

    for island_idx, quads in enumerate(island_quads):
        z = float(island_idx) * 0.5
        vert_cache = {}

        def get_vert(u, v):
            key = (round(float(u), 6), round(float(v), 6))
            vert = vert_cache.get(key)
            if vert is None:
                vert = bm.verts.new((float(u), float(v), z))
                vert_cache[key] = vert
            return vert

        for u0, v0, u1, v1 in quads:
            coords = ((u0, v0), (u1, v0), (u1, v1), (u0, v1))
            verts = [get_vert(u, v) for u, v in coords]
            face = bm.faces.new(verts)
            for loop, (u, v) in zip(face.loops, coords):
                loop[uv_layer].uv = (float(u), float(v))

    bm.normal_update()
    bm.to_mesh(mesh)
    bm.free()

    uv = mesh.uv_layers.get(uv_name)
    if uv is not None:
        mesh.uv_layers.active = uv
    mesh.update()
    return obj


def _extract_bulk_segments(distortion_cls, mesh, uv_layer, island_record):
    utils = importlib.import_module(PACKAGE + ".utils")
    loop_count = len(mesh.loops)
    face_count = len(mesh.polygons)
    uv_flat = utils.read_all_uvs(uv_layer, loop_count)
    ranges = utils.bulk_loop_ranges(mesh, face_count)
    loop_edge = utils.bulk_loop_attribute(mesh, "edge_index", loop_count)
    assert uv_flat is not None and ranges is not None and loop_edge is not None, (
        "Bulk mesh/UV arrays unavailable in Blender"
    )
    return distortion_cls._island_boundary_segments_bulk(
        island_record["faces"], ranges, loop_edge, uv_flat, loop_count
    )


def check_nested_containment_detected(mods):
    DistortionAnalyzer = mods["distortion"].DistortionAnalyzer
    IslandExtractor = mods["island_extraction"].IslandExtractor
    MinimalUVExecutor = mods["uv_executor"].MinimalUVExecutor

    obj = _build_islands_mesh(
        "b3_nested_containment",
        [
            [(0.1, 0.1, 0.9, 0.9)],  # outer (area 0.64 -> id=0)
            [(0.3, 0.3, 0.7, 0.7)],  # inner (area 0.16 -> id=1)
        ],
    )
    try:
        ia = IslandExtractor.analyze(obj)
        assert ia.ok and ia.island_count == 2, f"Expected 2 islands, got {ia.island_count}"
        uv_layer = MinimalUVExecutor.get_uv_layer(obj.data, "SmartUV")

        candidates = DistortionAnalyzer.find_overlaps(ia)
        assert candidates == [(0, 1)], f"Expected bbox candidate [(0, 1)], got {candidates}"

        seg_0 = _extract_bulk_segments(DistortionAnalyzer, obj.data, uv_layer, ia.islands[0])
        seg_1 = _extract_bulk_segments(DistortionAnalyzer, obj.data, uv_layer, ia.islands[1])
        assert DistortionAnalyzer._segment_sets_cross(seg_0, seg_1) is False, (
            "Nested non-touching quads must not report crossing segments"
        )

        result = DistortionAnalyzer.find_real_overlaps(obj.data, uv_layer, ia)
        assert result == ([(0, 1)], 1, False), f"Expected ([(0, 1)], 1, False), got {result}"
        return "nested containment detected without crossing edges"
    finally:
        _drop(obj)


def check_nested_multiface_interior_edges_stripped(mods):
    DistortionAnalyzer = mods["distortion"].DistortionAnalyzer
    IslandExtractor = mods["island_extraction"].IslandExtractor
    MinimalUVExecutor = mods["uv_executor"].MinimalUVExecutor

    outer_2x2 = [
        (0.1, 0.1, 0.5, 0.5),
        (0.5, 0.1, 0.9, 0.5),
        (0.1, 0.5, 0.5, 0.9),
        (0.5, 0.5, 0.9, 0.9),
    ]
    inner_quad = [(0.15, 0.15, 0.45, 0.45)]
    obj = _build_islands_mesh("b3_nested_multiface", [outer_2x2, inner_quad])
    try:
        ia = IslandExtractor.analyze(obj)
        assert ia.ok and ia.island_count == 2, f"Expected 2 islands, got {ia.island_count}"
        uv_layer = MinimalUVExecutor.get_uv_layer(obj.data, "SmartUV")

        seg_0 = _extract_bulk_segments(DistortionAnalyzer, obj.data, uv_layer, ia.islands[0])
        seg_1 = _extract_bulk_segments(DistortionAnalyzer, obj.data, uv_layer, ia.islands[1])
        assert len(seg_0) == 8, f"Expected 8 perimeter segments (4 interior stripped), got {len(seg_0)}"
        assert DistortionAnalyzer._segment_sets_cross(seg_0, seg_1) is False, (
            "Inner quad inside bottom-left cell must not cross outer perimeter"
        )

        result = DistortionAnalyzer.find_real_overlaps(obj.data, uv_layer, ia)
        assert result == ([(0, 1)], 1, False), f"Expected ([(0, 1)], 1, False), got {result}"
        return f"outer_segs={len(seg_0)} (interior stripped), overlap={result[0]}"
    finally:
        _drop(obj)


def check_adjacent_non_overlapping(mods):
    DistortionAnalyzer = mods["distortion"].DistortionAnalyzer
    IslandExtractor = mods["island_extraction"].IslandExtractor
    MinimalUVExecutor = mods["uv_executor"].MinimalUVExecutor

    obj = _build_islands_mesh(
        "b3_adjacent_disjoint",
        [
            [(0.1, 0.1, 0.4, 0.4)],
            [(0.4, 0.1, 0.7, 0.4)],   # touches u=0.4
            [(0.75, 0.1, 0.95, 0.4)],  # disjoint
        ],
    )
    try:
        ia = IslandExtractor.analyze(obj)
        assert ia.ok and ia.island_count == 3, f"Expected 3 islands, got {ia.island_count}"
        uv_layer = MinimalUVExecutor.get_uv_layer(obj.data, "SmartUV")

        result = DistortionAnalyzer.find_real_overlaps(obj.data, uv_layer, ia)
        assert result == ([], 0, False), f"Expected ([], 0, False), got {result}"
        return "3 adjacent/disjoint quads -> 0 overlaps"
    finally:
        _drop(obj)


def check_concave_u_pocket_outside_outline(mods):
    DistortionAnalyzer = mods["distortion"].DistortionAnalyzer
    IslandExtractor = mods["island_extraction"].IslandExtractor
    MinimalUVExecutor = mods["uv_executor"].MinimalUVExecutor

    # 5-quad U-shape inside [0.1, 0.9]^2 with open pocket [0.35, 0.65] x [0.35, 0.9]
    u_shape = [
        (0.1, 0.1, 0.35, 0.35),
        (0.35, 0.1, 0.65, 0.35),
        (0.65, 0.1, 0.9, 0.35),
        (0.1, 0.35, 0.35, 0.9),
        (0.65, 0.35, 0.9, 0.9),
    ]
    pocket_quad = [(0.4, 0.45, 0.6, 0.75)]
    obj = _build_islands_mesh("b3_concave_u_pocket", [u_shape, pocket_quad])
    try:
        ia = IslandExtractor.analyze(obj)
        assert ia.ok and ia.island_count == 2, f"Expected 2 islands, got {ia.island_count}"
        uv_layer = MinimalUVExecutor.get_uv_layer(obj.data, "SmartUV")

        candidates = DistortionAnalyzer.find_overlaps(ia)
        assert candidates == [(0, 1)], f"Expected bbox candidate [(0, 1)], got {candidates}"

        result = DistortionAnalyzer.find_real_overlaps(obj.data, uv_layer, ia)
        assert result == ([], 1, False), f"Expected ([], 1, False), got {result}"
        return "U-pocket candidate checked=1, real_overlaps=0 (even ray parity)"
    finally:
        _drop(obj)


def check_crossing_edges_detected(mods):
    DistortionAnalyzer = mods["distortion"].DistortionAnalyzer
    IslandExtractor = mods["island_extraction"].IslandExtractor
    MinimalUVExecutor = mods["uv_executor"].MinimalUVExecutor

    obj = _build_islands_mesh(
        "b3_crossing",
        [
            [(0.1, 0.1, 0.5, 0.5)],
            [(0.3, 0.3, 0.7, 0.7)],
        ],
    )
    try:
        ia = IslandExtractor.analyze(obj)
        assert ia.ok and ia.island_count == 2, f"Expected 2 islands, got {ia.island_count}"
        uv_layer = MinimalUVExecutor.get_uv_layer(obj.data, "SmartUV")

        result = DistortionAnalyzer.find_real_overlaps(obj.data, uv_layer, ia)
        assert result == ([(0, 1)], 1, False), f"Expected ([(0, 1)], 1, False), got {result}"
        return "crossing quads detected"
    finally:
        _drop(obj)


def check_touching_border_not_overlap(mods):
    DistortionAnalyzer = mods["distortion"].DistortionAnalyzer
    IslandExtractor = mods["island_extraction"].IslandExtractor
    MinimalUVExecutor = mods["uv_executor"].MinimalUVExecutor

    # Inner quad flush against the outer square's bottom border: its bbox is
    # contained in the outer's, its bottom edge coincides with the outer's
    # border, and its area lies outside the outer outline. Touching along a
    # shared seam is packing, not overlap.
    obj = _build_islands_mesh(
        "b3_touching_border",
        [
            [(0.1, 0.1, 0.7, 0.7)],
            [(0.2, 0.1, 0.5, 0.4)],  # bottom edge on the outer border (v=0.1)
        ],
    )
    try:
        ia = IslandExtractor.analyze(obj)
        assert ia.ok and ia.island_count == 2, f"Expected 2 islands, got {ia.island_count}"
        uv_layer = MinimalUVExecutor.get_uv_layer(obj.data, "SmartUV")

        candidates = DistortionAnalyzer.find_overlaps(ia)
        assert candidates == [(0, 1)], f"Expected bbox candidate [(0, 1)], got {candidates}"

        seg_0 = _extract_bulk_segments(DistortionAnalyzer, obj.data, uv_layer, ia.islands[0])
        probe = (0.2, 0.1)  # the containment probe: inner island's first outline vertex
        assert DistortionAnalyzer._point_on_boundary(probe, seg_0) is True, (
            "Probe on the shared border must be recognized as on-boundary"
        )
        assert DistortionAnalyzer._point_in_boundary(probe, seg_0) is False, (
            "On-boundary probe must read as outside (touching is not containment)"
        )
        assert DistortionAnalyzer._point_in_boundary((0.4, 0.4), seg_0) is True, (
            "Strictly interior point must still read as inside"
        )

        result = DistortionAnalyzer.find_real_overlaps(obj.data, uv_layer, ia)
        assert result == ([], 1, False), f"Expected ([], 1, False), got {result}"
        return "flush border quad cleared (probe on boundary -> outside), checked=1"
    finally:
        _drop(obj)


def check_near_boundary_containment_kept(mods):
    DistortionAnalyzer = mods["distortion"].DistortionAnalyzer
    IslandExtractor = mods["island_extraction"].IslandExtractor
    MinimalUVExecutor = mods["uv_executor"].MinimalUVExecutor

    # Same spot as the flush case but with a 0.01 gap: the inner quad sits
    # strictly inside the outer outline, so containment must stay detected.
    obj = _build_islands_mesh(
        "b3_near_boundary_containment",
        [
            [(0.1, 0.1, 0.7, 0.7)],
            [(0.2, 0.11, 0.5, 0.4)],
        ],
    )
    try:
        ia = IslandExtractor.analyze(obj)
        assert ia.ok and ia.island_count == 2, f"Expected 2 islands, got {ia.island_count}"
        uv_layer = MinimalUVExecutor.get_uv_layer(obj.data, "SmartUV")

        result = DistortionAnalyzer.find_real_overlaps(obj.data, uv_layer, ia)
        assert result == ([(0, 1)], 1, False), f"Expected ([(0, 1)], 1, False), got {result}"
        return "0.01-gap quad inside outer outline still contained"
    finally:
        _drop(obj)


def main():
    addon = importlib.import_module(PACKAGE)
    addon.register()
    results = []
    try:
        mods = {
            "distortion": importlib.import_module(PACKAGE + ".distortion"),
            "island_extraction": importlib.import_module(PACKAGE + ".island_extraction"),
            "uv_executor": importlib.import_module(PACKAGE + ".uv_executor"),
        }
        checks = [
            ("nested_containment_detected", check_nested_containment_detected),
            ("nested_multiface_interior_edges_stripped", check_nested_multiface_interior_edges_stripped),
            ("adjacent_non_overlapping", check_adjacent_non_overlapping),
            ("concave_u_pocket_outside_outline", check_concave_u_pocket_outside_outline),
            ("crossing_edges_detected", check_crossing_edges_detected),
            ("touching_border_not_overlap", check_touching_border_not_overlap),
            ("near_boundary_containment_kept", check_near_boundary_containment_kept),
        ]
        for name, fn in checks:
            try:
                detail = fn(mods)
                results.append((name, True, detail or ""))
            except Exception as exc:
                results.append((name, False, f"{type(exc).__name__}: {exc}"))
    finally:
        addon.unregister()

    for name, ok, detail in results:
        print(f"CHECK {name} {'PASS' if ok else 'FAIL'} {detail}")
    passed = sum(1 for _, ok, _ in results if ok)
    failed = len(results) - passed
    print(f"RISULTATO passati={passed} falliti={failed} totale={len(results)}")


if __name__ == "__main__":
    main()
