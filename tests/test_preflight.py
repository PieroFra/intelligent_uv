# -*- coding: utf-8 -*-
"""Pre-flight checks on a healthy cube and a broken cube."""

import importlib
import os
import sys
import traceback

import bpy

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(ROOT))
PACKAGE = os.path.basename(ROOT)


def module(name):
    return importlib.import_module(PACKAGE + '.' + name)


def _findings_signature(result):
    return (
        bool(result.ok),
        tuple((f.severity, f.title, f.detail, f.fix, int(f.count))
              for f in result.findings),
    )


def test_preflight():
    healthy_obj = None
    broken_obj = None
    try:
        bpy.ops.mesh.primitive_cube_add(size=2.0, location=(-3.0, 0.0, 0.0))
        healthy_obj = bpy.context.object
        assert healthy_obj is not None and healthy_obj.type == 'MESH', (
            "Cubo sano non creato"
        )

        bpy.ops.mesh.primitive_cube_add(size=2.0, location=(3.0, 0.0, 0.0))
        broken_obj = bpy.context.object
        assert broken_obj is not None and broken_obj.type == 'MESH', (
            "Cubo rotto non creato"
        )
        # Non-uniform object scale: a blocker for the pre-flight.
        broken_obj.scale = (2.0, 1.0, 1.0)

        preflight = module('preflight').Preflight
        mesh_analysis_mod = module('mesh_analysis')

        ma_broken = mesh_analysis_mod.MeshAnalyzer.analyze(broken_obj.data)
        res_broken = preflight.run(broken_obj, ma_broken)

        assert isinstance(res_broken.findings, list), "findings non e una lista"
        assert len(res_broken.findings) > 0, "Elenco controlli vuoto per il cubo rotto"
        assert res_broken.ok == (len(res_broken.blockers) == 0), (
            "Flag complessivo incoerente con la severita dei controlli"
        )
        assert not res_broken.ok, "Il cubo rotto dovrebbe avere errori bloccanti"
        for finding in res_broken.findings:
            assert isinstance(finding.title, str) and finding.title.strip(), (
                "Nome del controllo vuoto"
            )
            assert isinstance(finding.detail, str) and finding.detail.strip(), (
                "Messaggio del controllo vuoto"
            )

        ma_healthy = mesh_analysis_mod.MeshAnalyzer.analyze(healthy_obj.data)
        res_healthy = preflight.run(healthy_obj, ma_healthy)

        assert res_healthy.ok, "Il cubo sano non dovrebbe produrre errori bloccanti"
        assert len(res_healthy.blockers) == 0, "Il cubo sano produce errori bloccanti"
        assert res_healthy.ok == (len(res_healthy.blockers) == 0), (
            "Flag complessivo incoerente (cubo sano)"
        )

        ma_broken_2 = mesh_analysis_mod.MeshAnalyzer.analyze(broken_obj.data)
        res_broken_2 = preflight.run(broken_obj, ma_broken_2)
        assert _findings_signature(res_broken) == _findings_signature(res_broken_2), (
            "Due chiamate identiche danno esito diverso"
        )
    finally:
        for obj in (healthy_obj, broken_obj):
            if obj is not None:
                try:
                    bpy.data.objects.remove(obj, do_unlink=True)
                except Exception:
                    pass


if __name__ == '__main__':
    passed = 0
    failed = 0
    try:
        test_preflight()
        passed = 1
    except Exception:
        failed = 1
        traceback.print_exc()
    print("RISULTATO passati={} falliti={} totale=1".format(passed, failed))
