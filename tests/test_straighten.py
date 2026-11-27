# -*- coding: utf-8 -*-
"""Test straighten.py: rettifica di strip quad aperte e skip delle mesh non-quad."""

import importlib
import math
import os
import sys
import traceback

import bpy

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(ROOT))
PACKAGE = os.path.basename(ROOT)


def module(name):
    return importlib.import_module(PACKAGE + "." + name)


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


def _fresh_uv_layer(mesh, name):
    for existing in list(mesh.uv_layers):
        try:
            mesh.uv_layers.remove(existing)
        except Exception:
            pass
    layer = mesh.uv_layers.new(name=name)
    assert layer is not None, "Impossibile creare il layer UV '%s'" % name
    mesh.uv_layers.active = layer
    return layer


def _smart_project(obj):
    for other in bpy.context.view_layer.objects:
        other.select_set(False)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    # Unwrap e non Smart UV Project: senza seam la strip aperta resta un'unica
    # isola, mentre smart_project la spezzetta per angolo tra facce.
    assert bpy.ops.uv.unwrap(
        method="ANGLE_BASED", fill_holes=True, correct_aspect=True,
        use_subsurf_data=False, margin=0.0,
    ) == {"FINISHED"}, "Unwrap fallito"
    bpy.ops.object.mode_set(mode="OBJECT")


def _islands(obj):
    mesh_analysis = module("mesh_analysis").MeshAnalyzer.analyze(obj.data)
    assert getattr(mesh_analysis, "ok", False), "Analisi mesh fallita"
    # region_ids=None: l'estrattore calcola le componenti connesse topologiche,
    # che per una strip aperta senza seam e' un'unica isola.
    island_analysis = module("island_extraction").IslandExtractor.analyze(obj=obj)
    assert getattr(island_analysis, "ok", False), "Analisi isole fallita"
    return mesh_analysis, island_analysis


def _uv_snapshot(mesh, layer):
    return tuple(
        (loop_uv[0], loop_uv[1])
        for loop_uv in (tuple(item.uv) for item in layer.data)
    )


def _fill_efficiency(obj, island_analysis):
    layer = obj.data.uv_layers.active
    fill = module("distortion").DistortionAnalyzer.measure_fill(
        obj.data, layer, island_analysis
    )
    assert fill is not None, "measure_fill non ha restituito nulla"
    return float(fill["efficiency"])


def _real_overlaps(obj, island_analysis):
    pairs, checked, gave_up = (
        module("distortion").DistortionAnalyzer.find_real_overlaps(
            obj.data, obj.data.uv_layers.active, island_analysis
        )
    )
    return len(pairs), int(checked), int(gave_up)


def _assert_grid_cells(mesh, layer):
    """Ogni quad dell'isola deve essere un rettangolo allineato agli assi."""
    polygons = mesh.polygons
    utils = module("utils")
    assert len(polygons) >= 1, "Mesh senza facce"
    for poly in polygons:
        start, end = utils.polygon_loop_range(poly)
        uvs = [utils.loop_uv(layer, li) for li in range(start, end)]
        assert all(uv is not None for uv in uvs), "Loop UV illeggibile"
        u_values = sorted({round(uv[0], 6) for uv in uvs})
        v_values = sorted({round(uv[1], 6) for uv in uvs})
        assert len(u_values) == 2 and len(v_values) == 2, (
            "La faccia %d non e' un rettangolo allineato agli assi: u=%s v=%s"
            % (poly.index, u_values, v_values)
        )
        uvs_rounded = [(round(uv[0], 6), round(uv[1], 6)) for uv in uvs]
        counts = {corner: uvs_rounded.count(corner) for corner in uvs_rounded}
        assert all(count == 1 for count in counts.values()), (
            "La faccia %d ha angoli UV duplicati: %s"
            % (poly.index, repr(uvs_rounded))
        )


def _assert_shared_corners_match(mesh, layer):
    """Vertici condivisi da facce adiacenti devono avere UV identiche."""
    vertex_uvs = {}
    polygons = mesh.polygons
    utils = module("utils")
    for poly in polygons:
        start, end = utils.polygon_loop_range(poly)
        for li in range(start, end):
            vertex = mesh.loops[li].vertex_index
            uv = utils.loop_uv(layer, li)
            key = (round(uv[0], 6), round(uv[1], 6))
            if vertex in vertex_uvs:
                assert vertex_uvs[vertex] == key, (
                    "Il vertice %d ha UV diverse tra facce adiacenti: %s vs %s"
                    % (vertex, vertex_uvs[vertex], key)
                )
            else:
                vertex_uvs[vertex] = key


