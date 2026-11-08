# -*- coding: utf-8 -*-
"""Standalone isolation tests for the native edition: no rizomuv_* import.

The contract enforced here, with capabilities.EXTERNAL_ENGINE_ENABLED pinned
to False at runtime (the native ZIP writes that value on disk):

  a) importing and registering the add-on must not import rizomuv_bridge,
     rizomuv_link or rizomuv_script;
  b) a legacy scene with use_rizomuv=True must still complete the native
     path, without errors and without launching an external process.

The sentinel lives on sys.meta_path and raises on every attempt, so a module
that wraps the import in try/except ImportError cannot hide it either.
"""

import importlib
import os
import subprocess
import sys
import traceback

import bpy


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(ROOT))
PACKAGE = os.path.basename(ROOT)
BLOCKED = "rizomuv"


class RizomUVImportSentinel:
    """Meta path finder that fails on every rizomuv_* import."""

    def __init__(self):
        self.attempts = []

    def find_spec(self, fullname, path=None, target=None):
        leaf = fullname.rsplit(".", 1)[-1]
        if leaf.startswith(BLOCKED):
            self.attempts.append(fullname)
            raise AssertionError(
                "L'edizione nativa ha importato un motore esterno: " + fullname)
        return None


def loaded_external_modules():
    """Names of the external-engine modules currently in sys.modules."""
    return sorted(
        name for name in list(sys.modules)
        if name.rsplit(".", 1)[-1].startswith(BLOCKED)
    )


def purge_package():
    """Drops the add-on package from sys.modules so the next import is clean."""
    for name in [n for n in list(sys.modules)
                 if n == PACKAGE or n.startswith(PACKAGE + ".")]:
        del sys.modules[name]


def remove_sentinel(sentinel):
    if sentinel in sys.meta_path:
        sys.meta_path.remove(sentinel)


def load_native_addon():
    """
    Imports and registers the add-on with every rizomuv_* import blocked.

    Returns (module, sentinel). The sentinel stays on sys.meta_path until
    release_native_addon(): the run must not import the engine either.
    """
    preloaded = loaded_external_modules()
    assert not preloaded, (
        "Moduli esterni gia' in sys.modules prima del test, il contratto non "
        "e' misurabile: " + repr(preloaded))

    sentinel = RizomUVImportSentinel()
    purge_package()
    sys.meta_path.insert(0, sentinel)

    try:
        module = importlib.import_module(PACKAGE)
    except Exception:
        remove_sentinel(sentinel)
        purge_package()
        raise

    # The full build ships the capability on; the native contract is proven by
    # pinning it off at runtime, exactly as the native ZIP does on disk.
    capabilities = sys.modules.get(PACKAGE + ".capabilities")
    assert capabilities is not None, "Il package non ha importato capabilities"
    capabilities.EXTERNAL_ENGINE_ENABLED = False

    try:
        module.register()
    except Exception:
        remove_sentinel(sentinel)
        try:
            module.unregister()
        except Exception:
            # A: a half registration is still better torn down on a best-effort
            # basis than left behind in the failing process.
            pass
        purge_package()
        raise

    return module, sentinel


def release_native_addon(module, sentinel):
    """Unregisters the add-on, unlocks Run, drops the sentinel and the cache."""
    try:
        module.IntelligentUV_OT_Run._busy = False
    except Exception:
        # A: the class is only needed to clear the flag; a missing one cannot
        # be left busy.
        pass
    try:
        module.unregister()
    except Exception:
        # A: the process ends after the suite; a failed teardown must not hide
        # the result of the assertions that already ran.
        pass
    remove_sentinel(sentinel)
    purge_package()


def test_import_and_register_without_external_engine():
    module, sentinel = load_native_addon()
    try:
        capabilities = importlib.import_module(PACKAGE + ".capabilities")
        assert capabilities.EXTERNAL_ENGINE_ENABLED is False, (
            "Il test presuppone l'edizione nativa: EXTERNAL_ENGINE_ENABLED "
            "deve essere False")
        assert sys.modules.get(PACKAGE) is module, (
            "Il package importato non e' quello sotto test")
        assert os.path.abspath(module.__file__).startswith(ROOT + os.sep), (
            "Importato un package diverso da quello del progetto")
        assert not sentinel.attempts, (
            "Import esterni tentati da import/register: " + repr(sentinel.attempts))
        leftovers = loaded_external_modules()
        assert not leftovers, (
            "Moduli esterni caricati da import/register: " + repr(leftovers))
        assert hasattr(bpy.types.Scene, "intelligent_uv_settings"), (
            "register() non ha agganciato intelligent_uv_settings alla Scene")
    finally:
        release_native_addon(module, sentinel)


def test_legacy_use_rizomuv_true_stays_native():
    module, sentinel = load_native_addon()
    launches = []
    original_popen = subprocess.Popen
    original_system = os.system
    original_startfile = getattr(os, "startfile", None)
    cube = None

    def refuse_launch(*args, **kwargs):
        launches.append(args[0] if args else kwargs.get("args"))
        raise AssertionError("Avvio di un processo esterno in edizione nativa")

    try:
        subprocess.Popen = refuse_launch
        os.system = refuse_launch
        if original_startfile is not None:
            os.startfile = refuse_launch

        for obj in list(bpy.context.scene.objects):
            obj.select_set(False)
        bpy.ops.mesh.primitive_cube_add(size=2.0, location=(0.0, 0.0, 0.0))
        cube = bpy.context.view_layer.objects.active
        assert cube is not None and cube.type == 'MESH', "Cubo di prova non creato"

        settings = bpy.context.scene.intelligent_uv_settings
        settings.use_rizomuv = True
        # An existing executable path is what used to open the external engine:
        # with the native edition it must be ignored, not launched.
        settings.rizomuv_path = bpy.app.binary_path
        assert os.path.isfile(settings.rizomuv_path), (
            "Serve un percorso esistente per provare che il motore non parte")

        module.IntelligentUV_OT_Run._busy = False
        result = bpy.ops.intelligent_uv.run()

        assert result == {'FINISHED'}, (
            "use_rizomuv=True non ha chiuso il percorso nativo: " + repr(result))
        assert not launches, "Processo esterno avviato: " + repr(launches)
        assert not sentinel.attempts, (
            "Import esterni durante l'esecuzione: " + repr(sentinel.attempts))
        assert not loaded_external_modules(), (
            "Moduli esterni caricati durante l'esecuzione: "
            + repr(loaded_external_modules()))
        assert module.IntelligentUV_OT_Run._busy is False, (
            "Il flag busy di Run e' rimasto alzato dopo il percorso nativo")

        layer_name = str(getattr(settings, "uv_layer_name", "SmartUV") or "SmartUV")
        assert cube.data.uv_layers.get(layer_name) is not None, (
            "Il percorso nativo non ha scritto il layer UV " + layer_name)
    finally:
        subprocess.Popen = original_popen
        os.system = original_system
        if original_startfile is not None:
            os.startfile = original_startfile
        if cube is not None:
            bpy.data.objects.remove(cube, do_unlink=True)
        release_native_addon(module, sentinel)


def main():
    tests = (test_import_and_register_without_external_engine,
             test_legacy_use_rizomuv_true_stays_native)
    passed = 0
    for test in tests:
        try:
            test()
        except Exception:
            print("FAIL " + test.__name__)
            traceback.print_exc()
        else:
            passed += 1
            print("PASS " + test.__name__)
    print("RISULTATO passati={} falliti={} totale={}".format(
        passed, len(tests) - passed, len(tests)))


if __name__ == "__main__":
    main()
