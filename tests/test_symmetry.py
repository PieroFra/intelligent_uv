# -*- coding: utf-8 -*-
"""Contratto di rilevamento e applicazione della simmetria.

Un cilindro a 16 lati e' simmetrico su due assi e deve produrre una copertura
alta; una mesh asimmetrica costruita nel test non deve produrre alcun asse
credibile. apply non deve rimuovere seam gia' presenti nella maschera e deve
aggiungere solo indici di edge nel range della maschera; due chiamate identiche
devono dare lo stesso risultato.
"""

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


def module(name):
    return importlib.import_module(PACKAGE + '.' + name)


def make_cylinder(sides=16):
    vertices = []
    for i in range(sides):
        angle = 2.0 * math.pi * i / sides
        vertices.append((math.cos(angle), math.sin(angle), 0.0))
    for i in range(sides):
        angle = 2.0 * math.pi * i / sides
        vertices.append((math.cos(angle), math.sin(angle), 1.0))
    faces = []
    for i in range(sides):
        j = (i + 1) % sides
        faces.append((i, j, sides + j, sides + i))
    mesh = bpy.data.meshes.new('SymmetryCylinderFixture')
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    return mesh


def make_asymmetric():
    # Prisma a sezione L con gambe di lunghezza diversa: nessun asse di
    # simmetria. Le coordinate restano tutte non negative, quindi lo specchio
    # rispetto all'origine non trova alcuna coppia di facce.
    cross = [(0.0, 0.0), (3.0, 0.0), (3.0, 1.0),
             (1.0, 1.0), (1.0, 2.0), (0.0, 2.0)]
    n = len(cross)
    vertices = [(x, y, 0.0) for x, y in cross] + [(x, y, 1.0) for x, y in cross]
    # Spezza anche la simmetria lungo Z perturbando un vertice del cappello.
    vertices[n + 0] = (vertices[n + 0][0], vertices[n + 0][1], 1.3)
    faces = []
    faces.append(tuple(range(n)))
    faces.append(tuple(n + i for i in range(n - 1, -1, -1)))
    for i in range(n):
        j = (i + 1) % n
        faces.append((i, j, n + j, n + i))
    mesh = bpy.data.meshes.new('SymmetryAsymmetricFixture')
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    return mesh


def test_symmetry():
    symmetry = module('symmetry')
    mesh_analysis = module('mesh_analysis')
    MeshAnalyzer = mesh_analysis.MeshAnalyzer

    # --- Cilindro a 16 lati: asse con copertura alta ---
    mesh = make_cylinder()
    try:
        analysis = MeshAnalyzer.analyze(mesh)
        assert analysis.ok, 'Analisi del cilindro fallita'
        axis, coverage, face_mirror = symmetry.detect_symmetry(analysis)
        assert axis in (0, 1, 2), 'Cilindro: nessun asse di simmetria trovato'
        assert coverage >= 0.8, 'Cilindro: copertura dell asse troppo bassa'
        assert face_mirror, 'Cilindro: nessuna faccia accoppiata'

        # Maschera con seam solo sul semispazio positivo dell'asse trovato.
        initial_mask = [False] * len(mesh.edges)
        for eidx, face_list in enumerate(analysis.faces_per_edge):
            if not face_list:
                continue
            center = analysis.face_centers[face_list[0]]
            if center[axis] > 0.0:
                initial_mask[eidx] = True
        assert any(initial_mask), 'Cilindro: nessun edge sul semispazio positivo'

        settings = SimpleNamespace(symmetry_min_coverage=0.8)

        def run():
            fresh_analysis = MeshAnalyzer.analyze(mesh)
            assert fresh_analysis.ok, 'Rianalisi del cilindro fallita'
            mask = list(initial_mask)
            result = symmetry.apply(fresh_analysis, mask, settings, report=None)
            return mask, result

        mask_first, result_first = run()
        mask_second, result_second = run()

        assert mask_first == mask_second, 'apply non deterministico sulla maschera'
        assert result_first.found == result_second.found, 'apply non deterministico su found'
        assert result_first.axis == result_second.axis, 'apply non deterministico su axis'
        assert result_first.coverage == result_second.coverage, 'apply non deterministico su coverage'
        assert result_first.seams_added == result_second.seams_added, 'apply non deterministico su seams_added'
        assert result_first.seams_removed == result_second.seams_removed, 'apply non deterministico su seams_removed'

        # Nessuna seam esistente viene rimossa.
        removed = [i for i, (before, after) in enumerate(zip(initial_mask, mask_first))
                   if before and not after]
        assert not removed, 'apply ha rimosso seam esistenti'
        assert result_first.seams_removed == 0, 'apply ha rimosso seam esistenti'

        # Vengono aggiunti solo indici di edge nel range della maschera.
        added = [i for i, (before, after) in enumerate(zip(initial_mask, mask_first))
                 if after and not before]
        assert all(0 <= i < len(initial_mask) for i in added), 'apply ha aggiunto edge fuori range'
        assert result_first.seams_added == len(added), 'Conteggio delle seam aggiunte incoerente'
        assert result_first.seams_added > 0, 'apply non ha aggiunto alcuna seam'
    finally:
        bpy.data.meshes.remove(mesh)

    # --- Mesh asimmetrica: nessun asse credibile ---
    mesh = make_asymmetric()
    try:
        analysis = MeshAnalyzer.analyze(mesh)
        assert analysis.ok, 'Analisi della mesh asimmetrica fallita'
        axis, coverage, face_mirror = symmetry.detect_symmetry(analysis)
        assert axis == -1, 'Mesh asimmetrica: asse di simmetria spurio trovato'
    finally:
        bpy.data.meshes.remove(mesh)


if __name__ == '__main__':
    tests = (test_symmetry,)
    passed = failed = 0
    for test in tests:
        try:
            test()
            passed += 1
        except Exception:
            failed += 1
            traceback.print_exc()
    print(f'RISULTATO passati={passed} falliti={failed} totale={len(tests)}')
