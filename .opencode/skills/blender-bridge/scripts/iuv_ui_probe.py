# -*- coding: utf-8 -*-
"""Lettura diretta e deterministica della UI di Intelligent UV Mapping.

Eseguito DENTRO Blender dal bridge TCP (`__name__ == "__bridge__"`).

Metodo (lo stesso collaudato su A.C.T.D.):

  1. carica l'addon, imposta la lingua, prepara una scena neutra;
  2. misura la larghezza reale della regione UI nella sidebar viva;
  3. estrae dal sorgente le etichette davvero disegnate (AST: `label`, `prop`,
     `operator` con `text=`) e i nomi UI delle property;
  4. misura ogni testo in pixel con `blf.dimensions` e lo confronta con lo
     spazio disponibile: il troncamento diventa un dato, non un'ipotesi;
  5. calcola la larghezza minima sicura della sidebar;
  6. ritaglia la sidebar dagli screenshot e la scala a max 1024 px (IT + EN).

Solo `bpy`, `blf` e `numpy` (forniti da Blender).
"""

import ast
import importlib
import os
import sys
import tempfile
import time
from pathlib import Path

import bpy

MODULE = "intelligent_uv"
SETTINGS_ATTR = "intelligent_uv_settings"
OUT_DIR = os.environ.get("IUV_GUI_OUT") or str(
    Path(tempfile.gettempdir()) / "opencode" / "iuv_gui"
)
LANGS = ("it", "en")
LANG_CODES = {"it": "it_IT", "en": "en_US"}

MARGIN = 24.0          # px di margine laterale della regione UI
MAX_WIDTH = 1024       # larghezza massima dei PNG finali
PANEL_MIN_WIDTH = 520  # larghezza desiderata della sidebar
PANEL_CATEGORIES = ("Intelligent UV",)

REPORT = []


def _say(line):
    REPORT.append(line)
    print(line)


# --- radice del progetto -------------------------------------------------------
def _project_root():
    """Cartella che contiene `ui.py` e `__init__.py` dell'addon."""
    override = os.environ.get("IUV_PROJECT_ROOT")
    if override:
        return Path(override).resolve()
    main_file = getattr(sys.modules.get("__main__"), "__file__", None)
    start = Path(main_file).resolve().parent if main_file else Path.cwd()
    for candidate in (start, *start.parents):
        if (candidate / "ui.py").is_file() and (candidate / "__init__.py").is_file():
            return candidate
    return start


ROOT = _project_root()


# --- caricamento ---------------------------------------------------------------
_STATE = {"module": None}


def _load_addon():
    """Importa e registra l'addon UNA volta sola.

    Richiamare `register()` due volte non e' sicuro: la guardia dell'addon cerca le
    classi con `cls.__name__`, ma gli operatori sono registrati col `bl_idname`,
    quindi non le riconosce, non le deregistra e la seconda registrazione fallisce
    lasciando la scena senza il puntatore alle impostazioni.
    """
    if _STATE["module"] is not None:
        return _STATE["module"]

    parent = str(ROOT.parent)
    if parent not in sys.path:
        sys.path.insert(0, parent)
    module = importlib.import_module(MODULE)
    module.register()
    _STATE["module"] = module
    return module


# --- estrazione delle etichette ------------------------------------------------
def _drawn_labels():
    """Etichette letteralmente disegnate dal pannello, con il loro tipo."""
    out = []
    for path in sorted(ROOT.rglob("*.py")):
        parts = set(path.relative_to(ROOT).parts)
        if ".opencode" in parts or "__pycache__" in parts:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fname = getattr(node.func, "attr", "")
            if fname not in ("label", "prop", "operator"):
                continue
            text = None
            for kw in node.keywords:
                if kw.arg == "text" and isinstance(kw.value, ast.Constant):
                    value = kw.value.value
                    if isinstance(value, str) and value:
                        text = value
                        break
            if fname == "prop" and text is None and len(node.args) >= 2:
                second = node.args[1]
                if isinstance(second, ast.Constant):
                    text = "\x00PROP:" + str(second.value)
            if text:
                out.append((fname, text))

    seen = set()
    unique = []
    for item in out:
        if item in seen:
            continue
        seen.add(item)
        unique.append(item)
    return unique


def _prop_ui_name(prop_name):
    """Nome UI (non tradotto) della property, se raggiungibile."""
    try:
        settings = getattr(bpy.context.scene, SETTINGS_ATTR)
        return settings.bl_rna.properties[prop_name].name
    except Exception:
        return None


# --- misure --------------------------------------------------------------------
def _ui_scale():
    try:
        return float(getattr(bpy.context.preferences.view, "ui_scale", 1.0) or 1.0)
    except Exception:
        return 1.0


