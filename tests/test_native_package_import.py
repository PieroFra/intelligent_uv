# -*- coding: utf-8 -*-
"""Standalone tests for a physical copy of the package without the RizomUV modules.

Contract enforced here:

  a) the three external-engine modules must be ABSENT FROM DISK in the copy,
     not merely skipped by an import hook;
  b) that copy must import under a unique name, register, expose its panel and
     operators, run the native path with use_rizomuv=True, then unregister.

The copy is what a native edition ships. Because the files do not exist, no
import hook is needed (or used) to prove they are never reached: absence on
disk is the condition under test.
"""

import importlib
import importlib.util
import os
import re
import shutil
import subprocess
import sys
import tempfile
import traceback

import bpy


COPY_NAME = "iuv_native_package_copy"
EXCLUDED = ("rizomuv_bridge.py", "rizomuv_link.py", "rizomuv_script.py")
SKIPPED_DIRS = ("__pycache__", "tests", "_esperimenti", ".git", ".opencode",
                "dist", "docs")


def package_root():
    """Absolute path of the add-on package (the parent of tests/)."""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _ignore(directory, names):
    """copytree filter: drops the external modules and anything not shipped."""
    del directory
    return {name for name in names
            if name in EXCLUDED or name in SKIPPED_DIRS}


def make_copy():
    """Copies the package without the RizomUV modules into a temporary dir."""
    root = package_root()
    missing = [name for name in EXCLUDED
               if not os.path.isfile(os.path.join(root, name))]
    assert not missing, (
        "Il progetto non contiene i moduli da escludere, il test non prova "
        "nulla: " + repr(missing))

    temp_dir = tempfile.mkdtemp(prefix="iuv_native_copy_")
    copy_path = os.path.join(temp_dir, COPY_NAME)
    shutil.copytree(root, copy_path, ignore=_ignore)

    # The native packaging pins the capability off inside the artifact: the
    # copy must carry the same written False, not a runtime monkeypatch.
    cap_path = os.path.join(copy_path, "capabilities.py")
    with open(cap_path, "r", encoding="utf-8") as handle:
        source = handle.read()
    pattern = r"(?m)^EXTERNAL_ENGINE_ENABLED[ \t]*=.*$"
    assert len(re.findall(pattern, source)) == 1, (
        "capabilities.py della copia non espone il flag da pinnare: "
        + cap_path)
    patched = re.sub(pattern, "EXTERNAL_ENGINE_ENABLED = False", source)
    with open(cap_path, "w", encoding="utf-8") as handle:
        handle.write(patched)
    return temp_dir, copy_path


def remove_tree(path):
    shutil.rmtree(path, ignore_errors=True)


def external_files(root):
    """Every rizomuv_* file still on disk under root, source or compiled."""
    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        del dirnames
        for name in filenames:
            if name.startswith("rizomuv"):
                found.append(os.path.join(dirpath, name))
    return sorted(found)


def purge_package(name):
    """Drops the copied package from sys.modules so the next import is clean."""
    for module_name in [n for n in list(sys.modules)
                        if n == name or n.startswith(name + ".")]:
        del sys.modules[module_name]


def external_modules(name):
    """External-engine modules loaded under the copied package namespace."""
    prefix = name + "."
    return sorted(
        n for n in list(sys.modules)
        if n.startswith(prefix) and n.rsplit(".", 1)[-1].startswith("rizomuv"))


def rna_identifier(cls):
    """RNA identifier of a class: it exists only if Blender registered it."""
    rna = getattr(cls, "bl_rna", None)
    assert rna is not None, "Classe non registrata: " + cls.__name__
    return rna.identifier


def test_copy_has_no_external_engine_files():
    temp_dir, copy_path = make_copy()
    try:
        leftovers = external_files(copy_path)
        assert not leftovers, (
            "La copia contiene ancora moduli esterni: " + repr(leftovers))
        for name in EXCLUDED:
            assert not os.path.exists(os.path.join(copy_path, name)), (
                "File escluso ancora presente nella copia: " + name)
            assert os.path.isfile(os.path.join(package_root(), name)), (
                "File originale assente, esclusione non verificabile: " + name)
    finally:
        remove_tree(temp_dir)
    assert not os.path.exists(temp_dir), "Directory temporanea non rimossa"


