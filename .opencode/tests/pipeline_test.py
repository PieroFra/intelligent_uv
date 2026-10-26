# -*- coding: utf-8 -*-
"""Test headless della pipeline UV di Intelligent UV Mapping.

Copre quello che lo smoke test non tocca: i rifiuti del ContextGuard e un giro
completo analisi -> seam -> unwrap -> distorsione su cubo, cilindro aperto e
sfera, piu' l'assegnazione UDIM multi-tile su un cubo a tre materiali,
e i check F2 (contratto del live link RizomUV, senza lanciarlo), F3
(preservazione delle seam messe a mano e guard del Edit Mode)
e F4 (texel density globale multi-oggetto). L'ultimo controllo prova la firma
inglese della UI (_EnglishLayout, popup License & Credits) con lingua italiana
attiva, prima e dopo un secondo register().
Non modifica il codice dell'addon: crea solo oggetti di scena e li
elimina alla fine.

Uso:
    blender --factory-startup --background --python .opencode/tests/pipeline_test.py

Ultima riga dell'output: RISULTATO passati=X falliti=Y totale=N
"""

import importlib
import math
import os
import sys
import types

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


def pipeline_udim_multi_tile():
    # F1 (UDIM multi-tile): cubo con 3 material slot (2 facce ciascuno).
    # udim.apply deve spalmare il layout su tile distinte, una per gruppo
    # materiale, e lasciare ogni faccia dentro il tile assegnato.
    udim = module("udim")
    island_mod = module("island_extraction")
    mat_mod = module("material_analysis")
    executor = module("uv_executor")

    materials = [bpy.data.materials.new("IUV_UDIM_{0}".format(i)) for i in range(3)]
    objs, layers, analyses = [], [], []
    try:
        for _tag in ("A", "B"):
            bpy.ops.mesh.primitive_cube_add()
            obj = bpy.context.view_layer.objects.active
            for mat in materials:
                obj.data.materials.append(mat)
            for fidx, poly in enumerate(obj.data.polygons):
                poly.material_index = fidx // 2

            settings = _settings()
            settings.use_udim = True
            settings.udim_max_tiles = 3

            _mesh_analysis, plan = _plan_and_mark(obj, settings)
            material_analysis = mat_mod.MaterialAnalyzer.analyze(obj)
            executor.MinimalUVExecutor.execute_unwrap(
                obj, settings, MARGIN_UV, use_seams=True
            )
            # L'estrazione isole usa gli stessi region ids del piano seam,
            # come fa la pipeline reale (operators/native.py).
            island_analysis = island_mod.IslandExtractor.analyze(
                obj=obj, settings=settings,
                material_analysis=material_analysis, region_ids=plan.region_ids,
            )
            if not getattr(island_analysis, "ok", False):
                raise RuntimeError("analisi isole fallita: {0}".format(
                    "; ".join(island_analysis.errors[:3]) or "nessun errore"))

            _name, layer = _uv_layer(obj)
            result = udim.apply(
                obj.data, layer, island_analysis, material_analysis,
                settings, report=None,
            )
            objs.append(obj)
            layers.append(layer)
            analyses.append((result, island_analysis, material_analysis))

        result, island_analysis, material_analysis = analyses[0]

        if result.tiles < 2:
            raise AssertionError(
                "udim.apply non ha sparso il layout su piu' tile: tiles={0}".format(
                    result.tiles))

        # faccia -> tile assegnata, passando per l'isola di appartenenza.
        face_tile = {}
        for record in island_analysis.islands:
            tile = result.assignments.get(record.get("id"))
            if tile is None:
                raise AssertionError(
                    "isola {0} rimasta senza tile assegnata".format(record.get("id")))
            for fidx in record.get("faces", ()):
                face_tile[fidx] = tile

        # gruppo materiale -> tile: iniettivo, altrimenti due materiali
        # condividono lo stesso spazio (collisione di tile).
        group_tile = {}
        for record in island_analysis.islands:
            tally = {}
            for fidx in record.get("faces", ()):
                group = material_analysis.face_material_group.get(fidx)
                if group is not None:
                    tally[group] = tally.get(group, 0) + 1
            if not tally:
                continue
            dominant = max(tally, key=tally.get)
            tile = result.assignments.get(record.get("id"))
            if dominant in group_tile and group_tile[dominant] != tile:
                raise AssertionError(
                    "gruppo {0} finito su tile diverse: {1} vs {2}".format(
                        dominant, group_tile[dominant], tile))
            group_tile[dominant] = tile
        used_tiles = set(group_tile.values())
        if len(used_tiles) != len(group_tile):
            raise AssertionError(
                "collisione di tile tra materiali diversi: {0}".format(group_tile))
        if len(used_tiles) < 2:
            raise AssertionError(
                "materiali diversi tutti sullo stesso tile: {0}".format(group_tile))

        # ogni loop UV di una faccia deve stare nel tile assegnato
        # ([tile_u, tile_u+1) x [tile_v, tile_v+1), tolleranza 1e-4).
        coords = _uv_coords(layers[0])
        _require_finite(coords)
        tile_tol = 1e-4
        for fidx, poly in enumerate(objs[0].data.polygons):
            tile_u, tile_v = face_tile[fidx]
            for li in range(poly.loop_start, poly.loop_start + poly.loop_total):
                u, v = coords[li]
                if not (tile_u - tile_tol <= u <= tile_u + 1.0 + tile_tol
                        and tile_v - tile_tol <= v <= tile_v + 1.0 + tile_tol):
                    raise AssertionError(
                        "faccia {0} (tile {1},{2}) con UV ({3:.4f}, {4:.4f}) "
                        "fuori dal tile".format(fidx, tile_u, tile_v, u, v))

        # determinismo: cubo gemello deve produrre UV identiche (1e-6).
        coords_b = _uv_coords(layers[1])
        if len(coords_b) != len(coords):
            raise AssertionError(
                "loop UV diversi tra i due cubi: {0} vs {1}".format(
                    len(coords), len(coords_b)))
        worst = 0.0
        for (u1, v1), (u2, v2) in zip(coords, coords_b):
            worst = max(worst, abs(u1 - u2), abs(v1 - v2))
        if worst > 1e-6:
            raise AssertionError(
                "UDIM non deterministico: scarto massimo {0}".format(worst))

        return "{0} tile {1}, {2} facce su {3} gruppi, scarto determinismo {4:.2e}".format(
            result.tiles, result.tile_numbers(), len(objs[0].data.polygons),
            len(group_tile), worst)
    finally:
        for obj in objs:
            _drop(obj)
        settings = _settings()
        settings.use_udim = False
        settings.udim_max_tiles = 20


