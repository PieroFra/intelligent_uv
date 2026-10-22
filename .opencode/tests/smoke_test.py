# -*- coding: utf-8 -*-
"""Smoke test headless di Intelligent UV Mapping.

Verifica che il package compili, si importi, si registri e si deregistri senza errori, e che
pannello, operatori e proprieta' esposte esistano davvero. Non tocca la pipeline UV.

Uso:
    blender --factory-startup --background --python .opencode/tests/smoke_test.py

Ultima riga dell'output: RISULTATO passati=X falliti=Y totale=N
"""

import importlib
import os
import sys
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))      # .opencode\tests -> .opencode -> radice
PACKAGE = os.path.basename(ROOT)
sys.path.insert(0, os.path.dirname(ROOT))

import bpy  # noqa: E402  (deve venire dopo la preparazione di sys.path)

STATE = {}
RESULTS = []

# Proprieta' usata per provare che i valori sopravvivono a un secondo register().
SNAPSHOT_PROP = "curvature_threshold"
SNAPSHOT_VALUE = 42.0


def check(name, fn):
    """Esegue un controllo e registra l'esito senza interrompere gli altri."""
    try:
        detail = fn()
        RESULTS.append((name, True, detail or ""))
    except Exception as exc:  # noqa: BLE001 - un controllo rotto non deve fermare il resto
        RESULTS.append((name, False, "{0}: {1}".format(type(exc).__name__, exc)))


def package():
    mod = STATE.get("mod")
    if mod is None:
        raise RuntimeError("package non importato")
    return mod


# --- controlli -----------------------------------------------------------------

def do_compile():
    """Compila ogni modulo senza scrivere .pyc (sintassi e indentazione)."""
    broken = []
    for path in sorted(Path(ROOT).rglob("*.py")):
        parts = set(path.relative_to(ROOT).parts)
        if ".opencode" in parts or "__pycache__" in parts:
            continue
        try:
            with open(path, "r", encoding="utf-8") as handle:
                compile(handle.read(), str(path), "exec")
        except SyntaxError as exc:
            broken.append("{0}:{1} {2}".format(path.name, exc.lineno, exc.msg))
    if broken:
        raise RuntimeError(" | ".join(broken[:3]))
    return "moduli compilati"


def do_import():
    importlib.invalidate_caches()
    STATE["mod"] = importlib.import_module(PACKAGE)
    return "versione {0}".format(".".join(str(n) for n in STATE["mod"].bl_info["version"]))


def do_bl_info():
    info = package().bl_info
    for key in ("name", "version", "blender", "category"):
        if key not in info:
            raise KeyError("bl_info senza '{0}'".format(key))
    if info["category"] != "UV":
        raise ValueError("categoria inattesa: {0}".format(info["category"]))
    return "{0} / categoria {1}".format(info["name"], info["category"])


def do_register():
    package().register()
    return "register() eseguito"


def do_pointer():
    settings = _scene_settings()
    return "puntatore presente"


def _scene_settings():
    """Restituisce il PropertyGroup della scena o solleva se il puntatore manca."""
    if not hasattr(bpy.types.Scene, "intelligent_uv_settings"):
        raise AttributeError("Scene.intelligent_uv_settings assente")
    settings = bpy.context.scene.intelligent_uv_settings
    if settings is None:
        raise ValueError("il puntatore sulla scena e' vuoto")
    return settings


def _rna_name(cls):
    """Nome RNA della classe: esiste solo se Blender l'ha davvero registrata.

    Gli operatori dichiarano `bl_idname` espliciti (INTELLIGENT_UV_OT_*), quindi il nome
    della classe Python non compare in `bpy.types`: l'identificatore RNA e' la prova vera.
    """
    rna = getattr(cls, "bl_rna", None)
    if rna is None:
        raise AttributeError("{0} non registrata".format(cls.__name__))
    return rna.identifier


def do_classes():
    broken = []
    for cls in package().CLASSES:
        try:
            _rna_name(cls)
        except AttributeError as exc:
            broken.append(str(exc))
    if broken:
        raise AttributeError("; ".join(broken))
    return "{0} classi".format(len(package().CLASSES))


