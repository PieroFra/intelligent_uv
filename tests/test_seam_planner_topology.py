# -*- coding: utf-8 -*-
"""Integration contract for disk regions produced by the seam planner."""

import importlib
import math
import os
import sys
import traceback

import bpy
from mathutils import Euler

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(ROOT))
PACKAGE = os.path.basename(ROOT)


def module(name):
    return importlib.import_module(PACKAGE + '.' + name)


def snapshot(mesh):
    return (tuple(tuple(v.co) for v in mesh.vertices),
            tuple(tuple(e.vertices) for e in mesh.edges),
            tuple((tuple(p.vertices), p.material_index) for p in mesh.polygons),
            tuple(e.use_seam for e in mesh.edges),
            tuple((layer.name, tuple(tuple(item.uv) for item in layer.data))
                  for layer in mesh.uv_layers))


def settings(curvature_threshold):
    value = bpy.context.scene.intelligent_uv_settings
    value.preserve_existing_seams = True
    value.curvature_threshold = curvature_threshold
    value.auto_curvature_threshold = False
    value.separate_by_material = False
    value.concave_seam_bias = 0.0
    value.prune_dangling_seams = True
    value.minimum_island_face_count = 1
    return value


def plan_and_regions(obj, configuration):
    before = snapshot(obj.data)
    analysis = module('mesh_analysis').MeshAnalyzer.analyze(obj.data)
    assert analysis.ok, 'Analisi mesh fallita'
    material = module('material_analysis').MaterialAnalyzer.analyze(obj)
    assert material.ok, 'Analisi materiali fallita'
    plan = module('seam_planning').SeamPlanner.plan(analysis, material, configuration)
    assert plan.ok, 'Pianificazione seam fallita'
    mask = tuple(plan.is_seam)
    assert len(mask) == len(obj.data.edges), 'Maschera seam incompatibile con la mesh'
    assert all(not edge.use_seam or mask[edge.index] for edge in obj.data.edges), 'Seam iniziali non preservate'
    regions = module('seam_topology').analyze_regions(obj.data, mask)
    assert regions, 'Nessuna regione prodotta dal piano'
    assert all(region.is_disk for region in regions), 'Il planner lascia regioni non disco'
    assert snapshot(obj.data) == before, 'Analisi o pianificazione modificano mesh, seam o UV iniziali'
    return mask, regions


def sphere_case(rotated):
    if bpy.context.object and bpy.context.object.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    bpy.ops.mesh.primitive_uv_sphere_add(segments=32, ring_count=16, radius=1.0,
                                        location=(0, 0, 0))
    obj = bpy.context.object
    mesh = obj.data
    try:
        assert len(mesh.vertices) == 482 and len(mesh.polygons) == 512, 'Fixture sfera 32x16 inattesa'
        cap_height = math.cos(math.pi / 16)
        for edge in mesh.edges:
            a, b = (mesh.vertices[index].co for index in edge.vertices)
            edge.use_seam = (abs(a.z - b.z) < 1e-6
                             and abs(abs(a.z) - cap_height) < 1e-6)
        initial = tuple(edge.use_seam for edge in mesh.edges)
        assert sum(initial) == 64, 'Fixture senza i due anelli seam dei cap'
        if rotated:
            rotation = Euler((math.pi / 7, math.pi / 5, math.pi / 3)).to_matrix()
            for vertex in mesh.vertices:
                vertex.co = rotation @ vertex.co
            mesh.update()
        initial_regions = module('seam_topology').analyze_regions(mesh, initial)
        assert initial_regions and any(not region.is_disk for region in initial_regions), 'Fixture già interamente disco prima del planner'
        mask, regions = plan_and_regions(obj, settings(60.0))
        assert any(seam and not initial[i] for i, seam in enumerate(mask)), 'Nessun taglio aggiunto sulla sfera non disco'
    finally:
        bpy.data.objects.remove(obj, do_unlink=True)
        bpy.data.meshes.remove(mesh)


def test_sphere_disk_regions():
    sphere_case(False)


def test_rotated_sphere_disk_regions():
    sphere_case(True)


def test_open_disk_no_superfluous_cuts():
    mesh = bpy.data.meshes.new('PlannerOpenDisk')
    mesh.from_pydata([(0, 0, 0), (1, 0, 0), (2, 0, 0),
                      (0, 1, 0), (1, 1, 0), (2, 1, 0)], [],
                     [(0, 1, 4, 3), (1, 2, 5, 4)])
    mesh.update()
    obj = bpy.data.objects.new('PlannerOpenDisk', mesh)
    bpy.context.scene.collection.objects.link(obj)
    try:
        initial = tuple(edge.use_seam for edge in mesh.edges)
        regions = module('seam_topology').analyze_regions(mesh, initial)
        assert len(regions) == 1 and regions[0].is_disk, 'Fixture aperta non costituita da un disco'
        mask, regions = plan_and_regions(obj, settings(180.0))
        incidence = [0] * len(mesh.edges)
        for loop in mesh.loops:
            incidence[loop.edge_index] += 1
        assert sum(count == 2 for count in incidence) == 1, 'Fixture senza unico arco interno condiviso'
        assert all(not mask[i] for i, count in enumerate(incidence) if count == 2), 'Taglio interno superfluo sul disco piano'
        assert len(regions) == 1, 'Il planner suddivide inutilmente il disco aperto'
    finally:
        bpy.data.objects.remove(obj, do_unlink=True)
        bpy.data.meshes.remove(mesh)


if __name__ == '__main__':
    passed = failed = 0
    tests = (test_sphere_disk_regions, test_rotated_sphere_disk_regions,
             test_open_disk_no_superfluous_cuts)
    try:
        importlib.import_module(PACKAGE).register()
    except Exception:
        failed = len(tests)
        traceback.print_exc()
    else:
        for test in tests:
            try:
                test()
                passed += 1
            except Exception:
                failed += 1
                traceback.print_exc()
    print(f'RISULTATO passati={passed} falliti={failed} totale={len(tests)}')
