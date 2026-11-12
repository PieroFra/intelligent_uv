# -*- coding: utf-8 -*-
"""Proprieta' di utils.normalize_vector e utils.angle_between_degrees."""

import importlib
import math
import os
import sys
import traceback

import bpy

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(ROOT))
PACKAGE = os.path.basename(ROOT)


def utils():
    module = importlib.import_module(PACKAGE + '.utils')
    assert callable(getattr(module, 'normalize_vector', None)), 'normalize_vector assente'
    assert callable(getattr(module, 'angle_between_degrees', None)), 'angle_between_degrees assente'
    return module


def test_normalize_zero_returns_none():
    module = utils()
    assert module.normalize_vector((0.0, 0.0, 0.0)) is None, 'Vettore nullo deve dare None'
    assert module.normalize_vector([0.0, 0.0, 0.0]) is None, 'Vettore nullo (lista) deve dare None'
    assert module.normalize_vector(None) is None, 'None deve dare None'


def test_normalize_empty_returns_none():
    module = utils()
    assert module.normalize_vector(()) is None, 'Tupla vuota deve dare None'
    assert module.normalize_vector([]) is None, 'Lista vuota deve dare None'


def test_normalize_tiny_returns_none():
    module = utils()
    tiny = (1e-13, 0.0, 0.0)
    assert module.normalize_vector(tiny) is None, 'Vettore quasi nullo deve dare None'


def test_normalize_unit_vector():
    module = utils()
    result = module.normalize_vector((1.0, 0.0, 0.0))
    assert result == (1.0, 0.0, 0.0), 'Asse X gia unitario: {}'.format(result)
    result = module.normalize_vector((0.0, 1.0, 0.0))
    assert result == (0.0, 1.0, 0.0), 'Asse Y gia unitario: {}'.format(result)


def test_normalize_non_unit():
    module = utils()
    result = module.normalize_vector((3.0, 4.0, 0.0))
    expected = (0.6, 0.8, 0.0)
    assert result is not None, 'Risultato None inatteso'
    for actual, exp in zip(result, expected):
        assert abs(actual - exp) < 1e-12, 'Componente {} != {} (risultato {})'.format(
            actual, exp, result)
    length = math.sqrt(sum(c * c for c in result))
    assert abs(length - 1.0) < 1e-12, 'Norma risultante {} != 1'.format(length)


def test_normalize_negative():
    module = utils()
    result = module.normalize_vector((-3.0, -4.0, 0.0))
    expected = (-0.6, -0.8, 0.0)
    assert result is not None
    for actual, exp in zip(result, expected):
        assert abs(actual - exp) < 1e-12, 'Componente {} != {}'.format(actual, exp)


def test_normalize_3d():
    module = utils()
    result = module.normalize_vector((1.0, 1.0, 1.0))
    assert result is not None
    for c in result:
        assert abs(c - 1.0 / math.sqrt(3.0)) < 1e-12, 'Componente {} inattesa'.format(c)


def test_angle_parallel():
    module = utils()
    actual = module.angle_between_degrees((1.0, 0.0, 0.0), (2.0, 0.0, 0.0))
    assert abs(actual - 0.0) < 1e-9, 'Paralleli devono dare 0 deg, ottenuto {}'.format(actual)


def test_angle_opposite():
    module = utils()
    actual = module.angle_between_degrees((1.0, 0.0, 0.0), (-1.0, 0.0, 0.0))
    assert abs(actual - 180.0) < 1e-9, 'Opposti devono dare 180 deg, ottenuto {}'.format(actual)


def test_angle_orthogonal():
    module = utils()
    actual = module.angle_between_degrees((1.0, 0.0, 0.0), (0.0, 1.0, 0.0))
    assert abs(actual - 90.0) < 1e-9, 'Ortogonali devono dare 90 deg, ottenuto {}'.format(actual)


def test_angle_known_value():
    module = utils()
    # (3,4,0) normalizzato = (0.6,0.8,0); angolo con X = acos(0.6) = 53.13010235...
    actual = module.angle_between_degrees((3.0, 4.0, 0.0), (1.0, 0.0, 0.0))
    expected = math.degrees(math.acos(0.6))
    assert abs(actual - expected) < 1e-9, 'Angolo atteso {} deg, ottenuto {}'.format(
        expected, actual)


def test_angle_quasi_parallel_no_nan():
    module = utils()
    actual = module.angle_between_degrees((1.0, 0.0, 0.0), (1.0, 1e-12, 0.0))
    assert not math.isnan(actual), 'NaN su quasi-paralleli'
    assert not math.isinf(actual), 'Inf su quasi-paralleli'
    assert actual >= 0.0 and actual < 1e-6, 'Angolo quasi-parallelo inatteso: {}'.format(actual)


def test_angle_null_fallback():
    module = utils()
    # Entrambi nulli -> fallback (0,1,0) per entrambi -> 0 deg.
    actual = module.angle_between_degrees((0.0, 0.0, 0.0), (0.0, 0.0, 0.0))
    assert abs(actual - 0.0) < 1e-9, 'Due nulli devono dare 0 deg (fallback), ottenuto {}'.format(actual)


def test_angle_one_null():
    module = utils()
    # Primo nullo -> fallback (0,1,0); secondo asse X -> 90 deg.
    actual = module.angle_between_degrees((0.0, 0.0, 0.0), (1.0, 0.0, 0.0))
    assert abs(actual - 90.0) < 1e-9, 'Un nullo deve dare 90 deg, ottenuto {}'.format(actual)


def test_angle_non_normalized():
    module = utils()
    a = module.angle_between_degrees((3.0, 4.0, 0.0), (0.0, 5.0, 0.0))
    b = module.angle_between_degrees((0.6, 0.8, 0.0), (0.0, 1.0, 0.0))
    assert abs(a - b) < 1e-9, 'I vettori non normalizzati devono dare lo stesso angolo: {} vs {}'.format(a, b)


def test_angle_opposite_non_unit():
    module = utils()
    actual = module.angle_between_degrees((2.0, 0.0, 0.0), (-3.0, 0.0, 0.0))
    assert abs(actual - 180.0) < 1e-9, 'Opposti non unitari devono dare 180 deg, ottenuto {}'.format(actual)


if __name__ == '__main__':
    passed = failed = 0
    tests = [
        test_normalize_zero_returns_none,
        test_normalize_empty_returns_none,
        test_normalize_tiny_returns_none,
        test_normalize_unit_vector,
        test_normalize_non_unit,
        test_normalize_negative,
        test_normalize_3d,
        test_angle_parallel,
        test_angle_opposite,
        test_angle_orthogonal,
        test_angle_known_value,
        test_angle_quasi_parallel_no_nan,
        test_angle_null_fallback,
        test_angle_one_null,
        test_angle_non_normalized,
        test_angle_opposite_non_unit,
    ]
    for test in tests:
        try:
            test()
            passed += 1
        except Exception:
            failed += 1
            traceback.print_exc()
    print('RISULTATO passati={} falliti={} totale={}'.format(passed, failed, len(tests)))
