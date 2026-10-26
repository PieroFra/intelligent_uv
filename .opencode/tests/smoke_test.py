# -*- coding: utf-8 -*-
"""Smoke test headless di Intelligent UV Mapping.

Verifica che il package compili, si importi, si registri e si deregistri senza errori, e che
pannello, operatori e proprieta' esposte esistano davvero. Il controllo `pannello` disegna
`VIEW3D_PT_IntelligentUV` e `IntelligentUV_OT_ShowInfo` su uno spy layout con lingua
impostata su italiano e prova che `_EnglishLayout` (`ui.py`) passi `translate=False` a ogni
chiamata e inietti il nome RNA inglese nelle property prive di `text=`. Non tocca la pipeline UV.

Uso:
    blender --factory-startup --background --python .opencode/tests/smoke_test.py

Ultima riga dell'output: RISULTATO passati=X falliti=Y totale=N
"""

import importlib
import os
import sys
from pathlib import Path
from types import MethodType, SimpleNamespace

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


class _SpyOp:
    """Operatore finto restituito dallo spy layout: registra gli attributi
    assegnati dopo la chiamata (url, preset_name, ...)."""

    def __init__(self):
        object.__setattr__(self, "attrs", {})

    def __setattr__(self, name, value):
        self.attrs[name] = value


class _SpyLayout:
    """Layout finto: registra ogni chiamata per ispezionare args e kwargs.

    Il pannello reale disegna su questo spy tramite _EnglishLayout, quindi
    quello che viene registrato e' esattamente cio' che il proxy passa al
    layout vero: se `translate=False` manca o il testo non e' quello atteso,
    pannello e popup tradiscono l'inglese con una lingua non inglese attiva.
    """

    _TEXT = ("label", "prop", "operator", "menu", "prop_enum",
             "prop_menu_enum", "props_enum", "prop_search",
             "operator_menu_enum", "popover")
    _CONTAINERS = ("row", "column", "box", "split", "grid_flow",
                   "column_flow", "menu_pie")

    def __init__(self, calls, raise_on=None):
        object.__setattr__(self, "_calls", calls)
        object.__setattr__(self, "_raise", raise_on or ())

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        calls = self._calls
        if name in self._CONTAINERS:
            def make(*args, **kwargs):
                calls.append((name, args, dict(kwargs), None))
                return _SpyLayout(calls, self._raise)
            return make
        if name in self._TEXT:
            def draw(*args, **kwargs):
                # serve a provare il fallback del proxy quando il layout
                # vero rifiuta la keyword `translate` con un TypeError
                if name in self._raise and "translate" in kwargs:
                    raise TypeError(
                        "{0}() unexpected keyword 'translate'".format(name))
                result = _SpyOp()
                calls.append((name, args, dict(kwargs), result))
                return result
            return draw
        return lambda *args, **kwargs: None


def _require_english_calls(calls, tag):
    """Firma della UI inglese: translate=False su ogni chiamata testuale."""
    for name, _args, kwargs, _result in calls:
        if name in _SpyLayout._TEXT and kwargs.get("translate") is not False:
            raise AssertionError(
                "{0}: {1}() senza translate=False: {2!r}".format(
                    tag, name, sorted(kwargs)))


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

    # Il popup dei credits deve stare in CLASSES e registrato davvero.
    info = None
    for candidate in package().CLASSES:
        if candidate.__name__ == "IntelligentUV_OT_ShowInfo":
            info = candidate
            break
    if info is None:
        raise AttributeError("IntelligentUV_OT_ShowInfo assente da CLASSES")
    info_id = _rna_name(info)
    if info.bl_idname != "intelligent_uv.show_info":
        raise ValueError("bl_idname inatteso: {0}".format(info.bl_idname))

    # Pannello e popup disegnati su uno spy layout con lingua italiana:
    # _EnglishLayout deve forzare translate=False su ogni chiamata e dare alle
    # property senza text= il nome RNA inglese.
    prefs = bpy.context.preferences
    previous_lang = prefs.view.language
    previous_translate = prefs.view.use_translate_interface
    settings = _scene_settings()
    previous_advanced = settings.show_advanced
    calls = []
    try:
        prefs.view.language = 'it_IT'
        prefs.view.use_translate_interface = True
        settings.show_advanced = True
        stub = SimpleNamespace(layout=_SpyLayout(calls))
        # `_draw_advanced` e' un metodo della classe pannello e non usa `self`:
        # legato al puntatore via MethodType perche' panel.draw lo richiami
        # come un metodo normale.
        stub._draw_advanced = MethodType(cls._draw_advanced, stub)
        cls.draw(stub, bpy.context)
        info.draw(SimpleNamespace(layout=_SpyLayout(calls)), bpy.context)
    finally:
        settings.show_advanced = previous_advanced
        prefs.view.language = previous_lang
        prefs.view.use_translate_interface = previous_translate

    _require_english_calls(calls, "pannello/_EnglishLayout")
    for prop_id, expected in (("show_advanced", "Advanced"),
                              ("auto_parameters", "Automatic")):
        hits = [kwargs for name, args, kwargs, _r in calls
                if name == "prop" and len(args) >= 2 and args[1] == prop_id]
        if not hits:
            raise AssertionError("prop '{0}' mai disegnata".format(prop_id))
        if any(kwargs.get("text") != expected for kwargs in hits):
            raise AssertionError(
                "prop '{0}' senza text='{1}' iniettato: {2!r}".format(
                    prop_id, expected, [sorted(k) for k in hits]))
    return "tab '{0}' come {1}, popup {2}, {3} chiamate inglese".format(
        cls.bl_category, identifier, info_id, len(calls))


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
