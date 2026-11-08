# -*- coding: utf-8 -*-
"""Contratto topologico delle regioni sulla superficie virtualmente tagliata.

analyze_regions(mesh, seam_mask) restituisce una sequenza di regioni con
attributi face_indices, boundary_count, euler_characteristic, genus,
is_disk e supported. Le facce conservano gli indici della mesh originale.
"""

import importlib
import copy
import math
import os
import sys
import traceback

import bpy
from mathutils import Matrix

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(ROOT))
PACKAGE = os.path.basename(ROOT)


def analyzer():
    try:
        module = importlib.import_module(PACKAGE + '.seam_topology')
    except ModuleNotFoundError as exc:
        raise AssertionError('Modulo seam_topology obbligatorio assente') from exc
    assert callable(getattr(module, 'analyze_regions', None)), 'analyze_regions assente'
    return module.analyze_regions


def make_mesh(vertices, faces):
    mesh = bpy.data.meshes.new('SeamTopologyFixture')
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    # I flag reali sono deliberatamente diversi dalla maschera virtuale.
    for edge in mesh.edges:
        edge.use_seam = edge.index % 2 == 0
    layer = mesh.uv_layers.new(name='PreserveUV')
    for i, item in enumerate(layer.data):
        item.uv = (i / 17.0, i / 23.0)
    return mesh


def snapshot(mesh):
    return (tuple(tuple(v.co) for v in mesh.vertices),
            tuple((tuple(e.vertices), e.use_seam) for e in mesh.edges),
            tuple((tuple(p.vertices), p.material_index) for p in mesh.polygons),
            tuple((loop.vertex_index, loop.edge_index) for loop in mesh.loops),
            tuple((layer.name, tuple(tuple(item.uv) for item in layer.data))
                  for layer in mesh.uv_layers))


def annulus():
    n = 8
    vertices = [(r * math.cos(2 * math.pi * i / n),
                 r * math.sin(2 * math.pi * i / n), 0)
                for r in (1.0, 2.0) for i in range(n)]
    faces = [(i, n + i, n + (i + 1) % n, (i + 1) % n)
             for i in range(n)]
    return make_mesh(vertices, faces)


def torus():
    n, m = 8, 6
    vertices = []
    for i in range(n):
        u = 2 * math.pi * i / n
        for j in range(m):
            v = 2 * math.pi * j / m
            vertices.append(((3 + math.cos(v)) * math.cos(u),
                             (3 + math.cos(v)) * math.sin(u), math.sin(v)))
    faces = [(i * m + j, ((i + 1) % n) * m + j,
              ((i + 1) % n) * m + (j + 1) % m, i * m + (j + 1) % m)
             for i in range(n) for j in range(m)]
    return make_mesh(vertices, faces)


def radial_mask(mesh):
    matches = [e.index for e in mesh.edges if set(e.vertices) == {0, 8}]
    assert len(matches) == 1, 'Seam radiale della fixture assente o duplicata'
    return tuple(e.index == matches[0] for e in mesh.edges)


def analyze_preserving(mesh, mask):
    before = snapshot(mesh)
    saved_mask = tuple(mask)
    regions = list(analyzer()(mesh, mask))
    assert snapshot(mesh) == before, 'Analisi modifica mesh, seam reali o UV'
    assert tuple(mask) == saved_mask, 'Analisi modifica la maschera virtuale'
    indices = [i for region in regions for i in region.face_indices]
    assert sorted(indices) == list(range(len(mesh.polygons))), 'Partizione delle facce incompleta o duplicata'
    return regions


def expect_single(mesh, mask, boundary, chi, genus, disk):
    regions = analyze_preserving(mesh, mask)
    assert len(regions) == 1, 'Numero di regioni inatteso'
    region = regions[0]
    assert set(region.face_indices) == set(range(len(mesh.polygons))), 'Indici delle facce inattesi'
    assert region.supported is True, 'Superficie manifold non supportata'
    assert region.boundary_count == boundary, 'Numero di componenti di bordo errato'
    assert region.euler_characteristic == chi, 'Caratteristica di Eulero errata'
    assert region.genus == genus, 'Genere errato'
    assert region.is_disk is disk, 'Classificazione disco errata'
    return regions


