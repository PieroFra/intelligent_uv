# -*- coding: utf-8 -*-
"""Contratto di CurvatureEstimator._otsu_threshold su insiemi sintetici.

Il metodo restituisce una soglia in gradi, oppure None quando non esiste
una divisione valida (vuoto, valore singolo). Non deve mai andare in crash.
"""

import importlib
import math
import os
import sys
import traceback

import bmesh
import bpy

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(ROOT))
PACKAGE = os.path.basename(ROOT)


def estimator():
    try:
        module = importlib.import_module(PACKAGE + '.curvature')
    except ModuleNotFoundError as exc:
        raise AssertionError('Modulo curvature obbligatorio assente') from exc
    assert callable(getattr(module.CurvatureEstimator, '_otsu_threshold', None)), \
        '_otsu_threshold assente'
    return module.CurvatureEstimator


def test_otsu_bimodale_netto_tra_i_picchi():
    cls = estimator()
    low = [2.0 + 0.02 * i for i in range(50)]
    high = [60.0 + 0.2 * i for i in range(50)]
    threshold = cls._otsu_threshold(low + high)
    assert threshold is not None, 'Bimodale netto senza soglia'
    assert max(low) < threshold < min(high), (
        f'Soglia {threshold} fuori dal gap tra {max(low)} e {min(high)}')


def test_otsu_bimodale_indipendente_dall_ordine():
    cls = estimator()
    low = [2.0 + 0.02 * i for i in range(50)]
    high = [60.0 + 0.2 * i for i in range(50)]
    direct = cls._otsu_threshold(low + high)
    reversed_order = cls._otsu_threshold(list(reversed(low + high)))
    assert direct is not None and reversed_order is not None, 'Soglia assente'
    assert abs(direct - reversed_order) < 1e-9, (
        f'Soglia dipende dall ordine: {direct} contro {reversed_order}')


def test_otsu_uniforme_resta_nel_range():
    cls = estimator()
    angles = [i * 180.0 / 200.0 for i in range(200)]
    threshold = cls._otsu_threshold(angles)
    assert threshold is not None, 'Distribuzione uniforme senza soglia'
    assert min(angles) <= threshold <= max(angles), (
        f'Soglia {threshold} fuori dal range degli angoli')


def test_otsu_valore_singolo_nessuna_soglia():
    cls = estimator()
    threshold = cls._otsu_threshold([30.0] * 40)
    assert threshold is None, f'Valore singolo deve dare None, ottenuto {threshold}'


def test_otsu_vuoto_nessuna_soglia():
    cls = estimator()
    threshold = cls._otsu_threshold([])
    assert threshold is None, f'Lista vuota deve dare None, ottenuto {threshold}'


def test_otsu_none_nessun_crash():
    cls = estimator()
    # Attesa corretta: None in ingresso non deve sollevare. Il codice attuale
    # itera su angles senza guardia e solleva TypeError: vedi segnalazione.
    threshold = cls._otsu_threshold(None)
    assert threshold is None, f'None in ingresso deve dare None, ottenuto {threshold}'


def _drop(obj):
    if obj is None:
        return
    mesh = getattr(obj, 'data', None)
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


def _build_bent_strip(name, bend_angles):
    """Costruisce una strip aperta di quad con angoli diedri esatti in gradi."""
    mesh = bpy.data.meshes.new(name + '_mesh')
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)

    bm = bmesh.new()
    x, z, theta = 0.0, 0.0, 0.0
    v0 = bm.verts.new((x, 0.0, z))
    v1 = bm.verts.new((x, 1.0, z))

    for idx in range(len(bend_angles) + 1):
        x += math.cos(theta)
        z += math.sin(theta)
        v2 = bm.verts.new((x, 1.0, z))
        v3 = bm.verts.new((x, 0.0, z))
        bm.faces.new((v0, v1, v2, v3))
        v0, v1 = v3, v2
        if idx < len(bend_angles):
            theta += math.radians(bend_angles[idx])

    bm.normal_update()
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()
    return obj


