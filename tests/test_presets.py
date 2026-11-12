# -*- coding: utf-8 -*-
"""Contratto di presets su settings reali della scena."""

import importlib
import json
import os
import shutil
import sys
import tempfile
import traceback

import bpy

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(ROOT))
PACKAGE = os.path.basename(ROOT)


def module(name):
    return importlib.import_module(PACKAGE + '.' + name)


def _register():
    addon = importlib.import_module(PACKAGE)
    addon.register()
    return addon


def _unregister(addon):
    try:
        addon.unregister()
    except Exception:
        pass


def _settings(addon):
    settings = bpy.context.scene.intelligent_uv_settings
    assert settings is not None, 'Settings assenti dopo register()'
    return settings


def _values_comparable(left, right):
    try:
        _ = (left == right)
        return True
    except Exception:
        return False


def _close(left, right):
    if isinstance(left, float) or isinstance(right, float):
        try:
            return abs(float(left) - float(right)) <= 1e-6
        except (TypeError, ValueError):
            return left == right
    return left == right


def test_presets():
    addon = _register()
    try:
        settings = _settings(addon)
        presets_mod = module('presets')

        # 1. collect_current_values restituisce solo proprieta esistenti
        #    con valori confrontabili con lo stato attuale.
        values = presets_mod.collect_current_values(settings)
        assert (set(values).issubset(set(presets_mod.PRESET_KEYS))
                and all(hasattr(settings, key) for key in values)
                and all(_values_comparable(values[key], getattr(settings, key))
                        for key in values)), (
            'collect_current_values deve contenere solo proprieta esistenti '
            'con valori confrontabili')

        # 2. Round trip: applicare gli stessi valori non cambia nulla.
        before = dict(values)
        presets_mod.apply_values(settings, before)
        after = presets_mod.collect_current_values(settings)
        assert all(_close(before[key], after.get(key)) for key in before), (
            'Round trip fallito: i valori sono cambiati dopo apply_values')

        # 3. Una chiave sconosciuta non solleva e non tocca le altre proprieta.
        snapshot = presets_mod.collect_current_values(settings)
        applied, skipped = presets_mod.apply_values(
            settings, {'__unknown_preset_key__': 123})
        assert (applied == 0
                and '__unknown_preset_key__' in (skipped or [])
                and all(_close(snapshot[key], getattr(settings, key))
                        for key in snapshot)), (
            'apply_values con chiave sconosciuta deve saltare senza toccare '
            'le altre proprieta')

        # 4. list_presets: nomi senza estensione e senza duplicati, anche
        #    con cartella preset vuota.
        empty_dir = tempfile.mkdtemp(
            prefix='iuv_preset_empty_', dir=tempfile.gettempdir())
        preset_file = os.path.join(empty_dir, 'Hard Surface.json')
        original_get = presets_mod.get_preset_dir
        try:
            presets_mod.get_preset_dir = lambda create=True: empty_dir
            empty_names = presets_mod.list_presets()

            with open(preset_file, 'w', encoding='utf-8') as handle:
                json.dump({'seam_method': 'VSA'}, handle)
            names_with_file = presets_mod.list_presets()
        finally:
            presets_mod.get_preset_dir = original_get
            try:
                os.remove(preset_file)
            except OSError:
                pass
            shutil.rmtree(empty_dir, ignore_errors=True)

        assert (len(empty_names) == len(set(empty_names))
                and all(not str(name).lower().endswith('.json')
                        for name in empty_names)
                and len(names_with_file) == len(set(names_with_file))
                and all(not str(name).lower().endswith('.json')
                        for name in names_with_file)), (
            'list_presets deve restituire nomi senza estensione e senza '
            'duplicati, anche con cartella vuota')
    finally:
        _unregister(addon)


if __name__ == '__main__':
    passed = failed = 0
    tests = [test_presets]
    for test in tests:
        try:
            test()
            passed += 1
        except Exception:
            failed += 1
            traceback.print_exc()
    print('RISULTATO passati={} falliti={} totale={}'.format(
        passed, failed, len(tests)))