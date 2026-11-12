# -*- coding: utf-8 -*-
"""Tests for region_merge.py: RegionMerger.merge invariants."""

import importlib
import os
import sys
import traceback
from collections import Counter

import bpy

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(ROOT))
PACKAGE = os.path.basename(ROOT)


def module(name):
    return importlib.import_module(PACKAGE + '.' + name)


def _remove(obj, mesh):
    try:
        if obj is not None:
            bpy.data.objects.remove(obj, do_unlink=True)
    except Exception:
        pass
    try:
        if mesh is not None:
            bpy.data.meshes.remove(mesh)
    except Exception:
        pass


def test_region_merge_sphere_invariants():
    bpy.ops.mesh.primitive_uv_sphere_add(segments=32, ring_count=16, radius=1.0)
    obj = bpy.context.object
    mesh = obj.data
    try:
        analysis = module('mesh_analysis').MeshAnalyzer.analyze(mesh)
        assert analysis.ok, 'Analisi mesh della sfera fallita'

        material = module('material_analysis').MaterialAnalyzer.analyze(obj, analysis)
        assert material.ok, 'Analisi materiali della sfera fallita'

        settings = bpy.context.scene.intelligent_uv_settings

        seam_plan = module('seam_planning').SeamPlanner.plan(analysis, material, settings)
        assert seam_plan.ok, 'Pianificazione seam fallita: %s' % repr(getattr(seam_plan, 'errors', None))

        Merger = module('region_merge').RegionMerger
        r1 = Merger.merge(analysis, material, seam_plan, settings)
        r2 = Merger.merge(analysis, material, seam_plan, settings)

        assert r1.ok, 'RegionMerger.merge fallito (prima chiamata)'
        assert r2.ok, 'RegionMerger.merge fallito (seconda chiamata)'

        assert len(r1.region_ids) == analysis.face_count, (
            'Ogni faccia deve comparire in esattamente una regione: '
            'len(region_ids)=%d != face_count=%d' % (len(r1.region_ids), analysis.face_count)
        )
        assert all(isinstance(rid, int) and rid >= 0 for rid in r1.region_ids), (
            'region_ids contiene id non valido o faccia non assegnata'
        )

        counts = Counter(r1.region_ids)
        for rid in range(r1.region_count):
            assert counts.get(rid, 0) > 0, (
                'Regione %d vuota dopo il merge' % rid
            )

        assert r1.region_count <= seam_plan.region_count, (
            'Il merge ha aumentato il numero di regioni: %d > %d'
            % (r1.region_count, seam_plan.region_count)
        )
        assert r1.regions_before == seam_plan.region_count, (
            'regions_before incoerente con il piano: %d != %d'
            % (r1.regions_before, seam_plan.region_count)
        )

        assert r2.region_ids == r1.region_ids, (
            'Determinismo: region_ids diversi tra due chiamate identiche'
        )
        assert r2.region_count == r1.region_count, (
            'Determinismo: region_count diverso (%d vs %d)' % (r2.region_count, r1.region_count)
        )
    finally:
        _remove(obj, mesh)


if __name__ == '__main__':
    passed = 0
    failed = 0
    tests = (test_region_merge_sphere_invariants,)
    try:
        importlib.import_module(PACKAGE).register()
    except Exception:
        failed = len(tests)
        traceback.print_exc()
    else:
        for test in tests:
            try:
                test()
                passed += 1
            except Exception:
                failed += 1
                traceback.print_exc()
    print('RISULTATO passati={} falliti={} totale={}'.format(passed, failed, len(tests)))
    try:
        importlib.import_module(PACKAGE).unregister()
    except Exception:
        pass
