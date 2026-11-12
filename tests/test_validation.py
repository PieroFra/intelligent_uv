# -*- coding: utf-8 -*-
"""Validazione UV su una sfera 32x16 (r=1.0) con la pipeline di default.

Un unico controllo: esegue la pipeline UV (analisi mesh + piano seam +
marcatura + unwrap nativo) con i settings di default e poi la validazione
del risultato (ContextGuard + DistortionAnalyzer). Verifica gli invarianti
documentati: risultato con ok coerente con l'elenco degli errori, nessuna
faccia segnalata due volte (degenerate + misurate = totale facce), facce
degenerate contate uguali a quelle con area UV nulla costruite corrompendo
due loop UV, e nessun crash quando l'UV layer e' assente.
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


def _face_uv_area(pts):
    n = len(pts)
    if n < 3:
        return 0.0
    s = 0.0
    for i in range(n):
        u1, v1 = pts[i]
        u2, v2 = pts[(i + 1) % n]
        s += u1 * v2 - u2 * v1
    return abs(s) * 0.5


def _count_zero_uv_area_faces(mesh, coords):
    count = 0
    for poly in mesh.polygons:
        pts = [coords[li] for li in range(
            poly.loop_start, poly.loop_start + poly.loop_total)]
        if _face_uv_area(pts) <= 1e-14:
            count += 1
    return count


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


def test_validation():
    addon = importlib.import_module(PACKAGE)
    addon.register()
    objects = []
    try:
        settings = _settings()
        # Reset to RNA defaults: default pipeline.
        for prop in settings.bl_rna.properties:
            if prop.identifier == 'rna_type' or prop.is_readonly or prop.type == 'COLLECTION':
                continue
            try:
                setattr(settings, prop.identifier, prop.default)
            except Exception:  # noqa: BLE001
                pass

        obj = _make_sphere()
        objects.append(obj)

        mesh_analysis, plan = _plan_and_mark(obj, settings)
        module("uv_executor").MinimalUVExecutor.execute_unwrap(
            obj, settings, MARGIN_UV, use_seams=True
        )
        if obj.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")

        # ContextGuard: ok coerente con l'elenco degli errori.
        guard = module("validation").ContextGuard.validate_for_uv(bpy.context)
        assert guard.ok == (len(guard.errors) == 0), (
            "ok non coerente con gli errori: ok={0}, errors={1}".format(
                guard.ok, guard.errors))
        assert guard.ok is True, "contesto valido rifiutato: {0}".format(guard.errors)
        assert guard.errors == [], "errori inattesi: {0}".format(guard.errors)
        assert guard.face_count == len(obj.data.polygons), (
            "face_count errato: {0} vs {1}".format(guard.face_count, len(obj.data.polygons)))

        name, layer = _uv_layer(obj)
        coords = _uv_coords(layer)

        # Distortion: nessuna faccia segnalata due volte.
        distortion = module("distortion").DistortionAnalyzer.analyze(
            obj.data, layer, mesh_analysis
        )
        assert distortion.ok is True, "validazione distorsione non ok"
        assert distortion.degenerate_faces + distortion.faces_measured == len(obj.data.polygons), (
            "faccia segnalata due volte o mancante: degenerate={0} + measured={1} "
            "!= totale {2}".format(
                distortion.degenerate_faces, distortion.faces_measured,
                len(obj.data.polygons)))
        assert distortion.degenerate_faces == 0, (
            "sfera pulita con facce degenerate: {0}".format(distortion.degenerate_faces))

        # Corrompi due loop UV di una faccia triangolare per azzerarne l'area UV.
        poly0 = obj.data.polygons[0]
        assert poly0.loop_total >= 3, "prima faccia non ha almeno 3 loop"
        loops = list(range(poly0.loop_start, poly0.loop_start + poly0.loop_total))
        # Mantieni l'ultimo loop, collassa i primi due sul suo UV.
        anchor = coords[loops[-1]]
        for li in loops[:-1]:
            layer.data[li].uv = (float(anchor[0]), float(anchor[1]))
        coords_corr = _uv_coords(layer)

        expected_zero = _count_zero_uv_area_faces(obj.data, coords_corr)
        assert expected_zero >= 1, "corruzione non ha prodotto facce a area UV nulla"

        distortion2 = module("distortion").DistortionAnalyzer.analyze(
            obj.data, layer, mesh_analysis
        )
        assert distortion2.degenerate_faces == expected_zero, (
            "facce degenerate {0} != area UV nulla {1}".format(
                distortion2.degenerate_faces, expected_zero))
        assert distortion2.degenerate_faces + distortion2.faces_measured == len(obj.data.polygons), (
            "partizione rotta dopo corruzione: {0} + {1} != {2}".format(
                distortion2.degenerate_faces, distortion2.faces_measured,
                len(obj.data.polygons)))

        # Nessun crash quando l'UV layer e' assente.
        no_layer = module("distortion").DistortionAnalyzer.analyze(
            obj.data, None, mesh_analysis
        )
        assert no_layer is not None, "analyze ha restituito None senza UV layer"
        # _count_unsolved_islands senza layer: nessun crash, risultato (0, 0) o valido.
        unsolved, total = module("uv_executor").MinimalUVExecutor._count_unsolved_islands(
            obj.data, None
        )
        assert isinstance(unsolved, int) and isinstance(total, int), (
            "conteggio non intero senza UV layer: {0}, {1}".format(unsolved, total))

        return (
            "ok={0}, errors={1}, degenerate {2}->{3} (zero UV {4}), "
            "measured {5}, nessun crash senza UV layer".format(
                guard.ok, len(guard.errors), distortion.degenerate_faces,
                distortion2.degenerate_faces, expected_zero,
                distortion2.faces_measured)
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
        detail = test_validation()
        passed = 1
        print("CHECK test_validation PASS {0}".format(detail or ""))
    except Exception:
        failed = 1
        traceback.print_exc()
    print("RISULTATO passati={0} falliti={1} totale=1".format(passed, failed))