def pipeline_seam_preservation():
    # F3 (seam pinning): le seam messe a mano devono sopravvivere a analisi,
    # piano seam, marcatura e unwrap. Il planner le semina in is_seam e il
    # pruning le protegge (protected=existing_seams).
    bpy.ops.mesh.primitive_cube_add()
    obj = bpy.context.view_layer.objects.active
    try:
        mesh = obj.data
        # MeshEdge non espone link_faces (e' un attributo di BMEdge):
        # conto le facce per edge leggendo i loop dei poligoni.
        face_count = [0] * len(mesh.edges)
        for poly in mesh.polygons:
            for li in range(poly.loop_start, poly.loop_start + poly.loop_total):
                face_count[mesh.loops[li].edge_index] += 1
        manifold = [i for i, n in enumerate(face_count) if n == 2]
        if len(manifold) < 2:
            raise AssertionError(
                "il cubo non ha almeno 2 edge manifold: {0}".format(len(manifold)))
        chosen = [manifold[0], manifold[-1]]
        for eidx in chosen:
            mesh.edges[eidx].use_seam = True

        settings = _settings()
        previous = bool(getattr(settings, "preserve_existing_seams", True))
        settings.preserve_existing_seams = True
        try:
            mesh_analysis, plan = _plan_and_mark(obj, settings)
        finally:
            settings.preserve_existing_seams = previous

        unread = [eidx for eidx in chosen
                  if eidx not in mesh_analysis.existing_seams]
        if unread:
            raise AssertionError(
                "l'analisi non ha letto le seam esistenti: {0}".format(unread))

        preserved = int(getattr(plan, "preserved_seam_count", 0))
        if preserved < len(chosen):
            raise AssertionError(
                "il piano non preserva le seam a mano: preserved_seam_count={0}"
                " < {1}".format(preserved, len(chosen)))

        for eidx in chosen:
            if not mesh.edges[eidx].use_seam:
                raise AssertionError(
                    "seam a mano {0} persa dopo la marcatura".format(eidx))

        report = module("uv_executor").MinimalUVExecutor.execute_unwrap(
            obj, settings, MARGIN_UV, use_seams=True
        )

        for eidx in chosen:
            if not mesh.edges[eidx].use_seam:
                raise AssertionError(
                    "seam a mano {0} cancellata dall'unwrap (metodo {1})".format(
                        eidx, report.get("method", "?")))

        name, layer = _uv_layer(obj)
        coords = _uv_coords(layer)
        if not coords:
            raise ValueError("layer '{0}' senza loop UV".format(name))
        _require_finite(coords)

        seam_total = sum(1 for e in mesh.edges if e.use_seam)
        return "preservate {0}/{1}, seam totali {2}, UV finiti ({3} loop)".format(
            preserved, len(chosen), seam_total, len(coords))
    finally:
        _drop(obj)


