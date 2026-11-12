# -*- coding: utf-8 -*-
"""Test di preview.py: capture, revert e robustezza."""

import importlib
import math
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


def _cube():
    bpy.ops.mesh.primitive_cube_add(size=2.0, location=(0.0, 0.0, 0.0))
    obj = bpy.context.object
    assert obj is not None and obj.type == "MESH", "Cubo di prova non creato"
    return obj


def _create_uv_layer(mesh, name):
    uv_layers = mesh.uv_layers
    try:
        uv_layer = uv_layers.new(name=name)
    except Exception:
        uv_layer = uv_layers.new()
        try:
            uv_layer.name = name
        except Exception:
            pass
    assert uv_layer is not None, "Impossibile creare il layer UV '%s'" % name
    return uv_layer


def test_preview():
    addon = importlib.import_module(PACKAGE)
    addon.register()
    obj = None
    try:
        obj = _cube()
        mesh = obj.data
        utils = module("utils")
        preview_mod = module("preview")

        # Rimuovi i layer UV preesistenti.
        for _existing in list(mesh.uv_layers):
            try:
                mesh.uv_layers.remove(_existing)
            except Exception:
                pass

        uv_name = "SmartUV"
        uv_layer = _create_uv_layer(mesh, uv_name)
        mesh.uv_layers.active = uv_layer
        try:
            mesh.uv_layers.active_index = mesh.uv_layers.find(uv_name)
        except Exception:
            pass

        # Seleziona e proietta con Smart UV Project per avere UV reali.
        for _o in bpy.context.view_layer.objects:
            try:
                _o.select_set(False)
            except Exception:
                pass
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="SELECT")
        assert bpy.ops.uv.smart_project(
            angle_limit=math.radians(66.0),
            island_margin=0.0,
            correct_aspect=True,
            scale_to_bounds=False,
        ) == {"FINISHED"}, "Smart UV Project fallito"
        bpy.ops.object.mode_set(mode="OBJECT")

        _active_uv = mesh.uv_layers.active
        if _active_uv is not None:
            try:
                _active_uv.name = uv_name
            except Exception:
                pass
        for _layer in list(mesh.uv_layers):
            if _layer == mesh.uv_layers.active:
                continue
            try:
                _all_zero = all(
                    float(_d.uv[0]) == 0.0 and float(_d.uv[1]) == 0.0
                    for _d in _layer.data
                )
            except Exception:
                _all_zero = False
            if _all_zero:
                try:
                    mesh.uv_layers.remove(_layer)
                except Exception:
                    pass
        uv_layer = mesh.uv_layers.active
        assert uv_layer is not None, "Nessun layer UV attivo dopo Smart UV Project"
        try:
            uv_layer.name = uv_name
        except Exception:
            pass

        loop_count = len(uv_layer.data)
        layer_count = len(mesh.uv_layers)
        assert loop_count > 0, "Layer UV senza loop"
        captured = [(float(_d.uv[0]), float(_d.uv[1])) for _d in uv_layer.data]

        # Modifica alcune coordinate UV a mano.
        for _i in range(min(4, loop_count)):
            assert utils.set_loop_uv(uv_layer, _i, 0.123456, 0.654321), (
                "set_loop_uv fallito al loop %d" % _i
            )
        modified = [(float(_d.uv[0]), float(_d.uv[1])) for _d in uv_layer.data]
        assert modified[0] != captured[0], "La modifica manuale non e' stata applicata"

        # Capture: registra lo stato modificato.
        ok, msgs = preview_mod.capture(mesh, uv_name)
        assert ok, "capture fallita: %s" % "; ".join(msgs)
        assert len(mesh.uv_layers) == layer_count + 1, (
            "capture non ha creato il backup UV (layer %d vs %d)"
            % (len(mesh.uv_layers), layer_count + 1)
        )

        # Modifica di nuovo.
        for _i in range(min(4, loop_count)):
            assert utils.set_loop_uv(uv_layer, _i, 0.987654, 0.321098), (
                "set_loop_uv fallito al loop %d" % _i
            )

        # Revert: ripristina lo stato catturato.
        ok_r, msgs_r = preview_mod.revert(mesh, uv_name)
        assert ok_r, "revert fallito: %s" % "; ".join(msgs_r)

        layer_after = mesh.uv_layers.get(uv_name)
        assert layer_after is not None, "revert ha rimosso il layer UV"
        assert len(layer_after.data) == loop_count, (
            "numero di loop cambiato dopo revert: %d vs %d"
            % (len(layer_after.data), loop_count)
        )
        assert len(mesh.uv_layers) == layer_count, (
            "numero di layer cambiato dopo revert: %d vs %d"
            % (len(mesh.uv_layers), layer_count)
        )
        after_coords = [(float(_d.uv[0]), float(_d.uv[1])) for _d in layer_after.data]
        assert len(after_coords) == len(modified), "numero di coordinate cambiato dopo revert"
        for _idx, (_a, _b) in enumerate(zip(after_coords, modified)):
            assert _a[0] == _b[0] and _a[1] == _b[1], (
                "coordinata loop %d non ripristinata: %s vs %s"
                % (_idx, _a, _b)
            )

        # Due capture consecutive non perdono lo stato della prima.
        first_state = list(modified)
        ok1, _ = preview_mod.capture(mesh, uv_name)
        assert ok1, "prima capture consecutiva fallita"
        ok2, _ = preview_mod.capture(mesh, uv_name)
        assert ok2, "seconda capture consecutiva fallita"
        for _i in range(min(4, loop_count)):
            utils.set_loop_uv(layer_after, _i, 0.111111, 0.222222)
        ok_r2, _ = preview_mod.revert(mesh, uv_name)
        assert ok_r2, "revert dopo due capture fallito"
        layer_final = mesh.uv_layers.get(uv_name)
        assert layer_final is not None, "layer rimosso dopo due capture"
        final_coords = [(float(_d.uv[0]), float(_d.uv[1])) for _d in layer_final.data]
        for _idx, (_a, _b) in enumerate(zip(final_coords, first_state)):
            assert _a[0] == _b[0] and _a[1] == _b[1], (
                "stato della prima capture perso al loop %d: %s vs %s"
                % (_idx, _a, _b)
            )
        assert len(mesh.uv_layers) == layer_count, (
            "numero di layer cambiato dopo due capture: %d vs %d"
            % (len(mesh.uv_layers), layer_count)
        )

        # Revert senza capture precedente: non solleva e non rovina le UV.
        assert not preview_mod.has_pending(mesh), "backup residuo prima del test senza capture"
        real_layer = mesh.uv_layers.get(uv_name)
        assert real_layer is not None, "layer UV reale assente"
        real_before = [(float(_d.uv[0]), float(_d.uv[1])) for _d in real_layer.data]
        real_layer_count = len(mesh.uv_layers)
        missing_name = uv_name + "_missing_layer"
        try:
            _ok_nc, _msgs_nc = preview_mod.revert(mesh, missing_name)
        except Exception as _exc:  # noqa: BLE001 - il revert non deve sollevare
            raise AssertionError("revert senza capture ha sollevato: %r" % _exc)
        real_after = [(float(_d.uv[0]), float(_d.uv[1])) for _d in real_layer.data]
        assert real_after == real_before, "revert senza capture ha modificato le UV"
        assert len(mesh.uv_layers) == real_layer_count, (
            "revert senza capture ha cambiato il numero di layer: %d vs %d"
            % (len(mesh.uv_layers), real_layer_count)
        )

        return (
            "loop=%d, layer=%d, ripristino esatto, due capture OK, "
            "revert senza capture OK" % (loop_count, layer_count)
        )
    finally:
        if obj is not None:
            _remove(obj)
        try:
            addon.unregister()
        except Exception:  # noqa: BLE001 - unregister di pulizia
            pass


if __name__ == "__main__":
    passed = 0
    failed = 0
    try:
        detail = test_preview()
        passed = 1
        print("CHECK test_preview PASS %s" % (detail or ""))
    except Exception:
        failed = 1
        traceback.print_exc()
    print("RISULTATO passati=%d falliti=%d totale=1" % (passed, failed))
