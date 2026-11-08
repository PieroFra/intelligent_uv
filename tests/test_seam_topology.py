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
import time
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


def uv_sphere(segments, rings):
    """Sfera UV chiusa: due poli, anelli interni e ventagli di triangoli ai poli."""
    vertices = [(0.0, 0.0, 1.0)]
    for r in range(1, rings):
        theta = math.pi * r / rings
        z = math.cos(theta)
        radius = math.sin(theta)
        for j in range(segments):
            phi = 2 * math.pi * j / segments
            vertices.append((radius * math.cos(phi), radius * math.sin(phi), z))
    south = len(vertices)
    vertices.append((0.0, 0.0, -1.0))

    def ring(r, j):
        return 1 + (r - 1) * segments + j % segments

    faces = []
    for j in range(segments):
        faces.append((0, ring(1, j), ring(1, j + 1)))
    for r in range(1, rings - 1):
        for j in range(segments):
            faces.append((ring(r, j), ring(r, j + 1),
                          ring(r + 1, j + 1), ring(r + 1, j)))
    for j in range(segments):
        faces.append((south, ring(rings - 1, j + 1), ring(rings - 1, j)))
    return make_mesh(vertices, faces)


def cap_ring_mask(mesh, segments, rings):
    """Solo gli anelli orizzontali adiacenti ai due poli, come seam virtuali."""
    north = {1 + j for j in range(segments)}
    south = {1 + (rings - 2) * segments + j for j in range(segments)}
    mask = [False] * len(mesh.edges)
    for edge in mesh.edges:
        pair = set(edge.vertices)
        if pair <= north or pair <= south:
            mask[edge.index] = True
    assert sum(mask) == 2 * segments, 'Anelli cap della sfera incompleti'
    return mask


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


def expect_completion_honest(mesh, mask):
    """Completamento deterministico che non inventa riparazioni.

    Ogni regione non disco rimasta deve comparire in unresolved_regions e
    nessun arco aggiunto puo' esistere gia' nella maschera di input.
    """
    output, added, unresolved = complete_preserving(mesh, mask)
    final = analyze_preserving(mesh, output)
    remaining = [region for region in final
                 if not (region.supported and region.is_disk)]
    assert {frozenset(region.face_indices) for region in remaining} == {
        frozenset(region.face_indices) for region in unresolved}, \
        'Regioni non disco non segnalate come irrisolte'
    assert all(not region.is_disk for region in unresolved), 'Regione irrisolta classificata come disco'
    for edge in added:
        assert not mask[edge], 'Arco aggiunto gia presente nella maschera'
    return output, added, unresolved


def test_single_triangle():
    mesh = make_mesh([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [(0, 1, 2)])
    try:
        mask = (False,) * len(mesh.edges)
        expect_single(mesh, mask, 1, 1, 0, True)
        output, added, unresolved = expect_completion_honest(mesh, mask)
        assert output == tuple(mask), 'Triangolo singolo: maschera modificata'
        assert added == (), 'Triangolo singolo: archi inventati'
        assert unresolved == (), 'Triangolo singolo: disco segnalato irrisolto'
    finally:
        bpy.data.meshes.remove(mesh)


def test_hole_with_ngon():
    # Anello quadrangolare con un bordo esterno a 5 vertici e una faccia pentagonale.
    mesh = make_mesh([(0, 0, 0), (2, 0, 0), (2, 2, 0), (0, 2, 0),
                      (0.75, 0.75, 0), (1.25, 0.75, 0), (1.25, 1.25, 0), (0.75, 1.25, 0),
                      (1, 0, 0)],
                     [(8, 1, 2, 6, 5), (0, 8, 5, 4), (2, 3, 7, 6), (3, 0, 4, 7)])
    try:
        mask = (False,) * len(mesh.edges)
        regions = analyze_preserving(mesh, mask)
        assert len(regions) == 1, 'Anello con n-gon deve formare una sola regione'
        region = regions[0]
        assert region.supported is True, 'Anello manifold con n-gon non supportato'
        assert region.boundary_count == 2, 'Anello con n-gon: numero di bordi errato'
        assert region.euler_characteristic == 0, 'Anello con n-gon: Eulero errato'
        assert region.genus == 0, 'Anello con n-gon: genere errato'
        assert region.is_disk is False, 'Anello con n-gon classificato come disco'
        output, added, unresolved = expect_completion_honest(mesh, mask)
        assert output != tuple(mask) or unresolved, 'Anello con n-gon non riparato e non segnalato'
        if not added:
            assert {frozenset(r.face_indices) for r in unresolved} == {
                frozenset(region.face_indices)}, 'Anello non riparato senza segnalazione coerente'
        else:
            final = analyze_preserving(mesh, output)
            assert all(r.supported and r.is_disk for r in final), 'Riparazione anello produce regioni non disco'
    finally:
        bpy.data.meshes.remove(mesh)


def test_all_edges_marked_seam():
    mesh = make_mesh([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)],
                     [(0, 1, 2), (0, 2, 3)])
    try:
        mask = (True,) * len(mesh.edges)
        regions = analyze_preserving(mesh, mask)
        assert len(regions) == 2, 'Tutte le seam devono separare le due facce'
        assert {frozenset(r.face_indices) for r in regions} == {
            frozenset((0,)), frozenset((1,))}, 'Partizione con tutte le seam errata'
        for region in regions:
            assert region.supported is True, 'Faccia isolata da seam non supportata'
            assert region.is_disk is True, 'Faccia isolata da seam non e un disco'
            assert region.boundary_count == 1, 'Faccia isolata con bordi errati'
        output, added, unresolved = expect_completion_honest(mesh, mask)
        assert output == tuple(mask), 'Tutte le seam: maschera di input modificata'
        assert added == (), 'Tutte le seam: archi aggiunti inutilmente'
        assert unresolved == (), 'Tutte le seam: dischi segnalati irrisolti'
    finally:
        bpy.data.meshes.remove(mesh)