def test_copied_package_registers_and_runs_native():
    temp_dir, copy_path = make_copy()
    module = None
    cube = None
    launches = []
    original_popen = subprocess.Popen
    original_system = os.system

    def refuse_launch(*args, **kwargs):
        launches.append(args[0] if args else kwargs.get("args"))
        raise AssertionError("Avvio di un processo esterno dalla copia nativa")

    try:
        assert not external_files(copy_path), (
            "La copia contiene ancora moduli esterni: "
            + repr(external_files(copy_path)))

        sys.path.insert(0, temp_dir)
        module = importlib.import_module(COPY_NAME)
        assert os.path.abspath(module.__file__).startswith(copy_path + os.sep), (
            "Importata una copia diversa da quella temporanea: "
            + module.__file__)
        capabilities = importlib.import_module(COPY_NAME + ".capabilities")
        assert capabilities.EXTERNAL_ENGINE_ENABLED is False, (
            "La copia non e' l'edizione nativa: EXTERNAL_ENGINE_ENABLED deve "
            "essere False")
        for name in EXCLUDED:
            module_name = COPY_NAME + "." + name[:-3]
            assert importlib.util.find_spec(module_name) is None, (
                "Il modulo esterno e' ancora importabile dalla copia: "
                + module_name)
        assert not external_modules(COPY_NAME), (
            "Moduli esterni caricati prima di register(): "
            + repr(external_modules(COPY_NAME)))

        module.register()
        assert hasattr(bpy.types.Scene, "intelligent_uv_settings"), (
            "register() non ha agganciato intelligent_uv_settings alla Scene")
        assert rna_identifier(module.VIEW3D_PT_IntelligentUV) == (
            "VIEW3D_PT_intelligent_uv"), (
            "Il pannello non e' registrato con il suo identificatore RNA")
        for cls in module.CLASSES:
            assert rna_identifier(cls), "Classe non registrata: " + cls.__name__
        run_cls = module.IntelligentUV_OT_Run
        assert run_cls.bl_idname == "intelligent_uv.run", (
            "L'operatore Run non ha il bl_idname atteso")
        assert rna_identifier(run_cls) == bpy.ops.intelligent_uv.run.idname(), (
            "L'operatore Run non e' registrato in bpy.ops")
        assert not external_modules(COPY_NAME), (
            "register() ha caricato moduli esterni: "
            + repr(external_modules(COPY_NAME)))

        subprocess.Popen = refuse_launch
        os.system = refuse_launch
        for obj in list(bpy.context.scene.objects):
            obj.select_set(False)
        bpy.ops.mesh.primitive_cube_add(size=2.0, location=(0.0, 0.0, 0.0))
        cube = bpy.context.view_layer.objects.active
        assert cube is not None and cube.type == 'MESH', "Cubo di prova non creato"

        settings = bpy.context.scene.intelligent_uv_settings
        settings.use_rizomuv = True
        # An existing executable path used to open the external engine: the
        # native copy must ignore it instead of launching it.
        settings.rizomuv_path = bpy.app.binary_path
        assert os.path.isfile(settings.rizomuv_path), (
            "Serve un percorso esistente per provare che il motore non parte")

        module.IntelligentUV_OT_Run._busy = False
        result = bpy.ops.intelligent_uv.run()
        assert result == {'FINISHED'}, (
            "use_rizomuv=True non ha chiuso il percorso nativo: " + repr(result))
        assert not launches, "Processo esterno avviato: " + repr(launches)
        assert not external_modules(COPY_NAME), (
            "Il percorso nativo ha caricato moduli esterni: "
            + repr(external_modules(COPY_NAME)))
        assert module.IntelligentUV_OT_Run._busy is False, (
            "Il flag busy di Run e' rimasto alzato dopo il percorso nativo")

        layer_name = str(getattr(settings, "uv_layer_name", "SmartUV") or "SmartUV")
        assert cube.data.uv_layers.get(layer_name) is not None, (
            "Il percorso nativo non ha scritto il layer UV " + layer_name)

        module.unregister()
        assert not hasattr(bpy.types.Scene, "intelligent_uv_settings"), (
            "unregister() ha lasciato intelligent_uv_settings sulla Scene")
        module = None
    finally:
        subprocess.Popen = original_popen
        os.system = original_system
        if cube is not None:
            bpy.data.objects.remove(cube, do_unlink=True)
        if module is not None:
            module.IntelligentUV_OT_Run._busy = False
            try:
                module.unregister()
            except Exception:
                # A: a half registration is already being torn down and this
                # path only runs when an assertion above already failed.
                pass
        purge_package(COPY_NAME)
        if temp_dir in sys.path:
            sys.path.remove(temp_dir)
        remove_tree(temp_dir)
    assert not os.path.exists(temp_dir), "Directory temporanea non rimossa"


def main():
    tests = (test_copy_has_no_external_engine_files,
             test_copied_package_registers_and_runs_native)
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
