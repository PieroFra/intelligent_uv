# -*- coding: utf-8 -*-
"""Test sulle funzioni pure di recovery.py: find_failed_islands e add_relief_seams."""

import importlib
import os
import sys
import traceback

import bpy
import math
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(ROOT))
PACKAGE = os.path.basename(ROOT)


def module(name):
    return importlib.import_module(PACKAGE + '.' + name)


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


def _cube():
    bpy.ops.mesh.primitive_cube_add(size=2.0, location=(0.0, 0.0, 0.0))
    obj = bpy.context.object
    assert obj is not None and obj.type == "MESH", "Cubo di prova non creato"
    return obj


def _create_uv_layer(mesh, name):
    uv_layers = mesh.uv_layers
    try:
        uv_layer = uv_layers.new(name=name)
    except Exception:
        uv_layer = uv_layers.new()
        try:
            uv_layer.name = name
        except Exception:
            pass
    assert uv_layer is not None, "Impossibile creare il layer UV '%s'" % name
    return uv_layer


def test_find_failed_islands_single_collapsed_face():
    obj = None
    try:
        obj = _cube()
        mesh = obj.data
        utils = module("utils")
        mesh_analysis_mod = module("mesh_analysis")
        island_mod = module("island_extraction")
        recovery = module("recovery")

        uv_name = "SmartUV"

        # Rimuovi i layer UV preesistenti per non lasciare layer a coordinate zero
        # che smart_project potrebbe lasciare come layer attivo precedente.
        for _existing in list(mesh.uv_layers):
            try:
                mesh.uv_layers.remove(_existing)
            except Exception:
                pass

        uv_layer = _create_uv_layer(mesh, uv_name)

        # Rendi attivo il layer creato per lo Smart UV Project.
        mesh.uv_layers.active = uv_layer
        try:
            mesh.uv_layers.active_index = mesh.uv_layers.find(uv_name)
        except Exception:
            pass

        # Seleziona l'oggetto e passa in edit mode per creare un UV valido.
        for o in bpy.context.view_layer.objects:
            try:
                o.select_set(False)
            except Exception:
                pass
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj

        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="SELECT")
        assert bpy.ops.uv.smart_project(
            angle_limit=math.radians(66.0),
            island_margin=0.0,
            correct_aspect=True,
            scale_to_bounds=False,
        ) == {"FINISHED"}, "Smart UV Project fallito"
        bpy.ops.object.mode_set(mode="OBJECT")

        # Smart UV Project puo' creare un proprio layer attivo: usalo esplicitamente
        # e scarta gli eventuali layer rimasti a coordinate zero.
        _active_uv = mesh.uv_layers.active
        if _active_uv is not None:
            try:
                _active_uv.name = uv_name
            except Exception:
                pass
        for _layer in list(mesh.uv_layers):
            if _layer == mesh.uv_layers.active:
                continue
            try:
                _all_zero = all(
                    float(_d.uv[0]) == 0.0 and float(_d.uv[1]) == 0.0
                    for _d in _layer.data
                )
            except Exception:
                _all_zero = False
            if _all_zero:
                try:
                    mesh.uv_layers.remove(_layer)
                except Exception:
                    pass
        for _layer in mesh.uv_layers:
            if _layer == mesh.uv_layers.active:
                continue
            try:
                _all_zero = all(
                    float(_d.uv[0]) == 0.0 and float(_d.uv[1]) == 0.0
                    for _d in _layer.data
                )
            except Exception:
                _all_zero = False
            assert not _all_zero, (
                "Layer UV a coordinate zero rimasto: %s"
                % getattr(_layer, "name", "?")
            )

        uv_layer = mesh.uv_layers.active
        assert uv_layer is not None, "Nessun layer UV attivo dopo Smart UV Project"

        # Verifica che nessuna isola sia segnalata prima del collasso.
        mesh_analysis = mesh_analysis_mod.MeshAnalyzer.analyze(mesh)
        assert getattr(mesh_analysis, "ok", False), (
            "Analisi mesh del cubo fallita: %s"
            % "; ".join(getattr(mesh_analysis, "errors", [])[:3])
        )

        region_ids = list(range(len(mesh.polygons)))
        island_analysis = island_mod.IslandExtractor.analyze(
            obj=obj, settings=None, region_ids=region_ids
        )
        assert getattr(island_analysis, "ok", False), (
            "Analisi isole del cubo fallita: %s"
            % "; ".join(getattr(island_analysis, "errors", [])[:3])
        )

        failed_before = recovery.find_failed_islands(
            mesh, uv_layer, island_analysis, mesh_analysis
        )
        assert isinstance(failed_before, list), (
            "find_failed_islands deve restituire una lista"
        )
        assert len(failed_before) == 0, (
            "Attese 0 isole segnalate prima del collasso, trovate %d"
            % len(failed_before)
        )

        # Collassa a un punto i loop UV di una sola faccia (la prima).
        collapsed_face = 0
        poly = mesh.polygons[collapsed_face]
        start, end = utils.polygon_loop_range(poly)
        for li in range(start, end):
            utils.set_loop_uv(uv_layer, li, 0.0, 0.0)

        mesh_analysis = mesh_analysis_mod.MeshAnalyzer.analyze(mesh)
        assert getattr(mesh_analysis, "ok", False), (
            "Analisi mesh del cubo fallita: %s"
            % "; ".join(getattr(mesh_analysis, "errors", [])[:3])
        )

        island_analysis = island_mod.IslandExtractor.analyze(
            obj=obj, settings=None, region_ids=region_ids
        )
        assert getattr(island_analysis, "ok", False), (
            "Analisi isole del cubo fallita: %s"
            % "; ".join(getattr(island_analysis, "errors", [])[:3])
        )

        failed = recovery.find_failed_islands(
            mesh, uv_layer, island_analysis, mesh_analysis
        )
        assert isinstance(failed, list), "find_failed_islands deve restituire una lista"
        assert len(failed) == 1, (
            "Attesa una sola isola segnalata, trovate %d" % len(failed)
        )

        _island_id, faces, collapsed_count = failed[0]
        assert len(faces) == 1, (
            "L'isola segnalata deve contenere 1 faccia, trovate %d" % len(faces)
        )
        assert collapsed_face in faces, (
            "La faccia collassata (%d) non e' tra quelle segnalate: %s"
            % (collapsed_face, repr(faces))
        )
        assert collapsed_count == 1, (
            "collapsed_count atteso 1, ottenuto %d" % collapsed_count
        )
    finally:
        _remove(obj)


