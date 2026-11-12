# -*- coding: utf-8 -*-
"""Test degli operatori diagnose e preview_*: ritorno FINISHED su mesh valida,
rifiuto pulito senza UV e senza oggetto attivo, coerenza facce/loop."""

import importlib
import os
import sys
import traceback

import bpy

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PACKAGE = os.path.basename(ROOT)
sys.path.insert(0, os.path.dirname(ROOT))


def module(name):
    return importlib.import_module(PACKAGE + "." + name)


def _remove(obj):
    try:
        if obj is not None:
            bpy.data.objects.remove(obj, do_unlink=True)
    except Exception:  # noqa: BLE001 - pulizia non deve far fallire il controllo
        pass
    try:
        mesh = getattr(obj, "data", None)
        if mesh is not None and getattr(mesh, "users", 1) == 0:
            bpy.data.meshes.remove(mesh)
    except Exception:  # noqa: BLE001 - pulizia non deve far fallire il controllo
        pass


def _activate(obj):
    for other in bpy.context.view_layer.objects:
        try:
            other.select_set(False)
        except Exception:  # noqa: BLE001
            pass
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def _deactivate():
    for other in bpy.context.view_layer.objects:
        try:
            other.select_set(False)
        except Exception:  # noqa: BLE001
            pass
    try:
        bpy.context.view_layer.objects.active = None
    except Exception:  # noqa: BLE001
        pass


def _make_sphere():
    bpy.ops.mesh.primitive_uv_sphere_add(
        segments=32, ring_count=16, radius=0.7, location=(0.0, 0.0, 0.0),
        calc_uvs=False,
    )
    obj = bpy.context.object
    assert obj is not None and obj.type == "MESH", "Sfera di prova non creata"
    mesh = obj.data
    for edge in mesh.edges:
        edge.use_seam = False
    for layer in list(mesh.uv_layers):
        try:
            mesh.uv_layers.remove(layer)
        except Exception:  # noqa: BLE001
            pass
    _activate(obj)
    return obj


def _counts(obj):
    mesh = obj.data
    return len(mesh.polygons), len(mesh.loops)


def _call_operator(callable_):
    """Chiama bpy.ops...; un poll fallito e' un rifiuto pulito, non un traceback."""
    try:
        return callable_()
    except RuntimeError as exc:
        text = str(exc)
        if "poll() failed" in text or "context is incorrect" in text:
            return None
        raise


def _reset_settings(settings):
    for prop in settings.bl_rna.properties:
        if prop.identifier == "rna_type" or prop.is_readonly or prop.type == "COLLECTION":
            continue
        try:
            setattr(settings, prop.identifier, prop.default)
        except Exception:  # noqa: BLE001
            pass


# ---------------------------------------------------------------------------
# Diagnose
# ---------------------------------------------------------------------------

def test_diagnose_valid_mesh():
    addon = importlib.import_module(PACKAGE)
    addon.register()
    obj = None
    try:
        obj = _make_sphere()
        settings = bpy.context.scene.intelligent_uv_settings
        _reset_settings(settings)
        addon.IntelligentUV_OT_Run._busy = False

        before = _counts(obj)
        result = bpy.ops.intelligent_uv.diagnose()
        assert result == {"FINISHED"}, (
            "diagnose su mesh valida non FINISHED: " + repr(result))
        after = _counts(obj)
        assert after == before, (
            "mesh alterata da diagnose: %s vs %s" % (after, before))
        return "diagnose valida OK"
    finally:
        _remove(obj)
        try:
            addon.unregister()
        except Exception:  # noqa: BLE001
            pass


def test_diagnose_no_uv_mesh():
    addon = importlib.import_module(PACKAGE)
    addon.register()
    obj = None
    try:
        obj = _make_sphere()
        # Assicura assenza di layer UV.
        for layer in list(obj.data.uv_layers):
            try:
                obj.data.uv_layers.remove(layer)
            except Exception:  # noqa: BLE001
                pass
        settings = bpy.context.scene.intelligent_uv_settings
        _reset_settings(settings)
        addon.IntelligentUV_OT_Run._busy = False

        before = _counts(obj)
        result = bpy.ops.intelligent_uv.diagnose()
        assert result == {"FINISHED"}, (
            "diagnose su mesh senza UV non FINISHED: " + repr(result))
        after = _counts(obj)
        assert after == before, (
            "mesh alterata da diagnose: %s vs %s" % (after, before))
        return "diagnose senza UV OK"
    finally:
        _remove(obj)
        try:
            addon.unregister()
        except Exception:  # noqa: BLE001
            pass


