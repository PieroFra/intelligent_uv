# -*- coding: utf-8 -*-
"""Contratto di auto_params.derive su mesh finte (duck-typed).

derive(mesh_analysis, margin_result, settings) legge solo faces_per_edge,
face_normals, face_count e, dal margine, margin_uv. Qui si passano oggetti
minimi che espongono esattamente questi campi.
"""

import importlib
import math
import os
import sys
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(ROOT))
PACKAGE = os.path.basename(ROOT)


def auto_params():
    try:
        module = importlib.import_module(PACKAGE + '.auto_params')
    except ModuleNotFoundError as exc:
        raise AssertionError('Modulo auto_params obbligatorio assente') from exc
    assert callable(getattr(module, 'derive', None)), 'derive assente'
    assert getattr(module, 'CREASE_ANGLE', None) == 30.0, 'CREASE_ANGLE inatteso'
    return module


class FakeMeshAnalysis:
    def __init__(self, faces_per_edge, face_normals, face_count, edge_count):
        self.faces_per_edge = faces_per_edge
        self.face_normals = face_normals
        self.face_count = face_count
        self.edge_count = edge_count


class FakeMarginResult:
    def __init__(self, margin_uv):
        self.margin_uv = margin_uv


def mesh_from_angles(angles, face_count=None):
    """Ogni angolo diventa un bordo manifold tra due facce con quella normale."""
    faces_per_edge = []
    face_normals = []
    for index, angle in enumerate(angles):
        radians = math.radians(float(angle))
        face_normals.append((0.0, 0.0, 1.0))
        face_normals.append((math.sin(radians), 0.0, math.cos(radians)))
        faces_per_edge.append([2 * index, 2 * index + 1])
    if face_count is None:
        face_count = 2 * len(angles)
    return FakeMeshAnalysis(faces_per_edge, face_normals, face_count, len(angles))


def empty_mesh(face_count=100):
    return FakeMeshAnalysis([], [], face_count, 0)


def test_tolerance_uniforme_cade_sul_floor():
    module = auto_params()
    angles = [6.0 + 10.0 * i / 100.0 for i in range(101)]
    params = module.derive(mesh_from_angles(angles))
    assert params.tolerance == 12.0, f'Tolerance attesa al floor 12, ottenuta {params.tolerance}'
    assert 'tolerance 12 deg' in params.describe(), f'Nota del floor assente: {params.describe()}'


def test_tolerance_bimodale_otsu_clampata():
    module = auto_params()
    smooth = [2.0 + 0.02 * i for i in range(50)]
    sharp = [60.0 + 0.2 * i for i in range(50)]
    params = module.derive(mesh_from_angles(smooth + sharp))
    assert 12.0 < params.tolerance < 50.0, (
        f'Tolerance attesa tra 12 e 50 dal gap Otsu, ottenuta {params.tolerance}')
    assert params.tolerance > max(smooth), 'Tolerance sotto il cluster liscio'
    assert params.tolerance < min(sharp), 'Tolerance sopra il cluster spigoloso'
    assert 'from the angle distribution' in params.describe(), 'Nota Otsu assente'


def test_nessun_angolo_fallback_default():
    module = auto_params()
    params = module.derive(empty_mesh())
    assert params.tolerance == 25.0, f'Fallback atteso 25, ottenuto {params.tolerance}'
    assert params.crease_weight == 1.0, 'Crease weight modificato senza angoli'
    assert 'tolerance left at default' in params.describe(), 'Nota di fallback assente'


def test_crease_weight_senza_crease():
    module = auto_params()
    smooth = [2.0 + 0.06 * i for i in range(100)]
    params = module.derive(mesh_from_angles(smooth))
    # Attesa: nessuna crease -> peso 0.0 (nessuna trazione, il bordo resta dritto),
    # come dichiarato nel commento di auto_params. Il default 1.0 vale solo senza angoli.
    assert params.crease_weight == 0.0, (
        f'Peso atteso 0.0 senza crease, ottenuto {params.crease_weight}')


def test_crease_weight_con_crease_sopra_soglia():
    module = auto_params()
    smooth = [2.0 + 0.02 * i for i in range(50)]
    sharp = [60.0 + 0.2 * i for i in range(50)]
    params = module.derive(mesh_from_angles(smooth + sharp))
    no_crease = module.derive(mesh_from_angles(smooth))
    assert params.crease_weight == 2.0, (
        f'Peso atteso 2.0 con met\u00e0 degli spigoli sopra {module.CREASE_ANGLE} deg, '
        f'ottenuto {params.crease_weight}')
    assert params.crease_weight > no_crease.crease_weight, (
        'Il peso con crease deve superare quello senza crease')