def test_add_relief_seams_closed_island():
    obj = None
    try:
        obj = _cube()
        mesh = obj.data
        mesh_analysis_mod = module("mesh_analysis")
        recovery = module("recovery")

        mesh_analysis = mesh_analysis_mod.MeshAnalyzer.analyze(mesh)
        assert getattr(mesh_analysis, "ok", False), (
            "Analisi mesh del cubo fallita: %s"
            % "; ".join(getattr(mesh_analysis, "errors", [])[:3])
        )

        is_seam = [False] * int(getattr(mesh_analysis, "edge_count", 0))
        assert len(is_seam) > 0, "Il cubo non ha edge"

        # Isola chiusa: tutte le facce del cubo.
        faces = list(range(int(getattr(mesh_analysis, "face_count", 0))))
        assert len(faces) >= 4, "Servono almeno 4 facce per l'isola chiusa"

        added_first = recovery.add_relief_seams(
            mesh_analysis, is_seam, faces, 15.0
        )
        assert isinstance(added_first, int), "add_relief_seams deve restituire un int"
        assert added_first > 0, (
            "Prima chiamata: attese seam aggiunte, ottenute %d" % added_first
        )
        assert any(bool(v) for v in is_seam), (
            "Prima chiamata: is_seam non e' stato marcato"
        )

        added_second = recovery.add_relief_seams(
            mesh_analysis, is_seam, faces, 15.0
        )
        assert added_second == 0, (
            "Seconda chiamata: attese 0 seam aggiunte, ottenute %d" % added_second
        )
    finally:
        _remove(obj)


if __name__ == "__main__":
    passed = 0
    failed = 0
    tests = (
        test_find_failed_islands_single_collapsed_face,
        test_add_relief_seams_closed_island,
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