def do_panel():
    cls = None
    for candidate in package().CLASSES:
        if candidate.__name__ == "VIEW3D_PT_IntelligentUV":
            cls = candidate
            break
    if cls is None:
        raise AttributeError("pannello assente da CLASSES")
    identifier = _rna_name(cls)
    if cls.bl_category != "Intelligent UV":
        raise ValueError("bl_category inattesa: {0}".format(cls.bl_category))
    if cls.bl_space_type != "VIEW_3D":
        raise ValueError("bl_space_type inatteso: {0}".format(cls.bl_space_type))
    return "tab '{0}' come {1}".format(cls.bl_category, identifier)


def do_operators():
    operators = [c for c in package().CLASSES if c.__name__.startswith("IntelligentUV_OT_")]
    if len(operators) < 5:
        raise ValueError("solo {0} operatori in CLASSES".format(len(operators)))
    for cls in operators:
        _rna_name(cls)
    return "{0} operatori".format(len(operators))


def do_properties():
    settings = bpy.context.scene.intelligent_uv_settings
    total = len(settings.bl_rna.properties)
    if total < 10:
        raise ValueError("solo {0} proprieta' esposte".format(total))
    return "{0} proprieta'".format(total)


def do_unregister():
    package().unregister()
    return "unregister() eseguito"


def do_pointer_removed():
    if hasattr(bpy.types.Scene, "intelligent_uv_settings"):
        raise AttributeError("Scene.intelligent_uv_settings non rimosso")
    return "puntatore rimosso"


def do_double_register():
    """register() due volte di fila: la scena deve conservare il suo PropertyGroup.

    Il secondo register() sostituisce le classi (e quindi il PropertyGroup) mentre
    l'RNA della scena punta ancora alle vecchie: se il puntatore non viene
    riagganciato, `Scene.intelligent_uv_settings` sparisce e ogni accesso
    successivo solleva AttributeError. Il controllo parte da addon deregistrato e
    ripulisce con unregister() anche quando fallisce, cosi' i controlli seguenti
    trovano sempre una scena pulita.
    """
    mod = package()
    failure = ""
    try:
        mod.register()
        _scene_settings().curvature_threshold = SNAPSHOT_VALUE
        mod.register()
        settings = _scene_settings()
        if not any(p.identifier == SNAPSHOT_PROP for p in settings.bl_rna.properties):
            raise AttributeError(
                "proprieta' '{0}' assente dopo il secondo register()".format(SNAPSHOT_PROP)
            )
        value = getattr(settings, SNAPSHOT_PROP)
        if abs(value - SNAPSHOT_VALUE) > 1e-6:
            raise ValueError(
                "'{0}' non conservata: {1}".format(SNAPSHOT_PROP, value)
            )
    except Exception as exc:  # noqa: BLE001 - l'esito va riportato, non propagato
        failure = "{0}: {1}".format(type(exc).__name__, exc)
    finally:
        try:
            mod.unregister()
        except Exception as exc:  # noqa: BLE001 - la pulizia non deve mascherare l'esito
            failure = failure or "unregister: {0}: {1}".format(type(exc).__name__, exc)
        if hasattr(bpy.types.Scene, "intelligent_uv_settings"):
            failure = failure or "unregister non ha rimosso Scene.intelligent_uv_settings"
    if failure:
        raise RuntimeError(failure)
    return "puntatore e proprieta' conservati, scena ripulita"


check("compilazione", do_compile)
check("import", do_import)
check("bl_info", do_bl_info)
check("register", do_register)
check("scene_pointer", do_pointer)
check("classi", do_classes)
check("pannello", do_panel)
check("operatori", do_operators)
check("proprieta", do_properties)
check("unregister", do_unregister)
check("pointer_rimosso", do_pointer_removed)
check("doppio_register", do_double_register)
check("re-register", do_register)
check("unregister_finale", do_unregister)

print("SMOKE addon={0} blender={1}".format(PACKAGE, bpy.app.version_string))
for name, passed, detail in RESULTS:
    print("CHECK {0} {1} {2}".format(name, "PASS" if passed else "FAIL", detail))

passed = sum(1 for _, ok, _ in RESULTS if ok)
failed = len(RESULTS) - passed
print("RISULTATO passati={0} falliti={1} totale={2}".format(passed, failed, len(RESULTS)))
