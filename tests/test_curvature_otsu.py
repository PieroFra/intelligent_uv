# -*- coding: utf-8 -*-
"""Contratto di CurvatureEstimator._otsu_threshold su insiemi sintetici.

Il metodo restituisce una soglia in gradi, oppure None quando non esiste
una divisione valida (vuoto, valore singolo). Non deve mai andare in crash.
"""

import importlib
import os
import sys
import traceback

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


if __name__ == '__main__':
    passed = failed = 0
    tests = [
        test_otsu_bimodale_netto_tra_i_picchi,
        test_otsu_bimodale_indipendente_dall_ordine,
        test_otsu_uniforme_resta_nel_range,
        test_otsu_valore_singolo_nessuna_soglia,
        test_otsu_vuoto_nessuna_soglia,
        test_otsu_none_nessun_crash,
    ]
    for test in tests:
        try:
            test()
            passed += 1
        except Exception:
            failed += 1
            traceback.print_exc()
    print(f'RISULTATO passati={passed} falliti={failed} totale={len(tests)}')
