# -*- coding: utf-8 -*-
"""Contratto di margins.MarginCalculator su settings reali della scena."""

import importlib
import math
import os
import sys
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


def _reset(settings):
    for prop in settings.bl_rna.properties:
        if prop.identifier == 'rna_type' or prop.is_readonly or prop.type == 'COLLECTION':
            continue
        try:
            setattr(settings, prop.identifier, prop.default)
        except Exception:
            pass


class FakeMeshAnalysis:
    def __init__(self, total_area, edge_lengths):
        self.ok = True
        self.face_count = 10
        self.edge_count = 10
        self.total_area = float(total_area)
        self.edge_lengths = list(edge_lengths)


def test_get_texture_resolution_modes():
    addon = _register()
    try:
        settings = _settings(addon)
        _reset(settings)
        cases = [('1K', 1024), ('2K', 2048), ('4K', 4096)]
        for mode, expected in cases:
            settings.texture_resolution_mode = mode
            actual = module('margins').MarginCalculator.get_texture_resolution(settings)
            assert actual == expected, (
                'Risoluzione attesa {} per mode {}, ottenuta {}'.format(
                    expected, mode, actual))
    finally:
        _unregister(addon)


def test_get_texture_resolution_custom_clamp():
    addon = _register()
    try:
        settings = _settings(addon)
        _reset(settings)
        settings.texture_resolution_mode = 'CUSTOM'

        settings.custom_texture_resolution = 100
        actual = module('margins').MarginCalculator.get_texture_resolution(settings)
        assert actual == 100, 'Custom 100 deve restare 100, ottenuto {}'.format(actual)

        settings.custom_texture_resolution = 50
        actual = module('margins').MarginCalculator.get_texture_resolution(settings)
        assert actual == 64, 'Custom sotto il minimo deve clampare a 64, ottenuto {}'.format(actual)

        settings.custom_texture_resolution = 20000
        actual = module('margins').MarginCalculator.get_texture_resolution(settings)
        assert actual == 16384, 'Custom sopra il massimo deve clampare a 16384, ottenuto {}'.format(actual)
    finally:
        _unregister(addon)


def test_get_texture_resolution_fallback():
    # Nessun attributo riconosciuto: cade sul default 2K.
    margins = module('margins')

    class _Empty:
        pass

    actual = margins.MarginCalculator.get_texture_resolution(_Empty())
    assert actual == 2048, 'Fallback atteso 2048, ottenuto {}'.format(actual)


def test_margin_grows_with_island_count():
    addon = _register()
    try:
        settings = _settings(addon)
        _reset(settings)
        settings.texture_resolution_mode = '2K'
        low = module('margins').MarginCalculator.calculate(settings, None, 1)
        high = module('margins').MarginCalculator.calculate(settings, None, 1024)
        assert low.ok, 'Calcolo base non ok: {}'.format(low.errors)
        assert high.ok, 'Calcolo con isole non ok: {}'.format(high.errors)
        assert high.margin_px > low.margin_px, (
            'Il margine deve crescere con island_count alto: {} <= {}'.format(
                high.margin_px, low.margin_px))
    finally:
        _unregister(addon)


def test_calculate_auto_min_px():
    addon = _register()
    try:
        settings = _settings(addon)
        _reset(settings)
        settings.texture_resolution_mode = '1K'
        result = module('margins').MarginCalculator.calculate(settings, None, 1)
        assert result.ok, 'Calcolo non ok: {}'.format(result.errors)
        assert result.margin_px >= 2, (
            'Il margine auto non deve scendere sotto 2px, ottenuto {}'.format(result.margin_px))
        assert result.texture_resolution == 1024, (
            'Risoluzione attesa 1024, ottenuta {}'.format(result.texture_resolution))
    finally:
        _unregister(addon)


