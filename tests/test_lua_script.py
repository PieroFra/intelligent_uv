# -*- coding: utf-8 -*-
"""Invarianti sul testo generato da rizomuv_script.build_lua_script."""

import os
import re
import sys
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

try:
    import rizomuv_script
except Exception:
    import importlib

    if os.path.dirname(ROOT) not in sys.path:
        sys.path.insert(0, os.path.dirname(ROOT))
    rizomuv_script = importlib.import_module(
        os.path.basename(ROOT) + ".rizomuv_script")


def test_contains_both_paths():
    export_path = r"C:\work\export_mesh.fbx"
    import_path = r"C:\work\import_mesh.fbx"
    script = rizomuv_script.build_lua_script(export_path, import_path, 0.0123)
    assert rizomuv_script.to_lua_path(export_path) in script, (
        "Il path di export non compare nel script generato")
    assert rizomuv_script.to_lua_path(import_path) in script, (
        "Il path di import non compare nel script generato")


def test_margin_px_changes_result():
    base = rizomuv_script.build_lua_script("a.fbx", "b.fbx", 0.01)
    with_px = rizomuv_script.build_lua_script(
        "a.fbx", "b.fbx", 0.01, texture_resolution=1024, margin_px=4)
    assert base != with_px, (
        "texture_resolution+margin_px non cambiano il risultato rispetto a "
        "margin_uv da solo")
    assert "Value=4" in with_px, (
        "Il margine in pixel non compare nel script generato")


def test_windows_backslashes_safe():
    export_path = r"C:\Users\name\my folder\export.fbx"
    import_path = r"D:\out\sub dir\import.fbx"
    script = rizomuv_script.build_lua_script(export_path, import_path, 0.02)
    assert script.count('"') % 2 == 0, (
        "Virgolette non bilanciate nel script Lua")
    invalid = re.findall(r'\\(?!\\|"|n|r|t|[0-7]{3})', script)
    assert not invalid, (
        "Sequenze di escape invalide nel script Lua: " + repr(invalid))


def test_deterministic():
    a = rizomuv_script.build_lua_script(
        "x.fbx", "y.fbx", 0.03, texture_resolution=512, margin_px=2)
    b = rizomuv_script.build_lua_script(
        "x.fbx", "y.fbx", 0.03, texture_resolution=512, margin_px=2)
    assert a == b, "Due chiamate uguali danno testo diverso"


def test_margin_px_none_valid():
    script = rizomuv_script.build_lua_script(
        "x.fbx", "y.fbx", 0.03, margin_px=None)
    assert "None" not in script, "Il script contiene 'None'"
    assert script.strip() != "", "Il script generato e' vuoto"
    assert script.count('"') % 2 == 0, "Virgolette non bilanciate nel script Lua"


if __name__ == "__main__":
    tests = (
        test_contains_both_paths,
        test_margin_px_changes_result,
        test_windows_backslashes_safe,
        test_deterministic,
        test_margin_px_none_valid,
    )
    passed = failed = 0
    for test in tests:
        try:
            test()
            passed += 1
        except Exception:
            failed += 1
            traceback.print_exc()
    print("RISULTATO passati={} falliti={} totale={}".format(
        passed, failed, len(tests)))