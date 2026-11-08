# -*- coding: utf-8 -*-
"""Esperimento descrittivo: seam native, meridiano e tagli automatici."""

import importlib
import json
import math
import os
import sys
import traceback

import bpy

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(ROOT))
PACKAGE = os.path.basename(ROOT)
OUTPUT = os.path.join(os.path.abspath(os.environ['TEMP']),
                      'intelligent_uv_sphere_meridian.json')
REPORT = {}


def module(name):
    return importlib.import_module(PACKAGE + '.' + name)


def topology(mesh):
    return (tuple(tuple(v.co) for v in mesh.vertices),
            tuple(tuple(e.vertices) for e in mesh.edges),
            tuple(tuple(p.vertices) for p in mesh.polygons))


def cap_ring_edges(mesh):
    """Edges shared by a triangle cap and a quad ring: the two cap loops."""
    surrounding = {}
    for polygon in mesh.polygons:
        for key in polygon.edge_keys:
            surrounding.setdefault(frozenset(key), set()).add(len(polygon.vertices))
    return {edge.index for edge in mesh.edges
            if surrounding.get(frozenset(edge.vertices)) == {3, 4}}


def metrics(mesh):
    """Angoli dei triangoli tessellati e densità sqrt(area UV / area 3D)."""
    mesh.calc_loop_triangles()
    uv = mesh.uv_layers.active.data
    output = {}
    for region in ('fascia', 'cap'):
        errors, densities = [], []
        excluded, degenerate = set(), set()
        area3_sum = area2_sum = 0.0
        faces = {p.index for p in mesh.polygons
                 if ('cap' if len(p.vertices) == 3 else 'fascia') == region}
        for tri in mesh.loop_triangles:
            if tri.polygon_index not in faces:
                continue
            xyz = [mesh.vertices[i].co for i in tri.vertices]
            xy = [uv[i].uv.copy() for i in tri.loops]
            a3 = (xyz[1] - xyz[0]).cross(xyz[2] - xyz[0]).length / 2
            a2 = abs((xy[1].x - xy[0].x) * (xy[2].y - xy[0].y)
                     - (xy[1].y - xy[0].y) * (xy[2].x - xy[0].x)) / 2
            if a3 <= 1e-15 or a2 <= 1e-15:
                degenerate.add(tri.polygon_index)
                excluded.add(tri.polygon_index)
                continue
            for i in range(3):
                def angle(points):
                    u = points[(i + 1) % 3] - points[i]
                    v = points[(i + 2) % 3] - points[i]
                    return math.acos(max(-1.0, min(1.0, u.dot(v) / (u.length * v.length))))
                errors.append(abs(angle(xyz) - angle(xy)) * 180 / math.pi)
            densities.append(math.sqrt(a2 / a3))
            area3_sum += a3
            area2_sum += a2
        output[region] = {
            'face_count': len(faces), 'valid_triangle_count': len(densities),
            'excluded_face_indices': sorted(excluded),
            'degenerate_face_indices': sorted(degenerate),
            'mean_absolute_corner_angle_error_degrees': sum(errors) / len(errors) if errors else None,
            'max_absolute_corner_angle_error_degrees': max(errors) if errors else None,
            'density_area_aggregate': math.sqrt(area2_sum / area3_sum) if area3_sum else None,
            'density_triangle_min': min(densities) if densities else None,
            'density_triangle_max': max(densities) if densities else None,
            'area_3d': area3_sum, 'area_uv': area2_sum,
        }
    return output