def pipeline_edit_mode_guard():
    # F3 (guard Edit Mode): _run_analysis (operators/base.py:42-47) riporta in
    # Object Mode prima di scrivere seam. Percorso reale: l'operatore
    # mark_seam_candidates chiama _run_analysis; check e' read-only e, se la
    # sua poll lo blocca, il blocco deve essere pulito (nessuna eccezione).
    bpy.ops.mesh.primitive_cube_add()
    obj = bpy.context.view_layer.objects.active
    try:
        _activate(obj)
        bpy.ops.object.mode_set(mode='EDIT')
        if bpy.context.mode != 'EDIT_MESH':
            raise AssertionError(
                "non siamo entrati in Edit Mode: mode={0}".format(
                    bpy.context.mode))

        try:
            check_result = bpy.ops.intelligent_uv.check()
            check_outcome = "check in Edit Mode: {0}".format(
                sorted(check_result))
        except RuntimeError as exc:
            # poll ha rifiutato il contesto: blocco pulito, nessun traceback.
            check_outcome = "check bloccato pulito da poll ({0})".format(exc)

        result = bpy.ops.intelligent_uv.mark_seam_candidates()
        seam_total = sum(1 for e in obj.data.edges if e.use_seam)

        if bpy.context.mode != 'OBJECT':
            raise AssertionError(
                "il guard non ha riportato in Object Mode: mode={0}".format(
                    bpy.context.mode))
        if 'FINISHED' not in result:
            raise AssertionError(
                "mark_seam_candidates non ha completato: {0}".format(
                    sorted(result)))
        if seam_total <= 0:
            raise AssertionError(
                "nessuna seam marcata: la pipeline non ha girato in Object Mode")

        return "{0}; mark_seam_candidates {1} -> OBJECT, {2} seam marcate".format(
            check_outcome, sorted(result), seam_total)
    finally:
        if bpy.context.mode != 'OBJECT':
            try:
                bpy.ops.object.mode_set(mode='OBJECT')
            except Exception:  # noqa: BLE001 - solo pulizia tra i controlli
                pass
        _drop(obj)