def test_calculate_seam_margin_capped():
    addon = _register()
    try:
        settings = _settings(addon)
        _reset(settings)
        settings.texture_resolution_mode = '2K'
        # Area enorme -> seam length richiesto enorme -> oltre il 15% degli edge.
        analysis = FakeMeshAnalysis(1e6, [1.0] * 100)
        result = module('margins').MarginCalculator.calculate(settings, analysis, 1)
        assert result.ok, 'Calcolo non ok: {}'.format(result.errors)
        assert result.seam_margin_capped is True, (
            'Il seam margin avrebbe dovuto essere capped, ma non lo e')
        assert result.excluded_edge_fraction <= module('margins').MarginCalculator.MAX_EXCLUDED_EDGE_FRACTION + 1e-9, (
            'Frazione esclusa {} oltre il limite dichiarato'.format(
                result.excluded_edge_fraction))
        assert result.min_seam_edge_length == 1.0, (
            'min_seam_edge_length capped atteso 1.0, ottenuto {}'.format(
                result.min_seam_edge_length))
    finally:
        _unregister(addon)


def test_calculate_seam_margin_not_capped():
    addon = _register()
    try:
        settings = _settings(addon)
        _reset(settings)
        settings.texture_resolution_mode = '2K'
        analysis = FakeMeshAnalysis(1.0, [0.1] * 100)
        result = module('margins').MarginCalculator.calculate(settings, analysis, 1)
        assert result.ok, 'Calcolo non ok: {}'.format(result.errors)
        assert result.seam_margin_capped is False, (
            'Il seam margin non doveva essere capped')
        assert result.excluded_edge_fraction == 0.0, (
            'Frazione esclusa attesa 0.0, ottenuta {}'.format(
                result.excluded_edge_fraction))
    finally:
        _unregister(addon)


def test_calculate_consistent_px_uv_auto():
    addon = _register()
    try:
        settings = _settings(addon)
        _reset(settings)
        settings.texture_resolution_mode = '2K'
        result = module('margins').MarginCalculator.calculate(settings, None, 5)
        assert result.ok, 'Calcolo non ok: {}'.format(result.errors)
        assert result.spacing_px == result.margin_px, (
            'spacing_px {} != margin_px {}'.format(result.spacing_px, result.margin_px))
        expected_uv = float(result.margin_px) / float(result.texture_resolution)
        assert abs(result.margin_uv - expected_uv) < 1e-12, (
            'margin_uv {} incoerente con px/risoluzione {}'.format(
                result.margin_uv, expected_uv))
        assert result.is_auto is True, 'is_auto deve essere True in auto'
    finally:
        _unregister(addon)


def test_calculate_consistent_px_uv_manual():
    addon = _register()
    try:
        settings = _settings(addon)
        _reset(settings)
        settings.texture_resolution_mode = '2K'
        settings.auto_island_margin = False
        settings.island_margin = 0.05
        result = module('margins').MarginCalculator.calculate(settings, None, 1)
        assert result.ok, 'Calcolo non ok: {}'.format(result.errors)
        assert result.is_auto is False, 'is_auto deve essere False in manuale'
        # margin_uv e un float RNA a 32 bit (0.05000000074505806), quindi
        # la tolleranza 1e-12 e troppo stretta: si usa 1e-6.
        assert abs(result.margin_uv - 0.05) < 1e-6, (
            'margin_uv atteso 0.05, ottenuto {}'.format(result.margin_uv))
        expected_px = max(1, int(round(result.margin_uv * result.texture_resolution)))
        assert result.margin_px == expected_px, (
            'margin_px {} incoerente con uv*risoluzione {}'.format(
                result.margin_px, expected_px))
        assert result.spacing_px == result.margin_px, (
            'spacing_px {} != margin_px {}'.format(result.spacing_px, result.margin_px))
    finally:
        _unregister(addon)


def test_calculate_none_settings():
    margins = module('margins')
    result = margins.MarginCalculator.calculate(None)
    assert result.ok is False, 'Settings None deve dare ok=False'
    assert result.errors, 'Settings None deve produrre errori'


if __name__ == '__main__':
    passed = failed = 0
    tests = [
        test_get_texture_resolution_modes,
        test_get_texture_resolution_custom_clamp,
        test_get_texture_resolution_fallback,
        test_margin_grows_with_island_count,
        test_calculate_auto_min_px,
        test_calculate_seam_margin_capped,
        test_calculate_seam_margin_not_capped,
        test_calculate_consistent_px_uv_auto,
        test_calculate_consistent_px_uv_manual,
        test_calculate_none_settings,
    ]
    for test in tests:
        try:
            test()
            passed += 1
        except Exception:
            failed += 1
            traceback.print_exc()
    print('RISULTATO passati={} falliti={} totale={}'.format(passed, failed, len(tests)))