def test_duplicate_unfused_vertices():
    # Due triangoli sovrapposti con coordinate identiche ma vertici non fusi.
    mesh = make_mesh([(0, 0, 0), (1, 0, 0), (0, 1, 0),
                      (0, 0, 0), (1, 0, 0), (0, 1, 0)],
                     [(0, 1, 2), (3, 4, 5)])
    try:
        mask = (False,) * len(mesh.edges)
        regions = analyze_preserving(mesh, mask)
        assert len(regions) == 2, 'Vertici duplicati non fusi devono restare due regioni'
        for region in regions:
            assert region.supported is True, 'Triangolo duplicato non supportato'
            assert region.is_disk is True, 'Triangolo duplicato non classificato come disco'
            assert region.euler_characteristic == 1, 'Triangolo duplicato con Eulero errato'
        output, added, unresolved = expect_completion_honest(mesh, mask)
        assert added == (), 'Vertici duplicati non fusi: riparazione inventata'
        assert unresolved == (), 'Vertici duplicati non fusi: dischi segnalati irrisolti'
    finally:
        bpy.data.meshes.remove(mesh)


def test_analyze_wrong_mask_length():
    mesh = annulus()
    try:
        analyze = analyzer()
        module = importlib.import_module(PACKAGE + '.seam_topology')
        complete = getattr(module, 'complete_boundary_cuts', None)
        assert callable(complete), 'complete_boundary_cuts obbligatoria assente'
        before_mesh = snapshot(mesh)
        for size in (len(mesh.edges) - 1, len(mesh.edges) + 1):
            for mask in ([False] * size, [True] * size):
                before_mask = tuple(mask)
                for function in (analyze, complete):
                    try:
                        function(mesh, mask)
                    except ValueError:
                        pass
                    else:
                        raise AssertionError('Lunghezza maschera errata deve sollevare ValueError')
                assert tuple(mask) == before_mask, 'Errore dimensione modifica la maschera di input'
                assert snapshot(mesh) == before_mesh, 'Errore dimensione modifica la mesh'
    finally:
        bpy.data.meshes.remove(mesh)


def test_repeat_same_input_deterministic():
    mesh = annulus()
    try:
        mask = [False] * len(mesh.edges)
        first = analyze_preserving(mesh, mask)
        second = analyze_preserving(mesh, mask)
        assert region_signature(first) == region_signature(second), 'Analisi non deterministica a input identico'
        output, added, unresolved = complete_preserving(mesh, mask)
        output_again, added_again, unresolved_again = complete_preserving(mesh, list(output))
        assert output_again == output, 'Completamento non idempotente sulla maschera di output'
        assert added_again == (), 'Completamento ripetuto aggiunge altri archi'
        assert region_signature(unresolved_again) == region_signature(unresolved), 'Regioni irrisolte non stabili'
        assert region_signature(analyze_preserving(mesh, output)) == region_signature(
            analyze_preserving(mesh, list(output))), 'Analisi non deterministica sulla maschera di output'
    finally:
        bpy.data.meshes.remove(mesh)


