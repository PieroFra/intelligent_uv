# -*- coding: utf-8 -*-
"""Standalone contract tests for the pure native capabilities module."""

import builtins
import importlib
import importlib.util
from pathlib import Path
import traceback


MODULE_PATH = Path(__file__).resolve().parents[1] / "capabilities.py"


def load_capabilities():
    """Load only capabilities.py, blocking even cached forbidden imports."""
    assert MODULE_PATH.is_file(), "Modulo capabilities.py assente: contratto non implementato"
    attempted = []
    original_import = builtins.__import__
    original_import_module = importlib.import_module

    def guard(name):
        parts = name.lower().split(".")
        forbidden = any(
            part == "bpy" or any(token in part for token in (
                "discovery", "bridge", "link", "script", "rizom"))
            for part in parts)
        if forbidden:
            attempted.append(name)
            raise AssertionError("Import vietato nel modulo puro: " + name)

    def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
        guard(name)
        for item in fromlist or ():
            guard(item)
        return original_import(name, globals, locals, fromlist, level)

    def guarded_import_module(name, package=None):
        guard(name)
        return original_import_module(name, package)

    spec = importlib.util.spec_from_file_location(
        "_native_capabilities_contract", MODULE_PATH)
    assert spec is not None and spec.loader is not None, "Spec del modulo puro non disponibile"
    module = importlib.util.module_from_spec(spec)
    try:
        builtins.__import__ = guarded_import
        importlib.import_module = guarded_import_module
        spec.loader.exec_module(module)
    finally:
        builtins.__import__ = original_import
        importlib.import_module = original_import_module
    assert not attempted, "Dipendenze vietate tentate, anche se intercettate: " + repr(attempted)
    return module


def test_pure_import():
    module = load_capabilities()
    assert Path(module.__file__).resolve() == MODULE_PATH, "Importato un modulo diverso da capabilities.py"
    assert module.__package__ == "", "Il caricamento non deve eseguire il package addon"


def test_external_engine_enabled_in_full_build():
    module = load_capabilities()
    assert hasattr(module, "EXTERNAL_ENGINE_ENABLED"), "Flag EXTERNAL_ENGINE_ENABLED assente"
    assert module.EXTERNAL_ENGINE_ENABLED is True, "Engine esterno non abilitato nella build completa"


def test_external_engine_plain_boolean():
    module = load_capabilities()
    assert "EXTERNAL_ENGINE_ENABLED" in vars(module), "Il flag deve essere un valore fisso del modulo"
    assert type(vars(module)["EXTERNAL_ENGINE_ENABLED"]) is bool, "Il flag deve essere bool Python, non RNA o descriptor"


def main():
    tests = (test_pure_import, test_external_engine_enabled_in_full_build,
             test_external_engine_plain_boolean)
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
