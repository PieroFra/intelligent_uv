# -*- coding: utf-8 -*-
"""Test headless della pipeline UV di Intelligent UV Mapping.

Copre quello che lo smoke test non tocca: i rifiuti del ContextGuard e un giro
completo analisi -> seam -> unwrap -> distorsione su cubo, cilindro aperto e
sfera. Non modifica il codice dell'addon: crea solo oggetti di scena e li
elimina alla fine.

Uso:
    blender --factory-startup --background --python .opencode/tests/pipeline_test.py

Ultima riga dell'output: RISULTATO passati=X falliti=Y totale=N
"""

import importlib
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))      # .opencode\tests -> .opencode -> radice
PACKAGE = os.path.basename(ROOT)
sys.path.insert(0, os.path.dirname(ROOT))

import bpy  # noqa: E402  (deve venire dopo la preparazione di sys.path)

STATE = {}
RESULTS = []

# Margine isola passato all'unwrap: costante, non un valore inventato dal test.
MARGIN_UV = 0.01
UV_TOLERANCE = 0.05


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


def module(name):
    """Importa un sottomodulo del package (es. 'validation')."""
    return importlib.import_module("{0}.{1}".format(PACKAGE, name))


# --- helper di scena -----------------------------------------------------------

def _settings():
    settings = bpy.context.scene.intelligent_uv_settings
    if settings is None:
        raise ValueError("il puntatore su Scene.intelligent_uv_settings e' vuoto")
    return settings


def _activate(obj):
    """Deseleziona tutto e rende `obj` l'unico oggetto attivo."""
    for other in bpy.context.view_layer.objects:
        other.select_set(False)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def _link(name, mesh):
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def _drop(obj):
    """Rimuove oggetto e dati dalla scena (scena pulita tra un controllo e l'altro)."""
    try:
        bpy.data.objects.remove(obj, do_unlink=True)
    except Exception:  # noqa: BLE001 - la pulizia non deve far fallire il controllo
        pass


def _uv_layer(obj):
    name = str(getattr(_settings(), "uv_layer_name", "SmartUV") or "SmartUV")
    layer = obj.data.uv_layers.get(name)
    if layer is None:
        layers = [uv.name for uv in obj.data.uv_layers]
        raise AttributeError("layer '{0}' assente (presenti: {1})".format(name, layers))
    return name, layer


def _uv_coords(layer):
    return [(float(item.uv[0]), float(item.uv[1])) for item in layer.data]


def _require_finite(coords):
    for u, v in coords:
        if not (math.isfinite(u) and math.isfinite(v)):
            raise ValueError("coordinata non finita: ({0}, {1})".format(u, v))


def _require_unit_range(coords):
    low = -UV_TOLERANCE
    high = 1.0 + UV_TOLERANCE
    for u, v in coords:
        if not (low <= u <= high and low <= v <= high):
            raise ValueError("coordinata fuori da [{0}, {1}]: ({2}, {3})".format(
                low, high, u, v))


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _plan_and_mark(obj, settings):
    """analisi mesh -> analisi materiali -> piano seam -> seam reali."""
    mesh_analysis = module("mesh_analysis").MeshAnalyzer.analyze(obj.data)
    if not getattr(mesh_analysis, "ok", False):
        raise RuntimeError("analisi mesh fallita: {0}".format(
            "; ".join(mesh_analysis.errors[:3]) or "nessun errore riportato"))

    material_analysis = module("material_analysis").MaterialAnalyzer.analyze(obj)
    if not getattr(material_analysis, "ok", False):
        raise RuntimeError("analisi materiali fallita: {0}".format(
            "; ".join(material_analysis.errors[:3]) or "nessun errore riportato"))

    plan = module("seam_planning").SeamPlanner.plan(
        mesh_analysis, material_analysis, settings
    )
    if not getattr(plan, "ok", False):
        raise RuntimeError("piano seam fallito: {0}".format(
            "; ".join(plan.errors[:3]) or "nessun errore riportato"))

    success, message = module("seam_marking").SeamMarker.mark_real_seams(
        obj.data, plan.is_seam
    )
    if not success:
        raise RuntimeError("marcatura seam fallita: {0}".format(message))

    return mesh_analysis, plan


# --- controlli negativi --------------------------------------------------------

def negative_no_active():
    for other in bpy.context.view_layer.objects:
        other.select_set(False)
    bpy.context.view_layer.objects.active = None

    result = module("validation").ContextGuard.validate_for_uv(bpy.context)
    if result.ok:
        raise AssertionError("contesto senza oggetto attivo accettato")
    return "; ".join(result.errors[:1]) or "rifiutato"


def negative_non_mesh():
    obj = _link("IUV_Empty", None)
    try:
        _activate(obj)
        result = module("validation").ContextGuard.validate_for_uv(bpy.context)
        if result.ok:
            raise AssertionError("Empty accettato come oggetto UV")
        return "; ".join(result.errors[:1]) or "rifiutato"
    finally:
        _drop(obj)