def test_disconnected_non_manifold_island():
    # Un disco isolato piu' un'isola con un arco condiviso da tre facce.
    mesh = make_mesh([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0),
                      (5, 0, 0), (6, 0, 0), (5, 1, 0), (5, -1, 0), (5, 0, 1)],
                     [(0, 1, 2), (0, 2, 3), (4, 5, 6), (5, 4, 7), (4, 5, 8)])
    try:
        mask = (False,) * len(mesh.edges)
        regions = analyze_preserving(mesh, mask)
        assert len(regions) == 2, 'Isole disconnesse devono formare due regioni'
        supported = [r for r in regions if r.supported]
        unsupported = [r for r in regions if not r.supported]
        assert len(supported) == 1 and len(unsupported) == 1, 'Isola non manifold non riconosciuta'
        disk = supported[0]
        assert frozenset(disk.face_indices) == frozenset((0, 1)), 'Isola disco con facce errate'
        assert disk.is_disk is True and disk.boundary_count == 1 and disk.genus == 0, \
            'Isola disco con topologia errata'
        broken = unsupported[0]
        assert frozenset(broken.face_indices) == frozenset((2, 3, 4)), 'Isola non manifold con facce errate'
        assert broken.is_disk is False and broken.genus is None, 'Isola non manifold classificata come disco'
        output, added, unresolved = expect_completion_honest(mesh, mask)
        assert added == (), 'Isola non manifold: riparazione inventata'
        assert {frozenset(r.face_indices) for r in unresolved} == {
            frozenset(broken.face_indices)}, 'Isola non manifold non segnalata irrisolta'
        assert output == tuple(mask), 'Isola non manifold: maschera modificata'
    finally:
        bpy.data.meshes.remove(mesh)


TIMINGS = {}


def test_large_sphere_cap_seams_performance():
    """Sfera UV 64x32 per emisfero: i due anelli cap forzano il cammino tra bordi.

    I tempi finiscono in TIMINGS e in una riga REPORT, cosi' restano leggibili
    senza soglie nascoste. La mesh e' chiusa e manifold: 64 meridiani per 64
    anelli totali (32 per emisfero), cioe' 4096 facce.
    """
    mesh = uv_sphere(64, 64)
    try:
        assert len(mesh.polygons) == 4096, 'Fixture sfera con numero di facce errato'
        mask = cap_ring_mask(mesh, 64, 64)
        before = snapshot(mesh)
        saved_mask = tuple(mask)
        analyze = analyzer()
        start = time.perf_counter()
        regions = list(analyze(mesh, mask))
        analyze_seconds = time.perf_counter() - start
        assert snapshot(mesh) == before, 'Analisi della sfera modifica mesh, seam reali o UV'
        assert tuple(mask) == saved_mask, 'Analisi della sfera modifica la maschera virtuale'
        assert len(regions) == 3, 'Sfera con due cap tagliati deve avere tre regioni'
        assert sorted(r.is_disk for r in regions) == [False, True, True], \
            'Cap non dischi oppure banda centrale gia disco'
        indices = sorted(i for region in regions for i in region.face_indices)
        assert indices == list(range(len(mesh.polygons))), 'Partizione delle facce incompleta'

        module = importlib.import_module(PACKAGE + '.seam_topology')
        complete = getattr(module, 'complete_boundary_cuts', None)
        assert callable(complete), 'complete_boundary_cuts obbligatoria assente'
        start = time.perf_counter()
        result = complete(mesh, mask)
        complete_seconds = time.perf_counter() - start
        assert snapshot(mesh) == before, 'Completamento della sfera modifica mesh, seam reali o UV'
        assert tuple(mask) == saved_mask, 'Completamento della sfera modifica la maschera di input'
        output = tuple(result.seam_mask)
        assert len(output) == len(saved_mask), 'Maschera di output della sfera con dimensione errata'
        assert bool(result.added_edges), 'Banda anulare chiusa senza cammino aggiunto'
        assert not result.unresolved_regions, 'Sfera risolvibile lasciata irrisolta'
        final = analyze_preserving(mesh, output)
        assert final and all(r.supported and r.is_disk for r in final), \
            'Sfera completata con regioni non disco'

        # Guardia anti-regressione, non promessa di prestazioni: 2 secondi sono
        # un ordine di grandezza sopra il valore atteso e servono solo a notare
        # se il cammino tra i bordi degenera in quadratico o peggio.
        assert complete_seconds < 2.0, 'Completamento della sfera oltre la guardia di 2 secondi'

        TIMINGS['test_large_sphere_cap_seams_performance'] = {
            'faces': len(mesh.polygons),
            'edges': len(mesh.edges),
            'analyze_s': analyze_seconds,
            'complete_s': complete_seconds,
        }
        print('REPORT sfera faces={faces} edges={edges} analyze={analyze_s:.4f}s '
              'complete={complete_s:.4f}s'.format(
                  **TIMINGS['test_large_sphere_cap_seams_performance']))
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
             test_analysis_inconsistent_data_unrepaired, test_analysis_wrong_mask_length,
             test_single_triangle, test_hole_with_ngon, test_all_edges_marked_seam,
             test_duplicate_unfused_vertices, test_analyze_wrong_mask_length,
             test_repeat_same_input_deterministic, test_disconnected_non_manifold_island,
             test_large_sphere_cap_seams_performance)
    passed = failed = 0
    for test in tests:
        try:
            test()
            passed += 1
        except Exception:
            failed += 1
            traceback.print_exc()
    print(f'RISULTATO passati={passed} falliti={failed} totale={len(tests)}')
