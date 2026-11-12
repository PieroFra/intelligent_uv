# -*- coding: utf-8 -*-
"""Tests for vsa.py: VSA clustering invariants and plan_seams edge indices."""

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


def test_cube_cluster_coverage_and_no_empty():
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=(0.0, 0.0, 0.0))
    obj = bpy.context.object
    mesh = obj.data
    try:
        analysis = module('mesh_analysis').MeshAnalyzer.analyze(mesh)
        assert analysis.ok, 'Analisi mesh del cubo fallita'

        fc, cc = module('vsa').VSAClusterer.cluster(analysis)
        assert len(fc) == analysis.face_count, (
            'Ogni faccia deve appartenere a esattamente un cluster: '
            'len(face_cluster)=%d != face_count=%d' % (len(fc), analysis.face_count)
        )
        assert all(isinstance(c, int) and 0 <= c < cc for c in fc), (
            'Cluster id fuori range o non intero in face_cluster'
        )
        assert cc > 0, 'Il cubo deve produrre almeno un cluster'
        counts = Counter(fc)
        for cid in range(cc):
            assert counts.get(cid, 0) > 0, (
                'Cluster %d vuoto sul cubo' % cid
            )
    finally:
        _remove(obj, mesh)


def test_cube_creases_separate_clusters():
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=(0.0, 0.0, 0.0))
    obj = bpy.context.object
    mesh = obj.data
    try:
        analysis = module('mesh_analysis').MeshAnalyzer.analyze(mesh)
        assert analysis.ok, 'Analisi mesh del cubo fallita'

        fc, cc = module('vsa').VSAClusterer.cluster(analysis)
        angle_between = module('utils').angle_between_degrees
        for eidx, face_list in enumerate(analysis.faces_per_edge):
            if len(face_list) != 2:
                continue
            f1, f2 = face_list[0], face_list[1]
            if not (0 <= f1 < analysis.face_count and 0 <= f2 < analysis.face_count):
                continue
            angle = angle_between(
                analysis.face_normals[f1], analysis.face_normals[f2]
            )
            if angle >= 80.0:
                assert fc[f1] != fc[f2], (
                    'Crease a %.1f gradi non separa cluster diversi '
                    '(f%d=%d, f%d=%d)' % (angle, f1, fc[f1], f2, fc[f2])
                )
    finally:
        _remove(obj, mesh)


def test_plane_single_cluster():
    bpy.ops.mesh.primitive_grid_add(x_subdivisions=4, y_subdivisions=4, size=2.0)
    obj = bpy.context.object
    mesh = obj.data
    try:
        analysis = module('mesh_analysis').MeshAnalyzer.analyze(mesh)
        assert analysis.ok, 'Analisi mesh del piano fallita'

        fc, cc = module('vsa').VSAClusterer.cluster(analysis)
        assert len(fc) == analysis.face_count, (
            'Piano: face_cluster non copre tutte le facce'
        )
        assert all(0 <= c < cc for c in fc), 'Piano: cluster id non valido'
        counts = Counter(fc)
        for cid in range(cc):
            assert counts.get(cid, 0) > 0, 'Piano: cluster %d vuoto' % cid
        assert cc == 1, (
            'Piano piatto deve produrre un solo cluster, ottenuti %d' % cc
        )
    finally:
        _remove(obj, mesh)


def test_cluster_determinism():
    bpy.ops.mesh.primitive_uv_sphere_add(segments=16, ring_count=8, radius=1.0)
    obj = bpy.context.object
    mesh = obj.data
    try:
        analysis = module('mesh_analysis').MeshAnalyzer.analyze(mesh)
        assert analysis.ok, 'Analisi mesh della sfera fallita'

        fc1, cc1 = module('vsa').VSAClusterer.cluster(analysis)
        fc2, cc2 = module('vsa').VSAClusterer.cluster(analysis)
        assert cc1 == cc2, (
            'Determinismo: cluster_count diverso (%d vs %d)' % (cc1, cc2)
        )
        assert fc1 == fc2, 'Determinismo: partizione diversa tra due chiamate'
    finally:
        _remove(obj, mesh)