def pipeline_global_texel_density():
    # F4 (texel density globale multi-oggetto): due cubi di lato diverso
    # devono essere normalizzati alla stessa densita' target calcolata sulla
    # world area complessiva (coverage 1.0: il cubo piu' grande riempie il
    # tile unitario), mentre senza target esplicito ogni oggetto tiene la
    # propria densita' locale, diversa per geometrie di dimensioni diverse.
    texel = module("texel_density")
    island_mod = module("island_extraction")
    mat_mod = module("material_analysis")
    executor = module("uv_executor")

    settings = _settings()
    previous_layer = getattr(settings, "uv_layer_name", "SmartUV")
    settings.uv_layer_name = "SmartUV"

    prepared = []   # (obj, mesh_analysis, island_analysis, region_ids)
    try:
        for side in (1.0, 2.0):
            bpy.ops.mesh.primitive_cube_add(size=side)
            obj = bpy.context.view_layer.objects.active
            _activate(obj)
            mesh_analysis, plan = _plan_and_mark(obj, settings)
            executor.MinimalUVExecutor.execute_unwrap(
                obj, settings, MARGIN_UV, use_seams=True
            )
            material_analysis = mat_mod.MaterialAnalyzer.analyze(obj)
            island_analysis = island_mod.IslandExtractor.analyze(
                obj=obj, settings=settings,
                material_analysis=material_analysis, region_ids=plan.region_ids,
            )
            if not getattr(island_analysis, "ok", False):
                raise RuntimeError("analisi isole fallita (lato {0}): {1}".format(
                    side, "; ".join(island_analysis.errors[:3]) or "nessun errore"))
            prepared.append((obj, mesh_analysis, island_analysis, plan.region_ids))

        world_areas = [texel.world_area(item[0]) for item in prepared]

        def _island_uv_area(island_analysis):
            return sum(
                float(r.get("uv_area", 0.0) or 0.0)
                for r in island_analysis.islands
            )

        def _extract(obj, mesh_analysis, region_ids):
            mat = mat_mod.MaterialAnalyzer.analyze(obj)
            result = island_mod.IslandExtractor.analyze(
                obj=obj, settings=settings, material_analysis=mat,
                region_ids=region_ids,
            )
            if not getattr(result, "ok", False):
                raise RuntimeError("estrazione isole fallita: {0}".format(
                    "; ".join(result.errors[:3]) or "nessun errore"))
            return result

        def _measure(obj, island_analysis):
            world = texel.world_area(obj)
            if world <= 1e-12:
                raise AssertionError("world area nulla per {0}".format(obj.name))
            return _island_uv_area(island_analysis) / world

        # --- target globale sulla world area dei due oggetti ---
        target = texel.global_target_density([item[0] for item in prepared])
        if not target.get("ok"):
            raise AssertionError("global_target_density non ok: {0}".format(target))
        if not (float(target["target_density"]) > 0):
            raise AssertionError("target_density non positivo: {0}".format(
                target["target_density"]))
        big_world = world_areas[-1]
        if abs(float(target["max_area"]) - big_world) > 0.01 * big_world:
            raise AssertionError(
                "max_area {0} non corrisponde alla world area del cubo grande {1}".format(
                    target["max_area"], big_world))

        # --- comportamento locale (nessun target esplicito) ---
        # Misurato PRIMA del globale, sulle UV native dell'unwrap: senza
        # target_density normalize() lascia ogni oggetto alla propria densita'
        # locale, che dipende dalla dimensione (le UV dell'unwrap sono
        # invarianti di scala, l'area mesh no). Con due cubi di lato diverso
        # le densita locali devono divergere.
        local = []
        for obj, mesh_analysis, island_analysis, region_ids in prepared:
            res = texel.TexelDensityNormalizer.normalize(
                obj, island_analysis, mesh_analysis, settings=settings,
            )
            if not res.get("ok"):
                raise AssertionError("normalize locale fallito su {0}: {1}".format(
                    obj.name, res.get("message")))
            fresh = _extract(obj, mesh_analysis, region_ids)
            density = _measure(obj, fresh)
            if density <= 0:
                raise AssertionError(
                    "{0}: densita locale non positiva ({1:.6f}); unwrap nativo "
                    "degenerato".format(obj.name, density))
            local.append((obj.name, density))
        if abs(local[0][1] - local[1][1]) <= 0.02 * max(local[0][1], local[1][1]):
            raise AssertionError(
                "le densita locali coincidono entro il 2%: {0}".format(local))

        # --- normalizzazione globale: densita' raggiunta misurata ---
        # sull'area UV reale delle isole (non sui bounds del packer).
        achieved = []
        for obj, mesh_analysis, island_analysis, region_ids in prepared:
            res = texel.TexelDensityNormalizer.normalize(
                obj, island_analysis, mesh_analysis,
                settings=settings, target_density=target["target_density"],
            )
            if not res.get("ok"):
                raise AssertionError("normalize globale fallito su {0}: {1}".format(
                    obj.name, res.get("message")))
            fresh = _extract(obj, mesh_analysis, region_ids)
            density = _measure(obj, fresh)
            achieved.append((obj.name, density))
            if abs(density - target["target_density"]) > 0.05 * target["target_density"]:
                raise AssertionError(
                    "{0}: densita raggiunta {1:.6f} fuori 5% dal target {2:.6f}".format(
                        obj.name, density, target["target_density"]))
            if density > 1.05 * target["target_density"]:
                raise AssertionError(
                    "{0}: densita {1:.6f} supera target*1.05 ({2:.6f})".format(
                        obj.name, density, 1.05 * target["target_density"]))

        return ("world_area {0:.3f}/{1:.3f}, target {2:.6f} (max_area {3:.3f}), "
                "locali {4}, raggiunta {5}".format(
                    world_areas[0], world_areas[1], target["target_density"],
                    target["max_area"],
                    "; ".join("{0}={1:.4f}".format(n, d) for n, d in local),
                    "; ".join("{0}={1:.4f}".format(n, d) for n, d in achieved)))
    finally:
        for obj, _ma, _ia, _rid in prepared:
            _drop(obj)
        settings.uv_layer_name = previous_layer