def test_open_disk():
    mesh = make_mesh([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)],
                     [(0, 1, 2), (0, 2, 3)])
    try:
        expect_single(mesh, (False,) * len(mesh.edges), 1, 1, 0, True)
    finally:
        bpy.data.meshes.remove(mesh)


def test_two_separate_disks():
    mesh = make_mesh([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0),
                      (3, 0, 0), (4, 0, 0), (4, 1, 0), (3, 1, 0)],
                     [(0, 1, 2), (0, 2, 3), (4, 5, 6), (4, 6, 7)])
    try:
        regions = analyze_preserving(mesh, (False,) * len(mesh.edges))
        assert len(regions) == 2, 'Due dischi separati devono produrre due regioni'
        assert {frozenset(r.face_indices) for r in regions} == {
            frozenset((0, 1)), frozenset((2, 3))}, 'Partizione dei due dischi errata'
        for region in regions:
            assert region.supported is True, 'Disco separato non supportato'
            assert region.euler_characteristic == 1, 'Eulero deve usare le facce della singola regione'
            assert region.boundary_count == 1, 'Disco separato con numero di bordi errato'
            assert region.genus == 0, 'Disco separato con genere errato'
            assert region.is_disk is True, 'Disco separato non classificato come disco'
    finally:
        bpy.data.meshes.remove(mesh)


def test_disk_with_loose_vertices():
    mesh = make_mesh([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0),
                      (3, 0, 0), (4, 2, 1), (-2, 0, 3)],
                     [(0, 1, 2), (0, 2, 3)])
    try:
        regions = expect_single(mesh, (False,) * len(mesh.edges), 1, 1, 0, True)
        assert set(regions[0].face_indices) == {0, 1}, 'Vertici sciolti alterano la regione di facce'
    finally:
        bpy.data.meshes.remove(mesh)


def test_annulus():
    mesh = annulus()
    try:
        expect_single(mesh, (False,) * len(mesh.edges), 2, 0, 0, False)
    finally:
        bpy.data.meshes.remove(mesh)


def test_annulus_radial_seam():
    mesh = annulus()
    try:
        expect_single(mesh, radial_mask(mesh), 1, 1, 0, True)
    finally:
        bpy.data.meshes.remove(mesh)


def test_torus():
    mesh = torus()
    try:
        expect_single(mesh, (False,) * len(mesh.edges), 0, 0, 1, False)
    finally:
        bpy.data.meshes.remove(mesh)


def test_non_manifold():
    mesh = make_mesh([(0, 0, 0), (1, 0, 0), (0, 1, 0),
                      (0, -1, 0), (0, 0, 1)],
                     [(0, 1, 2), (1, 0, 3), (0, 1, 4)])
    try:
        regions = analyze_preserving(mesh, (False,) * len(mesh.edges))
        assert regions, 'Nessuna regione per la mesh non-manifold'
        assert all(r.supported is False for r in regions), 'Arco con tre facce erroneamente supportato'
        assert all(r.is_disk is False for r in regions), 'Regione non-manifold classificata come disco'
    finally:
        bpy.data.meshes.remove(mesh)


def test_rotation_and_preservation():
    for factory, cut, expected in ((annulus, False, (2, 0, 0, False)),
                                   (annulus, True, (1, 1, 0, True)),
                                   (torus, False, (0, 0, 1, False))):
        mesh = factory()
        try:
            mask = radial_mask(mesh) if cut else (False,) * len(mesh.edges)
            original = expect_single(mesh, mask, *expected)
            original_faces = tuple(sorted(original[0].face_indices))
            rotation = Matrix.Rotation(0.731, 4, 'X') @ Matrix.Rotation(1.127, 4, 'Z')
            mesh.transform(rotation)
            mesh.update()
            rotated = expect_single(mesh, mask, *expected)
            assert tuple(sorted(rotated[0].face_indices)) == original_faces, 'Rotazione cambia la partizione'
        finally:
            bpy.data.meshes.remove(mesh)