def test_estimate_uv_sphere_sotto_30_gradi():
    addon = importlib.import_module(PACKAGE)
    MeshAnalyzer = importlib.import_module(PACKAGE + '.mesh_analysis').MeshAnalyzer
    MaterialAnalyzer = importlib.import_module(PACKAGE + '.material_analysis').MaterialAnalyzer
    SeamPlanner = importlib.import_module(PACKAGE + '.seam_planning').SeamPlanner
    cls = estimator()

    assert cls.HARD_EDGE_FLOOR_DEG == 30.0, (
        f'HARD_EDGE_FLOOR_DEG atteso 30.0, ottenuto {cls.HARD_EDGE_FLOOR_DEG}')

    addon.register()
    obj = None
    settings = None
    prev_auto = prev_sep = None
    try:
        bpy.ops.mesh.primitive_uv_sphere_add(segments=32, ring_count=16, radius=1.0)
        obj = bpy.context.active_object
        ma = MeshAnalyzer.analyze(obj.data)
        assert ma.ok, 'MeshAnalyzer.analyze fallito sulla sfera UV'
        mat = MaterialAnalyzer.analyze(obj, ma)
        assert mat.ok, 'MaterialAnalyzer.analyze fallito sulla sfera UV'

        angles = cls.collect_angles(ma)
        assert angles and 0.0 < max(angles) < 15.0 < 30.0, (
            f'Angolo massimo inatteso sulla sfera UV: {max(angles) if angles else None}')

        est = cls.estimate(ma, fallback=60.0)
        assert est.ok is True, 'CurvatureEstimator.estimate deve restituire ok=True'
        assert est.method == 'no_hard_edges', f'Metodo atteso no_hard_edges, ottenuto {est.method}'
        assert est.threshold == 60.0, f'Soglia attesa 60.0, ottenuta {est.threshold}'

        settings = bpy.context.scene.intelligent_uv_settings
        prev_auto = settings.auto_curvature_threshold
        prev_sep = settings.separate_by_material
        settings.auto_curvature_threshold = True
        settings.separate_by_material = False

        plan = SeamPlanner.plan(ma, mat, settings)
        assert plan.ok is True, 'SeamPlanner.plan fallito sulla sfera UV'
        assert plan.angle_seam_count == 0, (
            f'Attesi 0 seam angolari su sfera liscia, ottenuti {plan.angle_seam_count}')
        assert plan.curvature_estimate is not None and plan.curvature_estimate.method == 'no_hard_edges', (
            f'Metodo stima nel plan inatteso: {getattr(plan.curvature_estimate, "method", None)}')
    finally:
        if settings is not None and prev_auto is not None:
            settings.auto_curvature_threshold = prev_auto
            settings.separate_by_material = prev_sep
        _drop(obj)
        addon.unregister()


def test_bimodale_sotto_30_smooth_mesh_guard():
    addon = importlib.import_module(PACKAGE)
    MeshAnalyzer = importlib.import_module(PACKAGE + '.mesh_analysis').MeshAnalyzer
    MaterialAnalyzer = importlib.import_module(PACKAGE + '.material_analysis').MaterialAnalyzer
    SeamPlanner = importlib.import_module(PACKAGE + '.seam_planning').SeamPlanner
    cls = estimator()

    addon.register()
    obj = None
    settings = None
    prev_auto = prev_thresh = prev_sep = None
    try:
        # 16 quad, 15 spigoli manifold: 10 a 5 deg e 5 a 25 deg (disco topologico < 30 deg)
        obj = _build_bent_strip('b4_bent_strip_sub30', [5.0] * 10 + [25.0] * 5)
        ma = MeshAnalyzer.analyze(obj.data)
        assert ma.ok, 'MeshAnalyzer.analyze fallito sulla strip'
        mat = MaterialAnalyzer.analyze(obj, ma)
        assert mat.ok, 'MaterialAnalyzer.analyze fallito sulla strip'

        angles = cls.collect_angles(ma)
        assert len(angles) == 15, f'Attesi 15 angoli manifold, ottenuti {len(angles)}'
        assert abs(max(angles) - 25.0) < 1e-4 and max(angles) < 30.0, (
            f'Angolo massimo inatteso nella strip: {max(angles)}')
        otsu = cls._otsu_threshold(angles)
        assert otsu is not None and 10.0 < otsu < 20.0, (
            f'Soglia Otsu attesa ~15 deg, ottenuta {otsu}')

        est = cls.estimate(ma, fallback=60.0)
        assert est.ok is True, 'CurvatureEstimator.estimate deve restituire ok=True'
        assert est.method == 'no_hard_edges', (
            f'Metodo atteso no_hard_edges sotto 30 deg, ottenuto {est.method}')
        assert est.threshold == 60.0, f'Soglia attesa 60.0, ottenuta {est.threshold}'

        settings = bpy.context.scene.intelligent_uv_settings
        prev_auto = settings.auto_curvature_threshold
        prev_thresh = settings.curvature_threshold
        prev_sep = settings.separate_by_material
        settings.auto_curvature_threshold = False
        settings.curvature_threshold = 10.0
        settings.separate_by_material = False

        plan = SeamPlanner.plan(ma, mat, settings)
        assert plan.ok is True, 'SeamPlanner.plan fallito sulla strip'
        assert plan.angle_seam_count == 0, (
            f'smooth_mesh guard doveva impedire seam angolari, ottenuti {plan.angle_seam_count}')
        assert len(plan.seam_edges) == 0, (
            f'Attesi 0 seam_edges su disco < 30 deg, ottenuti {len(plan.seam_edges)}')
        assert plan.region_count == 1, f'Attesa 1 regione, ottenute {plan.region_count}'
    finally:
        if settings is not None and prev_auto is not None:
            settings.auto_curvature_threshold = prev_auto
            settings.curvature_threshold = prev_thresh
            settings.separate_by_material = prev_sep
        _drop(obj)
        addon.unregister()