def pipeline_link_bridge_contract():
    # F2 (live link RizomUV): contratto headless del bridge. Non lancia
    # RizomUV e non apre socket: RizomUVLink e' importato in modo lazy dentro
    # link_module(), is_available()/unavailable_reason() sono funzioni pure e
    # _build_steps() dipende solo dalle impostazioni e dal margine. Con il
    # link assente (macchina CI) prepare() deve rifiutare PRIMA di toccare
    # oggetti/settings (rizomuv_link.py:251-252), con lo stesso motivo.
    link = module("rizomuv_link")

    available = link.is_available()
    if not isinstance(available, bool):
        raise AssertionError(
            "is_available() non ritorna un bool: {0!r}".format(available))

    reason = link.unavailable_reason()
    if not isinstance(reason, str):
        raise AssertionError(
            "unavailable_reason() non ritorna una stringa: {0!r}".format(reason))
    if not available and not reason:
        raise AssertionError("unavailable_reason() vuota con link non disponibile")

    if not available:
        # prepare(None, ...) deve sollevare RuntimeError con il motivo
        # esatto, senza toccare obj/settings e senza accedere a bpy.
        try:
            link.RizomUVLinkBridge.prepare(None, None, None, None)
        except RuntimeError as exc:
            if str(exc) != reason:
                raise AssertionError(
                    "prepare() ha rifiutato con messaggio diverso dal motivo: "
                    "{0!r} != {1!r}".format(str(exc), reason))
        except Exception as exc:  # noqa: BLE001 - crash diverso = contratto rotto
            raise AssertionError(
                "prepare() ha sollevato {0} invece di RuntimeError: {1}".format(
                    type(exc).__name__, exc))
        else:
            raise AssertionError("prepare() senza link non ha sollevato RuntimeError")

    # _build_steps: sequenza comandata solo dalle impostazioni e dal margine.
    margin_result = types.SimpleNamespace(margin_px=2, texture_resolution=2048)
    settings = _settings()
    previous_optimize = bool(getattr(settings, "link_optimize", True))
    try:
        settings.link_optimize = True
        steps = link.RizomUVLinkBridge._build_steps(settings, margin_result)
        names = [s[0] for s in steps]
        if names != ["load", "setup", "unfold", "optimize", "pack", "save"]:
            raise AssertionError(
                "6 step attesi in ordine esatto, ottenuto: {0}".format(names))

        setup_step = steps[1]
        if setup_step[0] != "setup" or setup_step[1] != "Set":
            raise AssertionError(
                "lo step setup non e' un Set: {0!r}".format(setup_step[:2]))
        pack_root = "Lib.Mesh.RootGroup.Properties.Pack"
        expected_entries = [
            (pack_root + ".MapResolution", 2048),
            (pack_root + ".UsePixelUnit", True),
            (pack_root + ".PaddingSizePx", 2),
            (pack_root + ".MarginSizePx", 2),
            (pack_root + ".Scaling.Mode", 0),
        ]
        entries = list(setup_step[2])
        if entries != expected_entries:
            raise AssertionError(
                "setup deve avere le 5 voci Set attese (UsePixelUnit True, "
                "Scaling.Mode 0): {0!r}".format(entries))

        settings.link_optimize = False
        steps_off = link.RizomUVLinkBridge._build_steps(settings, margin_result)
        names_off = [s[0] for s in steps_off]
        if names_off != ["load", "setup", "unfold", "pack", "save"]:
            raise AssertionError(
                "link_optimize=False deve dare 5 step senza optimize: {0}".format(
                    names_off))
    finally:
        settings.link_optimize = previous_optimize

    return ("link disponibile={0}; prepare rifiuta pulito con il motivo; "
            "setup con 5 Set (UsePixelUnit True, Scaling.Mode 0); "
            "link_optimize=False -> 5 step senza optimize".format(available))