def negative_empty_mesh():
    mesh = bpy.data.meshes.new("IUV_EmptyMesh")
    obj = _link("IUV_EmptyMeshObj", mesh)
    try:
        _activate(obj)
        result = module("validation").ContextGuard.validate_for_uv(bpy.context)
        if result.ok:
            raise AssertionError("mesh vuota accettata come oggetto UV")
        return "; ".join(result.errors[:1]) or "rifiutato"
    finally:
        _drop(obj)


# --- pipeline ------------------------------------------------------------------

def pipeline_cube():
    bpy.ops.mesh.primitive_cube_add()
    obj = bpy.context.view_layer.objects.active
    try:
        settings = _settings()
        _plan_and_mark(obj, settings)
        report = module("uv_executor").MinimalUVExecutor.execute_unwrap(
            obj, settings, MARGIN_UV, use_seams=True
        )

        name, layer = _uv_layer(obj)
        coords = _uv_coords(layer)
        if not coords:
            raise ValueError("layer '{0}' senza loop UV".format(name))
        _require_finite(coords)
        _require_unit_range(coords)
        return "{0} loop UV, metodo {1}, layer {2}".format(
            len(coords), report.get("method", "?"), name)
    finally:
        _drop(obj)


def pipeline_cylinder():
    # Cilindro aperto: in Blender 5.2 i capi si tolgono con end_fill_type='NOTHING'
    # (cap_ends non esiste piu' tra le proprieta' dell'operatore).
    bpy.ops.mesh.primitive_cylinder_add(end_fill_type='NOTHING')
    obj = bpy.context.view_layer.objects.active
    try:
        settings = _settings()
        _plan_and_mark(obj, settings)
        module("uv_executor").MinimalUVExecutor.execute_unwrap(
            obj, settings, MARGIN_UV, use_seams=True
        )

        name, layer = _uv_layer(obj)
        coords = _uv_coords(layer)
        if not coords:
            raise ValueError("layer '{0}' senza loop UV".format(name))
        _require_finite(coords)
        return "{0} loop UV, layer {1}".format(len(coords), name)
    finally:
        _drop(obj)


def pipeline_sphere():
    bpy.ops.mesh.primitive_uv_sphere_add()
    obj = bpy.context.view_layer.objects.active
    try:
        settings = _settings()
        mesh_analysis, _plan = _plan_and_mark(obj, settings)
        module("uv_executor").MinimalUVExecutor.execute_unwrap(
            obj, settings, MARGIN_UV, use_seams=True
        )

        _name, layer = _uv_layer(obj)
        coords = _uv_coords(layer)
        if not coords:
            raise ValueError("layer UV senza loop")
        _require_finite(coords)

        res = module("distortion").DistortionAnalyzer.analyze(
            obj.data, layer, mesh_analysis
        )
        metrics = {
            "density_min": res.density_min,
            "density_max": res.density_max,
            "density_mean": res.density_mean,
            "density_deviation": res.density_deviation,
            "angle_error_mean": res.angle_error_mean,
            "angle_error_max": res.angle_error_max,
        }
        for key, value in metrics.items():
            if not _is_number(value):
                raise TypeError("{0} non numerico: {1!r}".format(key, value))
            if not math.isfinite(float(value)):
                raise ValueError("{0} non finito: {1}".format(key, value))
        return "deviazione densita {0:.4f}, errore angolare medio {1:.2f} deg, facce {2}".format(
            float(res.density_deviation), float(res.angle_error_mean), res.faces_measured)
    finally:
        _drop(obj)


def pipeline_unregister():
    package().unregister()
    if hasattr(bpy.types.Scene, "intelligent_uv_settings"):
        raise AttributeError("Scene.intelligent_uv_settings non rimosso")
    return "unregister() eseguito"


# --- esecuzione ----------------------------------------------------------------

def _setup():
    importlib.invalidate_caches()
    mod = importlib.import_module(PACKAGE)
    STATE["mod"] = mod
    mod.register()


try:
    _setup()
except Exception as exc:  # noqa: BLE001 - senza package non ha senso proseguire
    print("SETUP FAIL {0}: {1}".format(type(exc).__name__, exc))
    print("RISULTATO passati=0 falliti=0 totale=0")
    sys.exit(1)


check("negative_no_active", negative_no_active)
check("negative_non_mesh", negative_non_mesh)
check("negative_empty_mesh", negative_empty_mesh)
check("pipeline_cube", pipeline_cube)
check("pipeline_cylinder", pipeline_cylinder)
check("pipeline_sphere", pipeline_sphere)
check("pipeline_unregister", pipeline_unregister)

print("PIPELINE addon={0} blender={1}".format(PACKAGE, bpy.app.version_string))
for name, passed, detail in RESULTS:
    print("CHECK {0} {1} {2}".format(name, "PASS" if passed else "FAIL", detail))

passed = sum(1 for _, ok, _ in RESULTS if ok)
failed = len(RESULTS) - passed
print("RISULTATO passati={0} falliti={1} totale={2}".format(passed, failed, len(RESULTS)))