def test_blocked_edges_not_crossed():
    bpy.ops.mesh.primitive_grid_add(x_subdivisions=4, y_subdivisions=4, size=2.0)
    obj = bpy.context.object
    mesh = obj.data
    try:
        analysis = module('mesh_analysis').MeshAnalyzer.analyze(mesh)
        assert analysis.ok, 'Analisi mesh del piano fallita'

        face_count = analysis.face_count
        faces_per_edge = analysis.faces_per_edge

        # Invariante 1: bloccando alcuni edge interni, nessun cluster deve
        # reggersi su un edge bloccato: ogni cluster resta connesso usando
        # solo edge non bloccati.
        blocked = set()
        for eidx, face_list in enumerate(faces_per_edge):
            if len(face_list) == 2:
                blocked.add(eidx)
                if len(blocked) >= 5:
                    break
        assert blocked, 'Nessun edge interno da bloccare sul piano'

        fc, cc = module('vsa').VSAClusterer.cluster(
            analysis, blocked_edges=blocked
        )
        assert len(fc) == face_count, 'Piano bloccato: copertura facce'
        assert all(0 <= c < cc for c in fc), 'Piano bloccato: cluster id non valido'

        # Adjacency limitata agli edge non bloccati.
        adj = [[] for _ in range(face_count)]
        for eidx, face_list in enumerate(faces_per_edge):
            if len(face_list) != 2 or eidx in blocked:
                continue
            f1, f2 = face_list[0], face_list[1]
            if 0 <= f1 < face_count and 0 <= f2 < face_count:
                adj[f1].append(f2)
                adj[f2].append(f1)

        members_by_cluster = {}
        for fidx in range(face_count):
            members_by_cluster.setdefault(fc[fidx], []).append(fidx)
        for cid, members in members_by_cluster.items():
            seen = {members[0]}
            stack = [members[0]]
            while stack:
                cur = stack.pop()
                for nb in adj[cur]:
                    if fc[nb] == cid and nb not in seen:
                        seen.add(nb)
                        stack.append(nb)
            assert len(seen) == len(members), (
                'Cluster %d non connesso senza edge bloccati: '
                '%d di %d facce raggiunte' % (cid, len(seen), len(members))
            )

        # Invariante 2: taglio completo lungo una riga della griglia: blocca
        # tutti gli edge che attraversano quella riga e verifica che le facce
        # dei due lati finiscano in cluster diversi.
        face_centers = analysis.face_centers
        ys = sorted(set(round(float(c[1]), 6) for c in face_centers))
        assert len(ys) >= 2, 'Griglia: servono almeno due righe di facce'
        mid = len(ys) // 2
        threshold = (ys[mid - 1] + ys[mid]) / 2.0

        blocked2 = set()
        for eidx, face_list in enumerate(faces_per_edge):
            if len(face_list) != 2:
                continue
            f1, f2 = face_list[0], face_list[1]
            if not (0 <= f1 < face_count and 0 <= f2 < face_count):
                continue
            side1 = float(face_centers[f1][1]) < threshold
            side2 = float(face_centers[f2][1]) < threshold
            if side1 != side2:
                blocked2.add(eidx)
        assert blocked2, 'Nessun edge da bloccare per il taglio di riga'

        fc2, cc2 = module('vsa').VSAClusterer.cluster(
            analysis, blocked_edges=blocked2
        )
        assert len(fc2) == face_count, 'Taglio riga: copertura facce'
        assert cc2 >= 2, (
            'Taglio completo deve produrre almeno 2 cluster, ottenuti %d' % cc2
        )
        for cid in range(cc2):
            sides = set()
            for fidx in range(face_count):
                if fc2[fidx] == cid:
                    sides.add(float(face_centers[fidx][1]) < threshold)
            assert len(sides) <= 1, (
                'Cluster %d contiene facce di entrambi i lati del taglio' % cid
            )
    finally:
        _remove(obj, mesh)


def test_plan_seams_valid_edge_indices():
    bpy.ops.mesh.primitive_uv_sphere_add(segments=32, ring_count=16, radius=1.0)
    obj = bpy.context.object
    mesh = obj.data
    try:
        analysis = module('mesh_analysis').MeshAnalyzer.analyze(mesh)
        assert analysis.ok, 'Analisi mesh della sfera fallita'
        material = module('material_analysis').MaterialAnalyzer.analyze(obj, analysis)
        assert material.ok, 'Analisi materiali della sfera fallita'

        settings = bpy.context.scene.intelligent_uv_settings
        result = module('vsa').plan_seams(analysis, material, settings)
        assert result.ok, 'plan_seams fallito: %s' % repr(result.errors)

        edge_count = analysis.edge_count
        assert len(result.is_seam) == edge_count, (
            'is_seam ha lunghezza %d != edge_count %d'
            % (len(result.is_seam), edge_count)
        )
        assert all(0 <= i < edge_count for i in result.seam_edges), (
            'seam_edges contiene indici fuori range'
        )
        assert len(result.seam_edges) == sum(1 for flag in result.is_seam if flag), (
            'seam_edges non coerente con is_seam (duplicati o conteggio errato)'
        )
    finally:
        _remove(obj, mesh)


def test_plan_seams_determinism():
    bpy.ops.mesh.primitive_uv_sphere_add(segments=16, ring_count=8, radius=1.0)
    obj = bpy.context.object
    mesh = obj.data
    try:
        analysis = module('mesh_analysis').MeshAnalyzer.analyze(mesh)
        assert analysis.ok, 'Analisi mesh della sfera fallita'
        material = module('material_analysis').MaterialAnalyzer.analyze(obj, analysis)
        assert material.ok, 'Analisi materiali della sfera fallita'

        settings = bpy.context.scene.intelligent_uv_settings
        r1 = module('vsa').plan_seams(analysis, material, settings)
        r2 = module('vsa').plan_seams(analysis, material, settings)
        assert r1.ok and r2.ok, 'plan_seams fallito'
        assert r1.is_seam == r2.is_seam, 'plan_seams non deterministico su is_seam'
        assert r1.seam_edges == r2.seam_edges, (
            'plan_seams non deterministico su seam_edges'
        )
    finally:
        _remove(obj, mesh)


if __name__ == '__main__':
    passed = 0
    failed = 0
    tests = (
        test_cube_cluster_coverage_and_no_empty,
        test_cube_creases_separate_clusters,
        test_plane_single_cluster,
        test_cluster_determinism,
        test_blocked_edges_not_crossed,
        test_plan_seams_valid_edge_indices,
        test_plan_seams_determinism,
    )
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