def test_diagnose_no_active_object():
    addon = importlib.import_module(PACKAGE)
    addon.register()
    obj = None
    try:
        obj = _make_sphere()
        _deactivate()
        raised = False
        try:
            result = bpy.ops.intelligent_uv.diagnose()
        except RuntimeError as exc:
            raised = True
            assert "Select a mesh object first" in str(exc), (
                "diagnose senza oggetto attivo: messaggio inatteso: " + repr(exc))
        if not raised:
            assert result == {"CANCELLED"}, (
                "diagnose senza oggetto attivo non rifiutata pulitamente: "
                + repr(result))
        return "diagnose senza oggetto attivo OK"
    finally:
        _remove(obj)
        try:
            addon.unregister()
        except Exception:  # noqa: BLE001
            pass


# ---------------------------------------------------------------------------
# Preview
# ---------------------------------------------------------------------------

def test_preview_valid_mesh():
    addon = importlib.import_module(PACKAGE)
    addon.register()
    obj = None
    try:
        obj = _make_sphere()
        settings = bpy.context.scene.intelligent_uv_settings
        _reset_settings(settings)
        addon.IntelligentUV_OT_Run._busy = False

        before = _counts(obj)
        result = bpy.ops.intelligent_uv.preview()
        assert result == {"FINISHED"}, (
            "preview su mesh valida non FINISHED: " + repr(result))
        after = _counts(obj)
        assert after == before, (
            "mesh alterata da preview: %s vs %s" % (after, before))
        return "preview valida OK"
    finally:
        _remove(obj)
        try:
            addon.unregister()
        except Exception:  # noqa: BLE001
            pass


def test_preview_no_uv_mesh():
    addon = importlib.import_module(PACKAGE)
    addon.register()
    obj = None
    try:
        obj = _make_sphere()
        for layer in list(obj.data.uv_layers):
            try:
                obj.data.uv_layers.remove(layer)
            except Exception:  # noqa: BLE001
                pass
        settings = bpy.context.scene.intelligent_uv_settings
        _reset_settings(settings)
        addon.IntelligentUV_OT_Run._busy = False

        before = _counts(obj)
        result = bpy.ops.intelligent_uv.preview()
        assert result == {"FINISHED"}, (
            "preview su mesh senza UV non FINISHED: " + repr(result))
        after = _counts(obj)
        assert after == before, (
            "mesh alterata da preview: %s vs %s" % (after, before))
        return "preview senza UV OK"
    finally:
        _remove(obj)
        try:
            addon.unregister()
        except Exception:  # noqa: BLE001
            pass


def test_preview_no_active_object():
    addon = importlib.import_module(PACKAGE)
    addon.register()
    obj = None
    try:
        obj = _make_sphere()
        _deactivate()
        result = _call_operator(lambda: bpy.ops.intelligent_uv.preview())
        assert result is None or result == {"CANCELLED"}, (
            "preview senza oggetto attivo non rifiutata pulitamente: " + repr(result))
        return "preview senza oggetto attivo OK"
    finally:
        _remove(obj)
        try:
            addon.unregister()
        except Exception:  # noqa: BLE001
            pass


# ---------------------------------------------------------------------------
# Apply preview
# ---------------------------------------------------------------------------

def test_apply_preview_valid_mesh():
    addon = importlib.import_module(PACKAGE)
    addon.register()
    obj = None
    try:
        obj = _make_sphere()
        settings = bpy.context.scene.intelligent_uv_settings
        _reset_settings(settings)
        addon.IntelligentUV_OT_Run._busy = False

        # Crea uno stato pending.
        preview_result = bpy.ops.intelligent_uv.preview()
        assert preview_result == {"FINISHED"}, (
            "preview preliminare fallito: " + repr(preview_result))

        before = _counts(obj)
        result = bpy.ops.intelligent_uv.apply_preview()
        assert result == {"FINISHED"}, (
            "apply_preview su mesh valida non FINISHED: " + repr(result))
        after = _counts(obj)
        assert after == before, (
            "mesh alterata da apply_preview: %s vs %s" % (after, before))

        # Dopo l'apply non deve restare pending.
        preview_mod = module("preview")
        assert not preview_mod.has_pending(obj.data), (
            "backup residuo dopo apply_preview")
        return "apply_preview valida OK"
    finally:
        _remove(obj)
        try:
            addon.unregister()
        except Exception:  # noqa: BLE001
            pass