class _SpyOp:
    """Operatore finto restituito dallo spy layout: registra gli attributi
    assegnati dopo la chiamata (url, preset_name, ...)."""

    def __init__(self):
        object.__setattr__(self, "attrs", {})

    def __setattr__(self, name, value):
        self.attrs[name] = value


class _SpyLayout:
    """Layout finto: registra ogni chiamata per ispezionare args e kwargs.

    Il pannello disegna su di esso attraverso _EnglishLayout, quindi le tuple
    registrate mostrano esattamente cio' che il proxy passa al layout vero.
    `raise_on` elenca i metodi che devono sollevare TypeError se ricevono
    `translate`, per provare il fallback del proxy.
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
                if name in self._raise and "translate" in kwargs:
                    raise TypeError(
                        "{0}() unexpected keyword 'translate'".format(name))
                result = _SpyOp()
                calls.append((name, args, dict(kwargs), result))
                return result
            return draw
        return lambda *args, **kwargs: None


def _require_english(calls, tag):
    """Firma della UI inglese: translate=False su label/prop/operator/menu."""
    for name, _args, kwargs, _result in calls:
        if name in ("label", "prop", "operator", "menu") \
                and kwargs.get("translate") is not False:
            raise AssertionError(
                "{0}: {1}() senza translate=False: {2!r}".format(
                    tag, name, sorted(kwargs)))


def pipeline_english_ui_and_credits():
    """UI inglese sotto lingua italiana: etichette, credits e doppio register.

    Copre il contratto di _EnglishLayout e del popup IntelligentUV_OT_ShowInfo:
    (a) translate=False su ogni chiamata testuale del pannello; (b) le
    etichette esplicite restano inglesi; (c) le property prive di text= ricevono
    il nome RNA inglese; (d) icon_only non inietta text=; (e) fallback pulito
    senza translate su TypeError; (f) il popup emette autore, licenza e i tre
    URL con translate=False; (g) dopo un secondo register() tutto continua a
    funzionare identicamente.
    """
    ui = module("ui")
    panel_cls = None
    info_cls = None
    for cls in package().CLASSES:
        if cls.__name__ == "VIEW3D_PT_IntelligentUV" and panel_cls is None:
            panel_cls = cls
        if cls.__name__ == "IntelligentUV_OT_ShowInfo" and info_cls is None:
            info_cls = cls
    if panel_cls is None:
        raise AssertionError("pannello assente da CLASSES")
    if info_cls is None:
        raise AssertionError("IntelligentUV_OT_ShowInfo assente da CLASSES")

    labels = ("Unwrap", "Tex Size", "License & Credits",
              "RizomUV Bridge (Windows)")
    injected = (
        ("show_advanced", "Advanced"),
        ("auto_parameters", "Automatic"),
        ("link_optimize", "Optimize in RizomUV"),
        ("link_keep_open", "Keep RizomUV Open"),
    )
    url_needles = (
        "github.com/PieroFra/intelligent_uv",
        "discord.com/users/1176582483165327382",
        "gnu.org/licenses/gpl-3.0.html",
    )

    def _draw_panel(calls):
        # `_draw_advanced` e' un metodo della classe pannello: legato al
        # puntatore via MethodType perche' panel.draw lo richiami come metodo.
        stub = types.SimpleNamespace(layout=_SpyLayout(calls))
        stub._draw_advanced = types.MethodType(panel_cls._draw_advanced, stub)
        panel_cls.draw(stub, bpy.context)

    def _draw_info(calls):
        info_cls.draw(
            types.SimpleNamespace(layout=_SpyLayout(calls)), bpy.context)

    def _check_texts(calls, tag, needles):
        texts = [kwargs.get("text") for name, _a, kwargs, _r in calls
                 if name in _SpyLayout._TEXT]
        for needle in needles:
            if not any(isinstance(t, str) and needle in t for t in texts):
                raise AssertionError(
                    "{0}: testo '{1}' assente dal disegno".format(tag, needle))

    def _check_urls(calls, tag):
        urls = [getattr(result, "attrs", {}).get("url")
                for _n, _a, _k, result in calls if result is not None]
        for needle in url_needles:
            if not any(isinstance(u, str) and needle in u for u in urls):
                raise AssertionError(
                    "{0}: URL '{1}' assente dal popup".format(tag, needle))

    def _check_injected(calls, tag):
        for prop_id, expected in injected:
            hits = [kwargs for name, args, kwargs, _r in calls
                    if name == "prop" and len(args) >= 2 and args[1] == prop_id]
            if not hits:
                raise AssertionError(
                    "{0}: prop '{1}' mai disegnata".format(tag, prop_id))
            for kwargs in hits:
                if kwargs.get("text") != expected:
                    raise AssertionError(
                        "{0}: prop '{1}' senza text='{2}': {3!r}".format(
                            tag, prop_id, expected, sorted(kwargs)))

    prefs = bpy.context.preferences
    previous_lang = prefs.view.language
    previous_translate = prefs.view.use_translate_interface
    settings = _settings()
    previous_advanced = settings.show_advanced
    previous_rizom = settings.use_rizomuv

    try:
        prefs.view.language = "it_IT"
        prefs.view.use_translate_interface = True
        settings.show_advanced = True
        settings.use_rizomuv = True

        # (a) (b) (c) — pannello completo su spy layout
        calls = []
        _draw_panel(calls)
        _require_english(calls, "pannello")
        _check_texts(calls, "pannello", labels)
        _check_injected(calls, "pannello")

        # (d) — prop(icon_only=True) NON inietta text=
        icon_calls = []
        proxy = ui._EnglishLayout(_SpyLayout(icon_calls))
        proxy.prop(settings, "dry_run", icon_only=True)
        if len(icon_calls) != 1:
            raise AssertionError(
                "spy non ha registrato 1 chiamata: {0}".format(len(icon_calls)))
        icon_kwargs = icon_calls[0][2]
        if "text" in icon_kwargs:
            raise AssertionError(
                "icon_only=True ha ricevuto text=: {0!r}".format(icon_kwargs))
        if icon_kwargs.get("translate") is not False:
            raise AssertionError("icon_only=True senza translate=False")

        # (e) — fallback del proxy su TypeError del layout sottostante
        fallback_calls = []
        proxy = ui._EnglishLayout(
            _SpyLayout(fallback_calls, raise_on=("label",)))
        proxy.label(text="Dry Run: nothing will be written")
        if len(fallback_calls) != 1:
            raise AssertionError("fallback: label non registrata")
        plain = fallback_calls[0][2]
        if "translate" in plain or plain.get("text") != \
                "Dry Run: nothing will be written":
            raise AssertionError(
                "fallback non pulito senza translate: {0!r}".format(plain))

        # (f) — popup credits: autore, licenza, URL, tutto in inglese
        info_calls = []
        _draw_info(info_calls)
        _require_english(info_calls, "popup")
        _check_texts(info_calls, "popup", (
            "Author: Pierfrancesco Diodato",
            "License: GPL-3.0-or-later",
        ))
        _check_urls(info_calls, "popup")

        # (g) — doppio register(): pannello e popup continuano a funzionare
        mod = package()
        mod.register()
        # Il secondo register() sostituisce le classi e ricostruisce il
        # PropertyGroup: l'istanzi presa prima va ri-acquistata dalla scena,
        # un suo riutilizzo dopo la sostituzione RNA crasha Blender.
        settings = _settings()
        settings.show_advanced = True
        settings.use_rizomuv = True
        calls2 = []
        _draw_panel(calls2)
        _require_english(calls2, "pannello/doppio register")
        _check_texts(calls2, "pannello/doppio register", labels)
        _check_injected(calls2, "pannello/doppio register")
        info_calls2 = []
        _draw_info(info_calls2)
        _require_english(info_calls2, "popup/doppio register")
        _check_texts(info_calls2, "popup/doppio register", (
            "Author: Pierfrancesco Diodato",
            "License: GPL-3.0-or-later",
        ))
        _check_urls(info_calls2, "popup/doppio register")
    finally:
        # Le preferenze si ripristinano sempre; le property si leggono dal
        # PropertyGroup corrente (nuovo se il doppio register e' riuscito).
        prefs.view.use_translate_interface = previous_translate
        prefs.view.language = previous_lang
        try:
            fresh = _settings()
        except Exception:  # noqa: BLE001 - scene senza puntatore: solo pulizia
            fresh = None
        if fresh is not None:
            fresh.use_rizomuv = previous_rizom
            fresh.show_advanced = previous_advanced

    return ("{0} chiamate pannello + {1} popup: translate=False ovunque, "
            "etichette e nomi RNA inglesi, icon_only senza text=, fallback su "
            "TypeError, credits completi, doppio register trasparente".format(
                len(calls), len(info_calls)))


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
check("pipeline_udim_multi_tile", pipeline_udim_multi_tile)
check("pipeline_seam_preservation", pipeline_seam_preservation)
check("pipeline_edit_mode_guard", pipeline_edit_mode_guard)
check("pipeline_global_texel_density", pipeline_global_texel_density)
check("pipeline_link_bridge_contract", pipeline_link_bridge_contract)
check("pipeline_english_ui_and_credits", pipeline_english_ui_and_credits)
check("pipeline_unregister", pipeline_unregister)

print("PIPELINE addon={0} blender={1}".format(PACKAGE, bpy.app.version_string))
for name, passed, detail in RESULTS:
    print("CHECK {0} {1} {2}".format(name, "PASS" if passed else "FAIL", detail))

passed = sum(1 for _, ok, _ in RESULTS if ok)
failed = len(RESULTS) - passed
print("RISULTATO passati={0} falliti={1} totale={2}".format(passed, failed, len(RESULTS)))