def test_controllo_sopra_30_gradi_taglia_seam():
    addon = importlib.import_module(PACKAGE)
    MeshAnalyzer = importlib.import_module(PACKAGE + '.mesh_analysis').MeshAnalyzer
    MaterialAnalyzer = importlib.import_module(PACKAGE + '.material_analysis').MaterialAnalyzer
    SeamPlanner = importlib.import_module(PACKAGE + '.seam_planning').SeamPlanner
    cls = estimator()

    addon.register()
    obj = None
    settings = None
    prev_auto = prev_sep = None
    try:
        bpy.ops.mesh.primitive_cylinder_add(
            vertices=32, radius=1.0, depth=2.0, end_fill_type='NGON'
        )
        obj = bpy.context.active_object
        ma = MeshAnalyzer.analyze(obj.data)
        assert ma.ok, 'MeshAnalyzer.analyze fallito sul cilindro'
        mat = MaterialAnalyzer.analyze(obj, ma)
        assert mat.ok, 'MaterialAnalyzer.analyze fallito sul cilindro'

        est = cls.estimate(ma, fallback=60.0)
        assert est.ok is True, 'CurvatureEstimator.estimate fallito sul cilindro'
        assert est.method == 'otsu', f'Metodo atteso otsu sul cilindro, ottenuto {est.method}'
        assert 15.0 < est.threshold < 90.0, f'Soglia Otsu inattesa: {est.threshold}'

        settings = bpy.context.scene.intelligent_uv_settings
        prev_auto = settings.auto_curvature_threshold
        prev_sep = settings.separate_by_material
        settings.auto_curvature_threshold = True
        settings.separate_by_material = False

        plan = SeamPlanner.plan(ma, mat, settings)
        assert plan.ok is True, 'SeamPlanner.plan fallito sul cilindro'
        assert plan.angle_seam_count > 0, (
            f'Cilindro con tappi a 90 deg deve tagliare seam angolari, ottenuti {plan.angle_seam_count}')
    finally:
        if settings is not None and prev_auto is not None:
            settings.auto_curvature_threshold = prev_auto
            settings.separate_by_material = prev_sep
        _drop(obj)
        addon.unregister()


if __name__ == '__main__':
    passed = failed = 0
    tests = [
        test_otsu_bimodale_netto_tra_i_picchi,
        test_otsu_bimodale_indipendente_dall_ordine,
        test_otsu_uniforme_resta_nel_range,
        test_otsu_valore_singolo_nessuna_soglia,
        test_otsu_vuoto_nessuna_soglia,
        test_otsu_none_nessun_crash,
        test_estimate_uv_sphere_sotto_30_gradi,
        test_bimodale_sotto_30_smooth_mesh_guard,
        test_controllo_sopra_30_gradi_taglia_seam,
    ]
    for test in tests:
        try:
            test()
            passed += 1
            print(f'CHECK {test.__name__} PASS')
        except Exception as exc:
            failed += 1
            print(f'CHECK {test.__name__} FAIL {type(exc).__name__}: {exc}')
            traceback.print_exc()
    print(f'RISULTATO passati={passed} falliti={failed} totale={len(tests)}')