def test_apply_preview_no_pending():
    addon = importlib.import_module(PACKAGE)
    addon.register()
    obj = None
    try:
        obj = _make_sphere()
        settings = bpy.context.scene.intelligent_uv_settings
        _reset_settings(settings)
        addon.IntelligentUV_OT_Run._busy = False

        before = _counts(obj)
        result = _call_operator(lambda: bpy.ops.intelligent_uv.apply_preview())
        assert result is None or result == {"CANCELLED"}, (
            "apply_preview senza pending non rifiutata pulitamente: " + repr(result))
        after = _counts(obj)
        assert after == before, (
            "mesh alterata da apply_preview: %s vs %s" % (after, before))
        return "apply_preview senza pending OK"
    finally:
        _remove(obj)
        try:
            addon.unregister()
        except Exception:  # noqa: BLE001
            pass


def test_apply_preview_no_active_object():
    addon = importlib.import_module(PACKAGE)
    addon.register()
    obj = None
    try:
        obj = _make_sphere()
        _deactivate()
        result = _call_operator(lambda: bpy.ops.intelligent_uv.apply_preview())
        assert result is None or result == {"CANCELLED"}, (
            "apply_preview senza oggetto attivo non rifiutata pulitamente: " + repr(result))
        return "apply_preview senza oggetto attivo OK"
    finally:
        _remove(obj)
        try:
            addon.unregister()
        except Exception:  # noqa: BLE001
            pass


# ---------------------------------------------------------------------------
# Discard preview
# ---------------------------------------------------------------------------

def test_discard_preview_valid_mesh():
    addon = importlib.import_module(PACKAGE)
    addon.register()
    obj = None
    try:
        obj = _make_sphere()
        settings = bpy.context.scene.intelligent_uv_settings
        _reset_settings(settings)
        addon.IntelligentUV_OT_Run._busy = False

        preview_result = bpy.ops.intelligent_uv.preview()
        assert preview_result == {"FINISHED"}, (
            "preview preliminare fallito: " + repr(preview_result))

        before = _counts(obj)
        result = bpy.ops.intelligent_uv.discard_preview()
        assert result == {"FINISHED"}, (
            "discard_preview su mesh valida non FINISHED: " + repr(result))
        after = _counts(obj)
        assert after == before, (
            "mesh alterata da discard_preview: %s vs %s" % (after, before))

        preview_mod = module("preview")
        assert not preview_mod.has_pending(obj.data), (
            "backup residuo dopo discard_preview")
        return "discard_preview valida OK"
    finally:
        _remove(obj)
        try:
            addon.unregister()
        except Exception:  # noqa: BLE001
            pass


def test_discard_preview_no_pending():
    addon = importlib.import_module(PACKAGE)
    addon.register()
    obj = None
    try:
        obj = _make_sphere()
        settings = bpy.context.scene.intelligent_uv_settings
        _reset_settings(settings)
        addon.IntelligentUV_OT_Run._busy = False

        before = _counts(obj)
        result = _call_operator(lambda: bpy.ops.intelligent_uv.discard_preview())
        assert result is None or result == {"CANCELLED"}, (
            "discard_preview senza pending non rifiutata pulitamente: " + repr(result))
        after = _counts(obj)
        assert after == before, (
            "mesh alterata da discard_preview: %s vs %s" % (after, before))
        return "discard_preview senza pending OK"
    finally:
        _remove(obj)
        try:
            addon.unregister()
        except Exception:  # noqa: BLE001
            pass


def test_discard_preview_no_active_object():
    addon = importlib.import_module(PACKAGE)
    addon.register()
    obj = None
    try:
        obj = _make_sphere()
        _deactivate()
        result = _call_operator(lambda: bpy.ops.intelligent_uv.discard_preview())
        assert result is None or result == {"CANCELLED"}, (
            "discard_preview senza oggetto attivo non rifiutata pulitamente: " + repr(result))
        return "discard_preview senza oggetto attivo OK"
    finally:
        _remove(obj)
        try:
            addon.unregister()
        except Exception:  # noqa: BLE001
            pass


if __name__ == "__main__":
    passed = 0
    failed = 0
    tests = (
        test_diagnose_valid_mesh,
        test_diagnose_no_uv_mesh,
        test_diagnose_no_active_object,
        test_preview_valid_mesh,
        test_preview_no_uv_mesh,
        test_preview_no_active_object,
        test_apply_preview_valid_mesh,
        test_apply_preview_no_pending,
        test_apply_preview_no_active_object,
        test_discard_preview_valid_mesh,
        test_discard_preview_no_pending,
        test_discard_preview_no_active_object,
    )
    for test in tests:
        try:
            test()
            passed += 1
        except Exception:
            failed += 1
            traceback.print_exc()
    print("RISULTATO passati={0} falliti={1} totale={2}".format(
        passed, failed, len(tests)))