def complete_preserving(mesh, mask):
    module = importlib.import_module(PACKAGE + '.seam_topology')
    complete = getattr(module, 'complete_boundary_cuts', None)
    assert callable(complete), 'complete_boundary_cuts obbligatoria assente'
    before = snapshot(mesh)
    saved_mask = tuple(mask)
    signatures = []
    results = []
    for _ in range(2):
        result = complete(mesh, mask)
        assert snapshot(mesh) == before, 'Completamento modifica mesh, seam reali o UV'
        assert tuple(mask) == saved_mask, 'Completamento modifica la maschera di input'
        output = tuple(result.seam_mask)
        added = tuple(result.added_edges)
        unresolved = tuple(result.unresolved_regions)
        assert len(output) == len(saved_mask), 'Dimensione maschera di output errata'
        assert all(isinstance(value, bool) for value in output), 'Maschera di output non booleana'
        assert all(not old or new for old, new in zip(saved_mask, output)), 'Seam originali rimosse'
        expected_added = {i for i, (old, new) in enumerate(zip(saved_mask, output)) if new and not old}
        assert len(added) == len(set(added)), 'Archi aggiunti duplicati'
        assert set(added) == expected_added, 'Archi aggiunti non corrispondono alla maschera'
        signatures.append((output, added,
                           tuple(tuple(sorted(r.face_indices)) for r in unresolved)))
        results.append((output, added, unresolved))
    assert signatures[0] == signatures[1], 'Completamento non deterministico a input identico'
    return results[0]


def expect_completed_disks(mesh, mask, needs_cut):
    output, added, unresolved = complete_preserving(mesh, mask)
    assert bool(added) is needs_cut, 'Presenza di nuovi tagli inattesa'
    assert not unresolved, 'Regioni risolvibili lasciate irrisolte'
    regions = analyze_preserving(mesh, output)
    assert regions, 'Completamento senza regioni finali'
    assert all(r.supported is True and r.is_disk is True
               and r.genus == 0 and r.boundary_count == 1
               and r.euler_characteristic == 1 for r in regions), 'Regioni finali non disco'


def test_complete_annulus():
    mesh = annulus()
    try:
        mask = [False] * len(mesh.edges)
        expect_single(mesh, mask, 2, 0, 0, False)
        expect_completed_disks(mesh, mask, True)
    finally:
        bpy.data.meshes.remove(mesh)


def test_complete_open_disk():
    mesh = make_mesh([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)],
                     [(0, 1, 2), (0, 2, 3)])
    try:
        mask = [False] * len(mesh.edges)
        expect_single(mesh, mask, 1, 1, 0, True)
        expect_completed_disks(mesh, mask, False)
    finally:
        bpy.data.meshes.remove(mesh)


def test_complete_preserves_original_seams():
    mesh = annulus()
    try:
        mask = list(radial_mask(mesh))
        expect_completed_disks(mesh, mask, False)
        output, added, unresolved = complete_preserving(mesh, mask)
        assert output == tuple(mask), 'Disco già tagliato deve conservare esattamente le seam'
    finally:
        bpy.data.meshes.remove(mesh)


def test_complete_rotated_deformed_annulus():
    mesh = annulus()
    try:
        for vertex in mesh.vertices:
            x, y, z = vertex.co
            vertex.co = (1.7 * x, 0.6 * y, 0.23 * x * y)
        mesh.transform(Matrix.Rotation(0.731, 4, 'X') @ Matrix.Rotation(1.127, 4, 'Z'))
        mesh.update()
        mask = [False] * len(mesh.edges)
        expect_single(mesh, mask, 2, 0, 0, False)
        expect_completed_disks(mesh, mask, True)
    finally:
        bpy.data.meshes.remove(mesh)