def test_cylinder_strip_rectified():
    obj = None
    try:
        bpy.ops.object.select_all(action="SELECT")
        bpy.ops.object.delete(use_global=False)
        bpy.ops.mesh.primitive_cylinder_add(
            vertices=16, radius=1.0, depth=2.0, end_fill_type="NOTHING",
            location=(0.0, 0.0, 0.0),
        )
        obj = bpy.context.object
        assert obj is not None and obj.type == "MESH", "Cilindro di prova non creato"
        mesh = obj.data
        assert all(len(poly.vertices) == 4 for poly in mesh.polygons), (
            "Il cilindro aperto deve essere solo quad"
        )

        layer = _fresh_uv_layer(mesh, "SmartUV")
        # Il fianco del cilindro e' un anello chiuso a livello di mesh: il
        # flag use_seam non basta, la griglia richiede un bordo reale. Si
        # spacca fisicamente un bordo verticale per aprire la strip.
        import bmesh
        bm = bmesh.new()
        bm.from_mesh(mesh)
        targets = []
        for edge in bm.edges:
            va, vb = edge.verts[0].co, edge.verts[1].co
            if (
                abs(va.x - vb.x) < 1e-5
                and abs(va.y - vb.y) < 1e-5
                and abs(va.z - vb.z) > 1e-3
            ):
                targets.append(edge)
                break
        assert targets, "Nessun bordo verticale da spaccare"
        bmesh.ops.split_edges(bm, edges=targets)
        bm.to_mesh(mesh)
        mesh.update()
        bm.free()
        _smart_project(obj)
        # Il riferimento RNA al layer non sopravvive al round trip in edit
        # mode: rileggilo per nome prima di toccare le UV.
        layer = mesh.uv_layers.get("SmartUV")
        assert layer is not None, "Layer SmartUV perso dopo l'unwrap"

        mesh_analysis, island_analysis = _islands(obj)
        assert len(island_analysis.islands) == 1, (
            "Attesa una sola isola (strip aperta), trovate %d"
            % len(island_analysis.islands)
        )
        assert len(island_analysis.islands[0].get("faces", [])) >= 6, (
            "L'isola della strip ha meno di 6 facce"
        )

        # Warp deterministico: la strip parte da un layout non rettilineo,
        # cosi' la rettifica ha qualcosa da migliorare.
        utils = module("utils")
        for li in range(len(mesh.loops)):
            uv = utils.loop_uv(layer, li)
            assert uv is not None, "Loop UV illeggibile prima del warp"
            u, v = uv
            utils.set_loop_uv(
                layer, li,
                u + 0.08 * math.sin(6.0 * v),
                v + 0.08 * math.cos(6.0 * u),
            )

        _, island_before = _islands(obj)
        fill_before = _fill_efficiency(obj, island_before)
        assert fill_before < 0.98, (
            "Il warp non ha deformato abbastanza il layout: efficiency=%f"
            % fill_before
        )
        fill_data_before = module("distortion").DistortionAnalyzer.measure_fill(
            mesh, layer, island_before
        )
        island_area_before = float(fill_data_before["island_area"])

        result = module("straighten").straighten_islands(
            mesh, layer, island_before
        )
        assert getattr(result, "ok", False), "straighten_islands fallito"
        assert result.straightened_count == 1, (
            "Attesa 1 isola rettificata, ottenute %d (warnings=%s)"
            % (result.straightened_count, repr(result.warnings))
        )
        assert result.skipped_count == 0, (
            "Nessuna isola deve essere scartata sulla strip quad (warnings=%s)"
            % repr(result.warnings)
        )

        _assert_grid_cells(mesh, layer)
        _assert_shared_corners_match(mesh, layer)

        _, island_after = _islands(obj)
        fill_after = _fill_efficiency(obj, island_after)
        assert fill_after > fill_before, (
            "La rettifica non migliora l'occupazione UV: before=%f after=%f"
            % (fill_before, fill_after)
        )
        assert fill_after >= 0.999, (
            "Un layout a griglia deve riempire il proprio bounding box: "
            "efficiency=%f" % fill_after
        )

        overlaps, _checked, gave_up = _real_overlaps(obj, island_after)
        assert overlaps == 0, "Overlap reali dopo la rettifica: %d" % overlaps
        assert gave_up == 0, "Controllo overlap incompleto (gave_up=%d)" % gave_up

        fill_data_after = module("distortion").DistortionAnalyzer.measure_fill(
            mesh, layer, island_after
        )
        island_area_after = float(fill_data_after["island_area"])
        assert abs(island_area_after - island_area_before) <= 1e-6, (
            "L'area UV dell'isola non e' preservata: before=%f after=%f"
            % (island_area_before, island_area_after)
        )
    finally:
        _remove(obj)