def _text_width(text, scale):
    """Larghezza del testo in pixel di schermo (font UI di default)."""
    try:
        import blf

        width, _height = blf.dimensions(0, text)
    except Exception:
        return 0.0
    return float(width) * scale


# --- regione UI ----------------------------------------------------------------
def _sidebar_region():
    win = bpy.context.window_manager.windows[0]
    for area in win.screen.areas:
        if area.type != "VIEW_3D":
            continue
        try:
            area.spaces.active.show_region_ui = True
        except Exception:
            pass
        region = next((reg for reg in area.regions if reg.type == "UI"), None)
        if region is not None:
            for category in PANEL_CATEGORIES:
                try:
                    region.active_panel_category = category
                    break
                except Exception:
                    continue
        return win, area, region
    return win, None, None


def _set_sidebar_width(ui, area):
    """Porta la sidebar a una larghezza utile; restituisce quella ottenuta."""
    if ui is None:
        return 0

    def width():
        try:
            return int(getattr(ui, "width", 0) or 0)
        except Exception:
            return 0

    limit = max(320, int(getattr(area, "width", 800)) - 200) if area else 600
    try:
        ui.width = min(max(width(), PANEL_MIN_WIDTH), limit)
    except Exception:
        pass
    if width() < PANEL_MIN_WIDTH:
        try:
            view = bpy.context.preferences.view
            current = int(getattr(view, "ui_region_width", 0) or 0)
            if current > 0:
                view.ui_region_width = min(max(current, PANEL_MIN_WIDTH), 320)
                bpy.ops.wm.redraw_timer(type="DRAW_WIN_SWAP", iterations=1)
        except Exception:
            pass
    return width()


def _activate_tab(region):
    """Attiva il tab dell'addon e verifica che resti attivo dopo il redraw."""
    if region is None:
        return False
    for _ in range(3):
        for category in PANEL_CATEGORIES:
            try:
                region.active_panel_category = category
            except Exception:
                continue
        try:
            bpy.ops.wm.redraw_timer(type="DRAW_WIN_SWAP", iterations=2)
        except Exception:
            pass
        time.sleep(0.3)
        try:
            if region.active_panel_category == PANEL_CATEGORIES[0]:
                return True
        except Exception:
            pass
    return False


def _region_box(region, area=None):
    if region is None:
        return None
    try:
        x, y = int(region.x), int(region.y)
        if area is not None:
            x += int(area.x)
            y += int(area.y)
        return (x, y, int(region.width), int(region.height))
    except Exception:
        return None


# --- scena neutra e screenshot -------------------------------------------------
def prepare(lang):
    """Addon + lingua + cubo neutro + pannello in configurazione completa."""
    _load_addon()
    view = bpy.context.preferences.view
    view.language = LANG_CODES.get(lang, "en_US")
    view.use_translate_interface = True

    if bpy.context.object is not None and bpy.context.object.mode != "OBJECT":
        try:
            bpy.ops.object.mode_set(mode="OBJECT")
        except Exception:
            pass
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=(0.0, 0.0, 0.0))

    settings = getattr(bpy.context.scene, SETTINGS_ATTR, None)
    if settings is not None:
        # Il pannello nasconde meta' dei controlli dietro questo interruttore:
        # per misurare tutto va aperto.
        try:
            settings.show_advanced = True
        except Exception:
            pass
    bpy.context.view_layer.update()
    return settings


def _shot(path, win, area, region):
    if area is not None:
        try:
            ctx = {"window": win, "screen": win.screen, "area": area}
            if region is not None:
                ctx["region"] = region
            with bpy.context.temp_override(**ctx):
                bpy.ops.screen.screenshot_area(filepath=path)
            if os.path.exists(path):
                return path
        except Exception:
            pass
    with bpy.context.temp_override(window=win, screen=win.screen):
        bpy.ops.screen.screenshot(filepath=path)
    return path