def test_sphere_meridian():
    addon = importlib.import_module(PACKAGE)
    addon.register()
    bpy.ops.object.mode_set(mode='OBJECT') if bpy.context.object and bpy.context.object.mode != 'OBJECT' else None
    bpy.ops.mesh.primitive_uv_sphere_add(segments=32, ring_count=16, radius=1.0,
                                        location=(0, 0, 0))
    source = bpy.context.object
    before = topology(source.data)
    source_seams = tuple(e.use_seam for e in source.data.edges)
    source_uv = tuple((layer.name, tuple(tuple(item.uv) for item in layer.data))
                      for layer in source.data.uv_layers)
    copies = []
    for name in ('original', 'meridian', 'automatic'):
        obj = source.copy()
        obj.data = source.data.copy()
        obj.name = 'Sphere_' + name
        bpy.context.scene.collection.objects.link(obj)
        copies.append(obj)
    a, b, c = copies
    assert len({o.data.as_pointer() for o in copies}) == 3 and all(o.data is not source.data for o in copies), 'Mesh delle copie condivise'
    assert all(topology(o.data) == before for o in copies), 'Topologia delle copie differente'
    assert len(source.data.vertices) == 482 and len(source.data.polygons) == 512, 'Fixture 32x16 inattesa'
    fixture_seams = cap_ring_edges(source.data)
    assert len(fixture_seams) == 64, 'Anelli dei cap assenti o incompleti'
    settings = bpy.context.scene.intelligent_uv_settings
    # Reset every writable setting to its RNA default. The scene is shared with
    # the other suites, so leftovers from a previous run would change the plan.
    for prop in settings.bl_rna.properties:
        if prop.identifier == 'rna_type' or prop.is_readonly or prop.type == 'COLLECTION':
            continue
        try:
            setattr(settings, prop.identifier, prop.default)
        except Exception:
            pass
    analysis = module('mesh_analysis').MeshAnalyzer.analyze(a.data)
    assert analysis.ok, 'Analisi mesh fallita'
    material = module('material_analysis').MaterialAnalyzer.analyze(a)
    assert material.ok, 'Analisi materiali fallita'
    plan = module('seam_planning').SeamPlanner.plan(analysis, material, settings)
    assert plan.ok, 'Piano seam fallito'
    success, message = module('seam_marking').SeamMarker.mark_real_seams(a.data, plan.is_seam)
    assert success, 'Marcatura seam fallita: ' + message
    original = tuple(e.use_seam for e in a.data.edges)
    assert len(original) == len(b.data.edges), 'Maschera incompatibile'
    seam_topology = module('seam_topology')
    # The planner already completes the cut topologically (seam_planning), so the
    # plan mask must carry the fixture cap rings plus an extra longitudinal cut.
    automatic = tuple(plan.is_seam)
    assert len(automatic) == len(original), 'Maschera automatica incompatibile'
    marked = {i for i, seam in enumerate(automatic) if seam}
    assert fixture_seams <= marked, 'Piano senza le seam dei cap del fixture'
    extra = marked - fixture_seams
    assert extra, 'Piano senza il taglio longitudinale aggiunto'
    extra_vertices = {v for index in extra for v in b.data.edges[index].vertices}
    assert (any(b.data.vertices[v].co.z > 0.0 for v in extra_vertices)
            and any(b.data.vertices[v].co.z < 0.0 for v in extra_vertices)), 'Taglio aggiunto non collega i due cap'
    assert all(not seam or automatic[i] for i, seam in enumerate(original)), 'Seam originali perse nel ramo automatico'
    automatic_input = list(automatic)
    automatic_input_before = tuple(automatic_input)
    automatic_mesh_seams = tuple(e.use_seam for e in c.data.edges)
    completion = seam_topology.complete_boundary_cuts(c.data, automatic_input)
    assert tuple(automatic_input) == automatic_input_before, 'Input seam automatico modificato'
    assert topology(c.data) == before and tuple(e.use_seam for e in c.data.edges) == automatic_mesh_seams, 'Completamento automatico modifica la mesh input'
    assert not completion.added_edges, 'Completamento aggiunge archi a una maschera già completa'
    assert tuple(completion.seam_mask) == automatic, 'Completamento altera la maschera del piano'
    assert not completion.unresolved_regions, 'Regioni automatiche irrisolte sulla sfera'
    automatic_regions = seam_topology.analyze_regions(c.data, automatic)
    assert automatic_regions and all(region.is_disk for region in automatic_regions), 'Regioni automatiche non tutte disco'
    # Seleziona geometricamente il semimeridiano x positivo, escludendo i poli.
    path = sorted((v for v in b.data.vertices if v.co.x > 1e-6 and abs(v.co.y) < 1e-6),
                  key=lambda v: v.co.z)
    assert len(path) == 15, 'Meridiano non attraversa tutti i 15 anelli'
    edge_map = {frozenset(e.vertices): e.index for e in b.data.edges}
    added = []
    for u, v in zip(path, path[1:]):
        assert v.co.z > u.co.z, 'Meridiano non monotono'
        index = edge_map.get(frozenset((u.index, v.index)))
        assert index is not None, 'Percorso meridiano discontinuo'
        added.append(index)
    cap_vertices = {i for p in b.data.polygons if len(p.vertices) == 3 for i in p.vertices}
    assert path[0].index in cap_vertices and path[-1].index in cap_vertices, 'Estremi non sui cap'
    for endpoint in (path[0], path[-1]):
        assert any(original[e.index] and endpoint.index in e.vertices for e in b.data.edges), 'Meridiano non collegato alle seam dei cap'
    assert len(set(added)) == 14, 'Percorso con archi ripetuti'
    modified = tuple(seam or i in added for i, seam in enumerate(original))
    assert all(not seam or modified[i] for i, seam in enumerate(original)), 'Seam originali perse'
    assert any(modified[i] and not original[i] for i in added), 'Meridiano già interamente presente'
    parameters = dict(method='ANGLE_BASED', fill_holes=True, correct_aspect=True,
                      use_subsurf_data=False, margin=0.0)
    REPORT.update({'fixture': {'segments': 32, 'ring_count': 16},
                   'parameters': parameters, 'pack': False, 'postprocessing': False,
                    'original_seam_mask': list(original), 'meridian_seam_mask': list(modified),
                    'automatic_seam_mask': list(automatic),
                    'automatic_added_edges': list(completion.added_edges),
                    'automatic_unresolved_regions': list(completion.unresolved_regions),
                    'fixture_seam_indices': sorted(fixture_seams),
                    'automatic_extra_edges': sorted(extra),
                    'automatic_region_count': len(automatic_regions),
                    'automatic_all_regions_disk': all(region.is_disk for region in automatic_regions),
                   'path_vertex_indices': [v.index for v in path], 'path_edge_indices': added,
                   'limits': 'Pre-pack; densità in unità UV/unità mesh, scala globale unwrap non controllata; angoli su triangoli tessellati, non conformità esatta dei quad; nessuna misura di overlap o soglia di miglioramento.'})
    for obj, mask, name in ((a, original, 'original'), (b, modified, 'meridian'),
                            (c, automatic, 'automatic')):
        for edge, seam in zip(obj.data.edges, mask):
            edge.use_seam = seam
        for item in bpy.context.view_layer.objects:
            item.select_set(False)
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        layer = obj.data.uv_layers.new(name='MeridianExperiment')
        obj.data.uv_layers.active = layer
        try:
            bpy.ops.object.mode_set(mode='EDIT')
            bpy.ops.mesh.select_all(action='SELECT')
            assert bpy.ops.uv.unwrap(**parameters) == {'FINISHED'}, 'Unwrap fallito'
        finally:
            if obj.mode != 'OBJECT':
                bpy.ops.object.mode_set(mode='OBJECT')
        assert all(math.isfinite(x) for item in layer.data for x in item.uv), 'UV non finite'
        assert topology(obj.data) == before, 'Unwrap modifica la topologia'
        assert tuple(e.use_seam for e in obj.data.edges) == mask, 'Unwrap modifica le seam'
        REPORT[name] = metrics(obj.data)
    REPORT['quality_comparison'] = {
        name: {
            region: {
                key: (value - REPORT['original'][region][key]
                      if value is not None and REPORT['original'][region][key] is not None
                      else None)
                for key, value in REPORT[name][region].items()
                if key.startswith(('mean_absolute_', 'max_absolute_', 'density_'))
            }
            for region in ('fascia', 'cap')
        }
        for name in ('meridian', 'automatic')
    }
    assert topology(source.data) == before and tuple(e.use_seam for e in source.data.edges) == source_seams, 'Sorgente modificata'
    assert tuple((layer.name, tuple(tuple(item.uv) for item in layer.data))
                 for layer in source.data.uv_layers) == source_uv, 'UV sorgente modificate'


if __name__ == '__main__':
    passed = failed = 0
    try:
        test_sphere_meridian()
        passed += 1
    except Exception:
        failed += 1
        REPORT['failure'] = traceback.format_exc()
        traceback.print_exc()
    try:
        with open(OUTPUT, 'w', encoding='utf-8') as handle:
            json.dump(REPORT, handle, indent=2, allow_nan=False)
        print('REPORT ' + OUTPUT)
    except Exception:
        if not failed:
            passed = 0
            failed = 1
        traceback.print_exc()
    print(f'RISULTATO passati={passed} falliti={failed} totale=1')
