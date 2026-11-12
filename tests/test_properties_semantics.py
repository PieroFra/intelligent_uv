# -*- coding: utf-8 -*-
"""Contratto semantico delle proprieta del PropertyGroup registrato."""

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


# Lista canonica dei nomi delle proprieta esposte. La rimozione o la
# rinomina di una proprieta deve far fallire questo test invece di rompere
# silenziosamente i .blend degli utenti.
EXPECTED_EXPOSED_PROPERTIES = {
    'absorb_micro_islands',
    'active_preset_name',
    'auto_curvature_threshold',
    'auto_island_margin',
    'auto_parameters',
    'auto_seam_margin',
    'backup_uv_layer',
    'check_overlaps',
    'concave_seam_bias',
    'curvature_threshold',
    'custom_texture_resolution',
    'dry_run',
    'island_margin',
    'keep_temp_files',
    'last_export_path',
    'link_keep_open',
    'link_optimize',
    'mark_bevel_debug',
    'merge_islands',
    'merge_max_cone_angle',
    'min_seam_edge_length',
    'minimize_stretch',
    'minimize_stretch_iterations',
    'minimum_island_face_count',
    'normalize_texel_density',
    'orient_islands',
    'preserve_existing_seams',
    'process_selected',
    'prune_dangling_seams',
    'recover_failed_islands',
    'recovery_rounds',
    'recovery_tolerance',
    'report_distortion',
    'rizomuv_args',
    'rizomuv_engine_mode',
    'rizomuv_path',
    'rizomuv_timeout',
    'run_preflight',
    'seam_method',
    'separate_by_material',
    'show_advanced',
    'split_max_cone_angle',
    'split_non_developable',
    'stack_duplicates',
    'stop_on_blockers',
    'symmetrize_seams',
    'symmetry_min_coverage',
    'target_coverage',
    'texture_resolution_mode',
    'texture_sets',
    'udim_max_tiles',
    'use_rizomuv',
    'use_udim',
    'uv_layer_name',
    'vsa_area_weighted',
    'vsa_crease_weight',
    'vsa_iterations',
    'vsa_max_angle_deviation',
    'vsa_merge_clusters',
    'vsa_min_cluster_faces',
    'vsa_resolve_topology',
    'vsa_smooth_passes',
    'vsa_target_clusters',
}


def test_properties_semantics():
    addon = _register()
    try:
        settings = _settings(addon)
        presets_mod = module('presets')
        # 'rna_type' e 'name' sono proprieta intrinseche di RNA del PropertyGroup:
        # il PropertyGroup le fornisce per conto suo, non sono proprieta nostre.
        _INTRINSIC_RNA_PROPERTIES = ('rna_type', 'name')
        exposed = [p for p in settings.bl_rna.properties
                   if p.identifier not in _INTRINSIC_RNA_PROPERTIES]

        # 1. Ogni proprieta ENUM ha default presente tra gli item e item
        #    senza duplicati.
        for prop in exposed:
            if prop.type != 'ENUM':
                continue
            identifiers = [item.identifier for item in prop.enum_items]
            assert len(identifiers) == len(set(identifiers)), (
                "proprieta '{0}': item duplicati negli enum".format(
                    prop.identifier))
            assert prop.default in identifiers, (
                "proprieta '{0}': default '{1}' assente tra gli item {2}".format(
                    prop.identifier, prop.default, identifiers))

        # 2. Ogni proprieta numerica ha default dentro hard_min/hard_max quando
        #    definiti e soft_min <= soft_max.
        for prop in exposed:
            if prop.type not in ('INT', 'FLOAT'):
                continue
            default = prop.default
            if math.isfinite(prop.hard_min):
                assert default >= prop.hard_min, (
                    "proprieta '{0}': default {1} sotto hard_min {2}".format(
                        prop.identifier, default, prop.hard_min))
            if math.isfinite(prop.hard_max):
                assert default <= prop.hard_max, (
                    "proprieta '{0}': default {1} sopra hard_max {2}".format(
                        prop.identifier, default, prop.hard_max))
            assert prop.soft_min <= prop.soft_max, (
                "proprieta '{0}': soft_min {1} > soft_max {2}".format(
                    prop.identifier, prop.soft_min, prop.soft_max))

        # 3. Nessuna proprieta esposta ha nome vuoto o identico a un'altra.
        seen_names = set()
        duplicate_prop = None
        for prop in exposed:
            assert prop.name != '', (
                "proprieta '{0}': nome vuoto".format(prop.identifier))
            if prop.name in seen_names:
                duplicate_prop = prop.identifier
                break
            seen_names.add(prop.name)
        assert duplicate_prop is None, (
            "proprieta '{0}': nome identico a un'altra".format(duplicate_prop))

        # 4. Tutte le proprieta usate dai preset esistono davvero sul settings.
        for key in presets_mod.PRESET_KEYS:
            assert hasattr(settings, key), (
                "chiave preset '{0}' assente sul settings".format(key))

        # 5. Compatibilita: il set dei nomi delle proprieta esposte non cambia.
        actual = {p.identifier for p in exposed}
        assert actual == EXPECTED_EXPOSED_PROPERTIES, (
            "set proprieta esposte cambiato: mancanti={0} extra={1}".format(
                sorted(EXPECTED_EXPOSED_PROPERTIES - actual),
                sorted(actual - EXPECTED_EXPOSED_PROPERTIES)))
    finally:
        _unregister(addon)


if __name__ == '__main__':
    passed = failed = 0
    tests = [test_properties_semantics]
    for test in tests:
        try:
            test()
            passed += 1
        except Exception:
            failed += 1
            traceback.print_exc()
    print('RISULTATO passati={} falliti={} totale={}'.format(
        passed, failed, len(tests)))