def _crop_and_scale(src_png, dst_png, box, max_width=MAX_WIDTH):
    """Ritaglia il riquadro dalla finestra e scala a max_width. Ritorna (w, h)."""
    try:
        import numpy as np
    except Exception:
        return (0, 0)
    if not os.path.exists(src_png):
        return (0, 0)
    try:
        image = bpy.data.images.load(src_png, check_existing=False)
        width, height = image.size
        pixels = np.array(image.pixels[:], dtype=np.float32).reshape(height, width, 4)
        bpy.data.images.remove(image)
    except Exception:
        return (0, 0)

    if box is not None:
        x0, y0, w, h = box
        x0 = max(0, min(x0, width - 1))
        y0 = max(0, min(y0, height - 1))
        w = max(1, min(w, width - x0))
        h = max(1, min(h, height - y0))
        pixels = pixels[y0:y0 + h, x0:x0 + w, :]

    ch, cw = pixels.shape[0], pixels.shape[1]
    if cw > max_width:
        factor = int(cw // max_width) + 1
        nh, nw = ch // factor, cw // factor
        pixels = pixels[:nh * factor, :nw * factor, :].reshape(
            nh, factor, nw, factor, 4
        ).mean(axis=(1, 3))

    ch, cw = pixels.shape[0], pixels.shape[1]
    try:
        out = bpy.data.images.new("iuv_crop", width=cw, height=ch, alpha=True)
        out.pixels = pixels.ravel().tolist()
        os.makedirs(os.path.dirname(dst_png), exist_ok=True)
        out.filepath_raw = dst_png
        out.file_format = "PNG"
        out.save()
        bpy.data.images.remove(out)
    except Exception:
        return (0, 0)
    return (cw, ch)


def capture(lang, box):
    """Screenshot del pannello + ritaglio della sidebar (max 1024 px)."""
    os.makedirs(OUT_DIR, exist_ok=True)
    win, area, region = _sidebar_region()
    try:
        bpy.ops.wm.redraw_timer(type="DRAW_WIN_SWAP", iterations=2)
    except Exception:
        pass
    width = _set_sidebar_width(region, area)
    try:
        bpy.ops.wm.redraw_timer(type="DRAW_WIN_SWAP", iterations=2)
    except Exception:
        pass

    full = os.path.join(OUT_DIR, "iuv-panel-{0}.png".format(lang))
    crop = os.path.join(OUT_DIR, "iuv-ui-{0}.png".format(lang))
    _shot(full, win, area, region)
    size = _crop_and_scale(full, crop, _region_box(region, area))
    print("SHOT {0} full={1} crop={2} {3}x{4} sidebar={5}".format(
        lang, os.path.basename(full), os.path.basename(crop),
        size[0], size[1], width))
    return crop


# --- flusso principale ----------------------------------------------------------
def probe(lang):
    prepare(lang)
    win, area, region = _sidebar_region()
    try:
        bpy.ops.wm.redraw_timer(type="DRAW_WIN_SWAP", iterations=2)
    except Exception:
        pass

    box = _region_box(region, area)
    width = box[2] if box else 0
    scale = _ui_scale()
    available = max(0.0, float(width) - MARGIN)
    _say("UI_REGION width={0} available={1:.0f} scale={2:g}".format(
        width, available, scale))

    labels = _drawn_labels()
    flagged = 0
    widest = 0.0
    for kind, text in labels:
        if text.startswith("\x00PROP:"):
            name = _prop_ui_name(text[6:])
            if not name:
                continue
            text = name
        w = _text_width(text, scale)
        widest = max(widest, w)
        if available <= 0:
            status = "NOWIDTH"
        elif w > available:
            status = "TRUNC?"
            flagged += 1
        elif w > available * 0.85:
            status = "TIGHT"
        else:
            status = "OK"
        _say('UI_TEXT {0} kind={1} w={2:.0f} avail={3:.0f} "{4}"'.format(
            status, kind, w, available, text))

    min_safe = widest + MARGIN
    _say("UI_SUMMARY labels={0} flagged={1} region_width={2} min_safe_width={3:.0f}".format(
        len(labels), flagged, width, min_safe))
    _say("UI_NOTE le etichette del pannello sono scritte in inglese nel codice e non hanno "
          "catalogo di traduzione: le misure valgono per IT ed EN")

    tab_ok = _activate_tab(region)
    _say("UI_TAB active={0}".format(
        region.active_panel_category if region is not None else "?"))
    if not tab_ok:
        _say("UI_TAB_WARN il tab non e' rimasto attivo dopo il redraw")
    try:
        capture(lang, box)
    except Exception as exc:
        print("SHOT_ERROR {0} {1}: {2}".format(lang, type(exc).__name__, exc))

    return width, len(labels), flagged, min_safe


def main():
    for lang in LANGS:
        try:
            width, labels, flagged, min_safe = probe(lang)
            _say("PROBE {0} region_width={1} labels={2} flagged={3} min_safe={4:.0f}".format(
                lang, width, labels, flagged, min_safe))
        except Exception as exc:
            _say("PROBE_ERROR {0} {1}: {2}".format(lang, type(exc).__name__, exc))

    try:
        os.makedirs(OUT_DIR, exist_ok=True)
        path = os.path.join(OUT_DIR, "ui_report.txt")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("\n".join(REPORT) + "\n")
        print("REPORT_FILE {0}".format(path))
    except Exception as exc:
        print("REPORT_ERROR {0}: {1}".format(type(exc).__name__, exc))
    print("DONE")


if __name__ in {"__main__", "__bridge__"}:
    main()