def test_min_cluster_e_ceiling_da_risoluzione():
    module = auto_params()
    angles = [2.0 + 0.06 * i for i in range(100)]
    fine = module.derive(mesh_from_angles(angles, face_count=1000),
                         FakeMarginResult(0.002))
    coarse = module.derive(mesh_from_angles(angles, face_count=1000),
                           FakeMarginResult(0.02))
    assert fine.min_cluster_faces == 2, (
        f'Cluster minimo atteso 2 con margine fine, ottenuto {fine.min_cluster_faces}')
    assert coarse.min_cluster_faces == 8, (
        f'Cluster minimo atteso 8 con margine grosso, ottenuto {coarse.min_cluster_faces}')
    assert fine.min_cluster_faces <= coarse.min_cluster_faces, (
        'Texture a risoluzione alta non deve richiedere isole pi\u00f9 grandi')
    # Valore atteso calcolato dalla formula documentata in auto_params.py:178-186:
    # islands < (PADDING_BUDGET / (4 * margin)) ** 2 / coverage ** 2,
    # clampata tra 4 e 4000. Non copiare il valore osservato: si ricalcola qui.
    expected_fine_ceiling = int(
        ((module.PADDING_BUDGET / (4.0 * 0.002)) ** 2) / (0.95 * 0.95))
    expected_fine_ceiling = max(4, min(4000, expected_fine_ceiling))
    assert fine.island_ceiling == expected_fine_ceiling, (
        f'Ceiling atteso {expected_fine_ceiling} con margine fine, '
        f'ottenuto {fine.island_ceiling}')
    assert 4 <= fine.island_ceiling <= 4000, (
        'Ceiling fuori dai limiti di clamp: {}'.format(fine.island_ceiling))
    # Valore atteso calcolato dalla stessa formula documentata, con margine grossolano.
    expected_coarse_ceiling = int(
        ((module.PADDING_BUDGET / (4.0 * 0.02)) ** 2) / (0.95 * 0.95))
    expected_coarse_ceiling = max(4, min(4000, expected_coarse_ceiling))
    assert coarse.island_ceiling == expected_coarse_ceiling, (
        f'Ceiling atteso {expected_coarse_ceiling} con margine grosso, '
        f'ottenuto {coarse.island_ceiling}')
    assert fine.island_ceiling > coarse.island_ceiling, (
        'Ceiling deve crescere al crescere della risoluzione texture')


def test_senza_margine_dichiarato_nei_default():
    module = auto_params()
    angles = [2.0 + 0.06 * i for i in range(100)]
    params = module.derive(mesh_from_angles(angles, face_count=1000), None)
    assert params.min_cluster_faces == 3, 'Cluster minimo deve restare al default senza margine'
    assert params.island_ceiling == 0, 'Ceiling deve restare 0 senza margine'
    assert 'min cluster left at default' in params.describe(), 'Nota margine assente'


def test_describe_unisce_le_note():
    module = auto_params()
    angles = [2.0 + 0.06 * i for i in range(100)]
    params = module.derive(mesh_from_angles(angles, face_count=1000),
                           FakeMarginResult(0.02))
    assert params.notes, 'Nessuna nota prodotta'
    assert params.describe() == ' | '.join(params.notes), 'describe() non unisce le note'
    assert 'crease pull' in params.describe(), 'Nota crease assente'
    assert 'min cluster' in params.describe(), 'Nota cluster assente'


if __name__ == '__main__':
    passed = failed = 0
    tests = [
        test_tolerance_uniforme_cade_sul_floor,
        test_tolerance_bimodale_otsu_clampata,
        test_nessun_angolo_fallback_default,
        test_crease_weight_senza_crease,
        test_crease_weight_con_crease_sopra_soglia,
        test_min_cluster_e_ceiling_da_risoluzione,
        test_senza_margine_dichiarato_nei_default,
        test_describe_unisce_le_note,
    ]
    for test in tests:
        try:
            test()
            passed += 1
        except Exception:
            failed += 1
            traceback.print_exc()
    print(f'RISULTATO passati={passed} falliti={failed} totale={len(tests)}')