def test_ngon_strip_skipped():
    obj = None
    try:
        bpy.ops.object.select_all(action="SELECT")
        bpy.ops.object.delete(use_global=False)
        # Strip aperta di 5 quad + 1 n-gon (ultime tre celle fuse in una):
        # 6 facce totali, quindi oltre la soglia minima, ma con una faccia
        # non quad.
        cols = 8
        verts = []
        for c in range(cols):
            verts.append((float(c), 0.0, 0.0))
            verts.append((float(c), 1.0, 0.0))
        faces = []
        for c in range(cols - 3):
            b0, t0, b1, t1 = 2 * c, 2 * c + 1, 2 * c + 2, 2 * c + 3
            faces.append((b0, b1, t1, t0))
        # Le colonne 5-7 fuse in un solo n-gon a 6 vertici.
        faces.append((10, 12, 14, 15, 13, 11))
        mesh_data = bpy.data.meshes.new("ngon_strip")
        mesh_data.from_pydata(verts, [], faces)
        mesh_data.update()
        obj = bpy.data.objects.new("ngon_strip", mesh_data)
        bpy.context.scene.collection.objects.link(obj)
        mesh = obj.data
        assert any(len(poly.vertices) != 4 for poly in mesh.polygons), (
            "La fixture deve contenere una faccia non quad"
        )
        assert len(mesh.polygons) >= 6, "Servono almeno 6 facce per il test"

        layer = _fresh_uv_layer(mesh, "SmartUV")
        # Proiezione UV banale ma valida: il modulo legge le UV originali.
        utils = module("utils")
        for poly in mesh.polygons:
            start, end = utils.polygon_loop_range(poly)
            for li in range(start, end):
                co = mesh.vertices[mesh.loops[li].vertex_index].co
                assert utils.set_loop_uv(layer, li, co.x / cols, co.y), (
                    "Scrittura UV fallita"
                )

        _, island_analysis = _islands(obj)
        assert len(island_analysis.islands) == 1, (
            "Attesa una sola isola, trovate %d" % len(island_analysis.islands)
        )
        before = _uv_snapshot(mesh, layer)

        result = module("straighten").straighten_islands(mesh, layer, island_analysis)
        assert getattr(result, "ok", False), "straighten_islands fallito"
        assert result.straightened_count == 0, (
            "Un'isola con n-gon non deve essere rettificata: %d rettificate"
            % result.straightened_count
        )
        assert result.skipped_count == 1, (
            "Attesa 1 isola scartata, trovate %d" % result.skipped_count
        )
        assert _uv_snapshot(mesh, layer) == before, (
            "Le UV sono cambiate su una mesh che deve restare intatta"
        )
    finally:
        _remove(obj)


def test_icosphere_skipped():
    obj = None
    try:
        bpy.ops.object.select_all(action="SELECT")
        bpy.ops.object.delete(use_global=False)
        bpy.ops.mesh.primitive_ico_sphere_add(
            subdivisions=2, radius=1.0, location=(0.0, 0.0, 0.0)
        )
        obj = bpy.context.object
        assert obj is not None and obj.type == "MESH", "Icosfera di prova non creata"
        mesh = obj.data
        assert all(len(poly.vertices) == 3 for poly in mesh.polygons), (
            "L'icosfera deve essere solo triangoli"
        )

        layer = _fresh_uv_layer(mesh, "SmartUV")
        _smart_project(obj)
        # Il riferimento RNA al layer non sopravvive al round trip in edit
        # mode: rileggilo per nome prima di toccare le UV.
        layer = mesh.uv_layers.get("SmartUV")
        assert layer is not None, "Layer SmartUV perso dopo l'unwrap"

        _, island_analysis = _islands(obj)
        assert len(island_analysis.islands) >= 1, "Icosfera senza isole"
        before = _uv_snapshot(mesh, layer)

        result = module("straighten").straighten_islands(mesh, layer, island_analysis)
        assert getattr(result, "ok", False), "straighten_islands fallito"
        assert result.straightened_count == 0, (
            "Un'isola di triangoli non deve essere rettificata: %d rettificate"
            % result.straightened_count
        )
        assert result.skipped_count == len(island_analysis.islands), (
            "Attese %d isole scartate, trovate %d"
            % (len(island_analysis.islands), result.skipped_count)
        )
        assert _uv_snapshot(mesh, layer) == before, (
            "Le UV sono cambiate su una mesh che deve restare intatta"
        )
    finally:
        _remove(obj)


if __name__ == "__main__":
    passed = 0
    failed = 0
    tests = (
        test_cylinder_strip_rectified,
        test_ngon_strip_skipped,
        test_icosphere_skipped,
    )
    for test in tests:
        try:
            test()
            passed += 1
        except Exception:
            failed += 1
            traceback.print_exc()
    print("RISULTATO passati={} falliti={} totale={}".format(
        passed, failed, len(tests)
    ))