def expect_unrepaired(mesh, mask):
    original = analyze_preserving(mesh, mask)
    output, added, unresolved = complete_preserving(mesh, mask)
    assert output == tuple(mask), 'Regione non riparabile: maschera modificata'
    assert not added, 'Regione non riparabile: archi aggiunti'
    assert unresolved, 'Regione non riparabile non segnalata'
    assert {frozenset(r.face_indices) for r in unresolved} == {
        frozenset(r.face_indices) for r in original}, 'Regioni irrisolte non corrispondono alle originali'
    final = analyze_preserving(mesh, output)
    assert all(r.is_disk is False for r in final), 'Regione non riparabile diventata disco'


def test_complete_torus_unresolved():
    mesh = torus()
    try:
        mask = [False] * len(mesh.edges)
        expect_single(mesh, mask, 0, 0, 1, False)
        expect_unrepaired(mesh, mask)
    finally:
        bpy.data.meshes.remove(mesh)


def test_complete_non_manifold_unresolved():
    mesh = make_mesh([(0, 0, 0), (1, 0, 0), (0, 1, 0),
                      (0, -1, 0), (0, 0, 1)],
                     [(0, 1, 2), (1, 0, 3), (0, 1, 4)])
    try:
        mask = [False] * len(mesh.edges)
        regions = analyze_preserving(mesh, mask)
        assert regions and all(r.supported is False for r in regions), 'Fixture non-manifold errata'
        expect_unrepaired(mesh, mask)
    finally:
        bpy.data.meshes.remove(mesh)


def analysis_api(mesh):
    module = importlib.import_module(PACKAGE + '.mesh_analysis')
    analysis = module.MeshAnalyzer.analyze(mesh)
    assert analysis.ok, 'Analisi della fixture valida fallita'
    topology = importlib.import_module(PACKAGE + '.seam_topology')
    complete = getattr(topology, 'complete_analysis_boundary_cuts', None)
    assert callable(complete), 'complete_analysis_boundary_cuts obbligatoria assente'
    return analysis, complete


def analysis_snapshot(analysis):
    # Include anche gli array numpy senza confronti booleani ambigui.
    return copy.deepcopy({key: value.tolist() if hasattr(value, 'tolist') else value
                          for key, value in vars(analysis).items()})


def region_signature(regions):
    return tuple((tuple(r.face_indices), r.boundary_count,
                  r.euler_characteristic, r.genus, r.is_disk, r.supported)
                 for r in regions)


def expect_analysis_equivalent(mesh, mask, needs_cut, unresolved_count):
    before_mesh = snapshot(mesh)
    analysis, complete = analysis_api(mesh)
    before_analysis = analysis_snapshot(analysis)
    before_mask = tuple(mask)
    output, added, unresolved = complete_preserving(mesh, mask)
    for _ in range(2):
        result = complete(analysis, mask)
        assert tuple(result.seam_mask) == output, 'API analisi: maschera diversa dalla API Mesh'
        assert tuple(result.added_edges) == added, 'API analisi: archi aggiunti diversi dalla API Mesh'
        assert region_signature(result.unresolved_regions) == region_signature(unresolved), 'API analisi: topologia irrisolta diversa dalla API Mesh'
        assert len(result.unresolved_regions) == unresolved_count, 'API analisi: numero di regioni irrisolte errato'
        assert bool(result.added_edges) is needs_cut, 'API analisi: presenza di tagli errata'
        assert analysis_snapshot(analysis) == before_analysis, 'API analisi modifica i dati di input'
        assert snapshot(mesh) == before_mesh, 'API analisi modifica mesh, seam reali o UV'
        assert tuple(mask) == before_mask, 'API analisi modifica la maschera di input'
    if unresolved_count:
        assert output == before_mask and not added, 'Torus irrisolto modificato'
        assert all(r.supported and not r.is_disk and r.genus == 1
                   for r in unresolved), 'Torus irrisolto con topologia errata'
    else:
        regions = analyze_preserving(mesh, output)
        assert regions and all(r.supported and r.is_disk for r in regions), 'API analisi non produce dischi'


