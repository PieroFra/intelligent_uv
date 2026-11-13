# -*- coding: utf-8 -*-
"""Default pipeline on a UV sphere: VSA cluster and border-seam limits."""

import importlib
import os
import sys
import traceback

import bpy

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(ROOT))
PACKAGE = os.path.basename(ROOT)


def test_default_pipeline_sphere():
    addon = importlib.import_module(PACKAGE)
    addon.register()

    # Reset every writable setting to its RNA default so the run uses the
    # scene defaults: VSA seam method with automatic parameters enabled.
    settings = bpy.context.scene.intelligent_uv_settings
    for prop in settings.bl_rna.properties:
        if prop.identifier == 'rna_type' or prop.is_readonly or prop.type == 'COLLECTION':
            continue
        try:
            setattr(settings, prop.identifier, prop.default)
        except Exception:
            pass

    captured = []
    original_report = addon.IntelligentUV_OT_Run._report
    original_busy = addon.IntelligentUV_OT_Run._busy

    try:
        # Sphere: 32 segments x 16 rings, radius as in
        # _esperimenti/vetrina/build_scene.py:92. Seams and UV layers are
        # cleared so the run starts from a clean mesh.
        bpy.ops.mesh.primitive_uv_sphere_add(
            radius=0.7, segments=32, ring_count=16, location=(0.0, 0.0, 0.0),
            calc_uvs=False,
        )
        obj = bpy.context.object
        assert obj is not None and obj.type == 'MESH', "Sfera di prova non creata"
        mesh = obj.data
        for edge in mesh.edges:
            edge.use_seam = False
        for layer in list(mesh.uv_layers):
            mesh.uv_layers.remove(layer)

        for item in bpy.context.view_layer.objects:
            item.select_set(False)
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj

        def _captured_report(self, msg_type, message):
            if message:
                captured.append((str(msg_type), str(message)))

        addon.IntelligentUV_OT_Run._report = _captured_report
        addon.IntelligentUV_OT_Run._busy = False

        result = bpy.ops.intelligent_uv.run()
        assert result == {'FINISHED'}, (
            "Run non terminato correttamente: " + repr(result)
        )

        fallback_lines = [msg for (_level, msg) in captured
                          if msg.startswith("Near-uniform dihedral angles")]
        assert len(fallback_lines) == 1, (
            "Nota di fallback sul planner non trovata: " + repr(fallback_lines)
        )

        # Final state: the seams marked on the mesh and the UV islands they
        # leave behind. Islands are the face components joined by non-seam
        # edges; both counts are read from the object data after the run.
        if obj.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        seam_keys = set()
        for edge in mesh.edges:
            if edge.use_seam:
                seam_keys.add(tuple(sorted(edge.key)))
        border_seams = len(seam_keys)

        parent = list(range(len(mesh.polygons)))

        def _find(index):
            while parent[index] != index:
                parent[index] = parent[parent[index]]
                index = parent[index]
            return index

        edge_faces = {}
        for poly in mesh.polygons:
            for key in poly.edge_keys:
                edge_faces.setdefault(tuple(sorted(key)), []).append(poly.index)
        for key, faces in edge_faces.items():
            if key in seam_keys or len(faces) != 2:
                continue
            root_a, root_b = _find(faces[0]), _find(faces[1])
            if root_a != root_b:
                parent[root_a] = root_b
        clusters = len({_find(index) for index in range(len(mesh.polygons))})

        # A uniform sphere has dihedral angles of about 11 degrees between
        # adjacent faces (P90-P10 spread well under 5 degrees), so the run
        # must leave shape clustering and use the seam planner. The planner
        # yields a few disc regions, not dozens of fragments. A smooth
        # closed sphere must be opened into two hemispheres by a clean
        # equatorial seam ring instead of being fragmented, so the result
        # stays compact: islands between 1 and 4, border seams between 1
        # and 64. The old VSA limits (about 131 clusters and 537 seams)
        # and the provisional limits (20 islands / 150 seams) must not
        # come back.
        assert seam_keys, "Nessuna seam marcata sulla sfera 32x16"
        assert 1 <= border_seams <= 64, (
            "Seam marcate {} fuori da [1, 64] su sfera 32x16 (radius 0.7): "
            "una sfera chiusa liscia va aperta in 2 emisferi da un anello "
            "equatoriale pulito.".format(border_seams)
        )
        assert 1 <= clusters <= 4, (
            "Isole UV {} fuori da [1, 4] su sfera 32x16 (radius 0.7): "
            "una sfera chiusa liscia va aperta in 2 emisferi da un anello "
            "equatoriale pulito.".format(clusters)
        )
    finally:
        addon.IntelligentUV_OT_Run._report = original_report
        addon.IntelligentUV_OT_Run._busy = original_busy
        try:
            addon.unregister()
        except Exception:
            pass


if __name__ == '__main__':
    passed = 0
    failed = 0
    try:
        test_default_pipeline_sphere()
        passed = 1
    except Exception:
        failed = 1
        traceback.print_exc()
    print("RISULTATO passati={} falliti={} totale=1".format(passed, failed))