def test_analysis_complete_annulus_equivalence():
    mesh = annulus()
    try:
        expect_analysis_equivalent(mesh, [False] * len(mesh.edges), True, 0)
        expect_analysis_equivalent(mesh, list(radial_mask(mesh)), False, 0)
    finally:
        bpy.data.meshes.remove(mesh)


def test_analysis_complete_disk_equivalence():
    mesh = make_mesh([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)],
                     [(0, 1, 2), (0, 2, 3)])
    try:
        expect_analysis_equivalent(mesh, [False] * len(mesh.edges), False, 0)
    finally:
        bpy.data.meshes.remove(mesh)


def test_analysis_complete_torus_equivalence():
    mesh = torus()
    try:
        expect_analysis_equivalent(mesh, [False] * len(mesh.edges), False, 1)
    finally:
        bpy.data.meshes.remove(mesh)


def test_analysis_inconsistent_data_unrepaired():
    mesh = annulus()
    try:
        original, complete = analysis_api(mesh)
        before_mesh = snapshot(mesh)
        for defect in ('positions', 'face_edges', 'incidence'):
            analysis = copy.deepcopy(original)
            if defect == 'positions':
                analysis.vertex_positions = analysis.vertex_positions[:-1]
            elif defect == 'face_edges':
                analysis.edges_per_face[0] = analysis.edges_per_face[0][:-1]
            else:
                analysis.faces_per_edge[0] = []
            before_analysis = analysis_snapshot(analysis)
            mask = list(radial_mask(mesh))
            before_mask = tuple(mask)
            result = complete(analysis, mask)
            assert tuple(result.seam_mask) == before_mask, 'Dati incoerenti: maschera modificata'
            assert tuple(result.added_edges) == (), 'Dati incoerenti: archi aggiunti'
            assert region_signature(result.unresolved_regions) == (
                (tuple(range(analysis.face_count)), 0, 0, None, False, False),
            ), 'Dati incoerenti: regione non supportata incompleta o errata'
            assert analysis_snapshot(analysis) == before_analysis, 'Dati incoerenti riparati in input'
            assert tuple(mask) == before_mask, 'Dati incoerenti: maschera di input modificata'
            assert snapshot(mesh) == before_mesh, 'Dati incoerenti: mesh modificata'
    finally:
        bpy.data.meshes.remove(mesh)


def test_analysis_wrong_mask_length():
    mesh = annulus()
    try:
        analysis, complete = analysis_api(mesh)
        before_analysis = analysis_snapshot(analysis)
        before_mesh = snapshot(mesh)
        for size in (analysis.edge_count - 1, analysis.edge_count + 1):
            mask = [False] * size
            before_mask = tuple(mask)
            try:
                complete(analysis, mask)
            except ValueError:
                pass
            else:
                raise AssertionError('Lunghezza maschera errata deve sollevare ValueError')
            assert tuple(mask) == before_mask, 'Errore dimensione modifica la maschera'
            assert analysis_snapshot(analysis) == before_analysis, 'Errore dimensione modifica i dati analisi'
            assert snapshot(mesh) == before_mesh, 'Errore dimensione modifica la mesh'
    finally:
        bpy.data.meshes.remove(mesh)


if __name__ == '__main__':
    tests = (test_open_disk, test_two_separate_disks, test_disk_with_loose_vertices,
             test_annulus, test_annulus_radial_seam,
             test_torus, test_non_manifold, test_rotation_and_preservation,
             test_complete_annulus, test_complete_open_disk,
             test_complete_preserves_original_seams, test_complete_rotated_deformed_annulus,
             test_complete_torus_unresolved, test_complete_non_manifold_unresolved,
             test_analysis_complete_annulus_equivalence,
             test_analysis_complete_disk_equivalence,
             test_analysis_complete_torus_equivalence,
             test_analysis_inconsistent_data_unrepaired, test_analysis_wrong_mask_length)
    passed = failed = 0
    for test in tests:
        try:
            test()
            passed += 1
        except Exception:
            failed += 1
            traceback.print_exc()
    print(f'RISULTATO passati={passed} falliti={failed} totale={len(tests)}')
