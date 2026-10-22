# pylint: disable=invalid-name
"""
Intelligent UV Mapping — RIZOMUV BRIDGE

Headless bridge to the external RizomUV engine.
"""

import os
import subprocess
import tempfile

import bpy

from .rizomuv_script import build_lua_script
from .seam_marking import SeamMarker
from .uv_executor import MinimalUVExecutor
from .utils import (
    bulk_loop_attribute,
    bulk_loop_ranges,
    bulk_vertex_coords,
    loop_uv,
    polygon_loop_range,
    read_all_uvs,
    set_loop_uv,
    write_all_uvs,
)


# =============================================================================
# 12. RIZOMUV BRIDGE — Headless External Engine
# =============================================================================

class RizomUVBridge:
    """
    Headless bridge for RizomUV.

    Flow: mark seams -> export FBX -> generate Lua -> run RizomUV -> import FBX
    -> copy UV loops back -> clean up scene and temp files.
    """

    # ------------------------------------------------------------------
    # UV copy-back matching
    # ------------------------------------------------------------------

    # FBX stores coordinates as 32-bit floats, so the export -> RizomUV -> import
    # roundtrip quantizes every coordinate by roughly |coord| * 2^-24. The
    # tolerance therefore scales with the mesh size: FLOOR covers geometry near
    # the origin, RELATIVE keeps a model in metres from failing while a model in
    # millimetres does not start bridging genuinely distinct features.
    SPATIAL_TOL_FLOOR = 1e-5
    SPATIAL_TOL_RELATIVE = 1e-6

    # Above this fraction of unmatched faces the imported topology is considered
    # incompatible (RizomUV welded or split geometry, or a transform was baked),
    # and the copy-back fails instead of writing a half-corrupted layout.
    MAX_UNMAPPED_FRACTION = 0.01

    @staticmethod
    def _save_selection():
        try:
            return tuple(bpy.context.selected_objects)
        except Exception as exc:
            # B: best-effort, but a failure means the user's selection is lost.
            print(f"[IUV_RIZOMUV] Unable to save the previous selection: {exc}")
            return ()

    @classmethod
    def _restore_selection(cls, previous_selected):
        try:
            bpy.ops.object.select_all(action='DESELECT')
            for obj in previous_selected:
                if obj and obj.name in bpy.data.objects:
                    obj.select_set(True)
        except Exception as exc:
            # Runs from cleanup() inside a finally block. This handler must stay
            # broad: bpy.ops raises RuntimeError on a bad context, and letting it
            # escape here would mask the real error being propagated.
            print(f"[IUV_RIZOMUV] Unable to restore the previous selection: {exc}")

    @classmethod
    def _select_only(cls, obj):
        try:
            bpy.ops.object.select_all(action='DESELECT')
            obj.select_set(True)
            bpy.context.view_layer.objects.active = obj
        except Exception as exc:
            # C: without an isolated selection the FBX export would silently
            # include the wrong objects. Keep this broad: bpy.ops raises
            # RuntimeError on a bad context, which is exactly the case to catch.
            raise RuntimeError(
                f"Unable to isolate the selection on '{obj.name}': {exc}"
            ) from exc

    @staticmethod
    def _remove_temp_files(*paths):
        for path in paths:
            try:
                if path and os.path.exists(path):
                    os.remove(path)
            except OSError as exc:
                # B: cleanup is not fatal, but a locked temp file explains a
                # later "stale output" failure.
                print(f"[IUV_RIZOMUV] Unable to remove temp file {path}: {exc}")

    @staticmethod
    def _describe_exit_code(code):
        """Human-readable hint for common Windows fatal exit codes."""
        known = {
            0xC0000374: "heap corruption (RizomUV crashed internally)",
            0xC0000005: "access violation (RizomUV crashed internally)",
            0xC0000409: "stack buffer overrun (RizomUV crashed internally)",
            0xC000041D: "fatal exception in a callback (RizomUV crashed internally)",
        }

        try:
            unsigned = int(code) & 0xFFFFFFFF
        except (TypeError, ValueError):
            # A: exit codes are not integers on every platform.
            return ""

        label = known.get(unsigned)
        if not label:
            return ""

        return f" [0x{unsigned:08X}: {label}]"


    @classmethod
    def _spatial_tolerance(cls, vertices):
        """Match tolerance derived from the mesh extent (see constants)."""
        max_extent = 0.0
        for vert in vertices:
            co = vert.co
            max_extent = max(
                max_extent, abs(float(co[0])), abs(float(co[1])), abs(float(co[2]))
            )

        return max(cls.SPATIAL_TOL_FLOOR, cls.SPATIAL_TOL_RELATIVE * max_extent)

    @classmethod
    def _spatial_tolerance_from_coords(cls, coords):
        """Same tolerance, computed from a flat bulk-read coordinate buffer."""
        max_extent = 0.0
        for value in coords:
            av = abs(float(value))
            if av > max_extent:
                max_extent = av

        return max(cls.SPATIAL_TOL_FLOOR, cls.SPATIAL_TOL_RELATIVE * max_extent)

    @staticmethod
    def _face_centroid(mesh, poly):
        """Average vertex position of a polygon."""
        verts = mesh.vertices
        cx = cy = cz = 0.0
        count = 0

        for vi in poly.vertices:
            co = verts[int(vi)].co
            cx += float(co[0])
            cy += float(co[1])
            cz += float(co[2])
            count += 1

        if count == 0:
            return (0.0, 0.0, 0.0)

        inv = 1.0 / count
        return (cx * inv, cy * inv, cz * inv)

    @classmethod
    def match_and_copy_uvs(cls, src_mesh, src_uv_layer, dst_mesh, dst_uv_layer):
        """
        Copies UVs from src to dst by SPATIAL correspondence, never by array
        position.

        Why not by index: RizomUV reorders geometry during unwrap and packing,
        and the FBX roundtrip does not guarantee a stable vertex/face/loop
        order. Copying `loop N -> loop N` therefore assigns each UV to an
        essentially random face, which is exactly the observed failure.

        Why face centroids and not vertex normals: a vertex on a seam is shared
        by several loops at the *same* position, so position alone is ambiguous.
        Normals disambiguate only when the seam also creates an angle - a seam
        across a flat surface has identical normals on both sides and would be
        matched at random. A face centroid is unique per face regardless of
        flatness, so faces are paired first, and loops are then matched inside
        the already-paired faces where the only remaining ambiguity is a face
        having two vertices at the same position, which no valid mesh has.

        Complexity: O(F) average. Faces are hashed into a uniform grid whose
        cell size is the match tolerance, so each lookup inspects a constant
        number of cells, and matching loops inside a paired face is O(k^2) with
        k the (small) vertex count of that face.

        Returns (copied_loops, unmatched_faces, total_faces).
        """
        src_polys = getattr(src_mesh, "polygons", [])
        dst_polys = getattr(dst_mesh, "polygons", [])

        total = len(src_polys)
        if total == 0 or not dst_polys:
            return 0, total, total

        # Bulk path: one RNA call per attribute instead of one per element.
        # The RNA fallback below produces identical results and exists for
        # builds where foreach_get is not available on these collections.
        src_loop_count = len(getattr(src_mesh, "loops", []))
        dst_loop_count = len(getattr(dst_mesh, "loops", []))

        src_co = bulk_vertex_coords(src_mesh, len(getattr(src_mesh, "vertices", [])))
        dst_co = bulk_vertex_coords(dst_mesh, len(getattr(dst_mesh, "vertices", [])))
        src_loop_vert = bulk_loop_attribute(src_mesh, "vertex_index", src_loop_count)
        dst_loop_vert = bulk_loop_attribute(dst_mesh, "vertex_index", dst_loop_count)
        src_ranges = bulk_loop_ranges(src_mesh, total)
        dst_ranges = bulk_loop_ranges(dst_mesh, len(dst_polys))
        src_uvs = read_all_uvs(src_uv_layer, src_loop_count)
        dst_uvs = read_all_uvs(dst_uv_layer, dst_loop_count)

        if (src_co is None or dst_co is None
                or src_loop_vert is None or dst_loop_vert is None
                or src_ranges is None or dst_ranges is None
                or src_uvs is None or dst_uvs is None):
            return cls._match_and_copy_uvs_rna(
                src_mesh, src_uv_layer, dst_mesh, dst_uv_layer
            )

        return cls._match_and_copy_uvs_bulk(
            total,
            src_co, src_loop_vert, src_ranges, src_uvs,
            dst_co, dst_loop_vert, dst_ranges, dst_uvs,
            dst_uv_layer,
        )

    @classmethod
    def _match_and_copy_uvs_bulk(
        cls, total,
        src_co, src_loop_vert, src_ranges, src_uvs,
        dst_co, dst_loop_vert, dst_ranges, dst_uvs,
        dst_uv_layer,
    ):
        """Bulk implementation of match_and_copy_uvs (see its docstring)."""
        tol = cls._spatial_tolerance_from_coords(dst_co)
        tol_sq = tol * tol

        def cell_of(x, y, z):
            return (int(x // tol), int(y // tol), int(z // tol))

        def centroid(coords, loop_vert, start, count):
            cx = cy = cz = 0.0
            for i in range(start, start + count):
                vi = int(loop_vert[i]) * 3
                cx += float(coords[vi])
                cy += float(coords[vi + 1])
                cz += float(coords[vi + 2])
            inv = 1.0 / max(1, count)
            return (cx * inv, cy * inv, cz * inv)

        src_starts, src_totals = src_ranges
        dst_starts, dst_totals = dst_ranges

        # Spatial index over destination face centroids.
        grid = {}
        dst_centroids = []

        for di in range(len(dst_starts)):
            c = centroid(dst_co, dst_loop_vert, dst_starts[di], dst_totals[di])
            dst_centroids.append(c)
            grid.setdefault(cell_of(c[0], c[1], c[2]), []).append(di)

        claimed_faces = set()
        copied = 0
        unmatched = 0
        dirty = False

        for si_face in range(total):
            s_start = src_starts[si_face]
            s_count = src_totals[si_face]
            sc = centroid(src_co, src_loop_vert, s_start, s_count)
            cx, cy, cz = cell_of(sc[0], sc[1], sc[2])

            best_di = -1
            best_dist = tol_sq

            for gx in (cx - 1, cx, cx + 1):
                for gy in (cy - 1, cy, cy + 1):
                    for gz in (cz - 1, cz, cz + 1):
                        for di in grid.get((gx, gy, gz), ()):
                            if di in claimed_faces:
                                continue
                            if dst_totals[di] != s_count:
                                continue

                            dco = dst_centroids[di]
                            dx = dco[0] - sc[0]
                            dy = dco[1] - sc[1]
                            dz = dco[2] - sc[2]
                            dist = dx * dx + dy * dy + dz * dz

                            if dist <= best_dist:
                                best_dist = dist
                                best_di = di

            if best_di < 0:
                unmatched += 1
                continue

            claimed_faces.add(best_di)
            d_start = dst_starts[best_di]
            d_end = d_start + dst_totals[best_di]

            # Pair the loops of the two matched faces by vertex position. The
            # winding may be rotated or reversed by the roundtrip, so this is a
            # positional match rather than an offset.
            used = set()

            for si in range(s_start, s_start + s_count):
                svi = int(src_loop_vert[si]) * 3
                sx = float(src_co[svi])
                sy = float(src_co[svi + 1])
                sz = float(src_co[svi + 2])

                target = -1
                for dj in range(d_start, d_end):
                    if dj in used:
                        continue

                    dvi = int(dst_loop_vert[dj]) * 3
                    dx = float(dst_co[dvi]) - sx
                    dy = float(dst_co[dvi + 1]) - sy
                    dz = float(dst_co[dvi + 2]) - sz

                    if dx * dx + dy * dy + dz * dz <= tol_sq:
                        target = dj
                        break

                if target < 0:
                    continue

                used.add(target)
                dst_uvs[target * 2] = src_uvs[si * 2]
                dst_uvs[target * 2 + 1] = src_uvs[si * 2 + 1]
                copied += 1
                dirty = True

        if dirty and not write_all_uvs(dst_uv_layer, dst_uvs):
            # The whole point of the copy-back is the write; report it honestly.
            print("[IUV_RIZOMUV] Bulk UV write failed; no UVs were copied.")
            return 0, total, total

        return copied, unmatched, total

    @classmethod
    def _match_and_copy_uvs_rna(cls, src_mesh, src_uv_layer, dst_mesh, dst_uv_layer):
        """
        Per-element RNA fallback for match_and_copy_uvs.

        Same algorithm and same results as the bulk path, one RNA call per
        element. Kept for builds where foreach_get is unavailable.
        """
        src_polys = getattr(src_mesh, "polygons", [])
        dst_polys = getattr(dst_mesh, "polygons", [])
        src_verts = getattr(src_mesh, "vertices", [])
        dst_verts = getattr(dst_mesh, "vertices", [])

        total = len(src_polys)
        if total == 0 or not dst_polys:
            return 0, total, total

        tol = cls._spatial_tolerance(dst_verts)
        tol_sq = tol * tol

        def cell_of(point):
            return (
                int(point[0] // tol),
                int(point[1] // tol),
                int(point[2] // tol),
            )

        # Spatial index over destination face centroids.
        grid = {}
        dst_centroids = []

        for di, poly in enumerate(dst_polys):
            centroid = cls._face_centroid(dst_mesh, poly)
            dst_centroids.append(centroid)
            grid.setdefault(cell_of(centroid), []).append(di)

        claimed_faces = set()
        copied = 0
        unmatched = 0

        for src_poly in src_polys:
            centroid = cls._face_centroid(src_mesh, src_poly)
            cx, cy, cz = cell_of(centroid)

            best_di = -1
            best_dist = tol_sq

            for gx in (cx - 1, cx, cx + 1):
                for gy in (cy - 1, cy, cy + 1):
                    for gz in (cz - 1, cz, cz + 1):
                        for di in grid.get((gx, gy, gz), ()):
                            if di in claimed_faces:
                                continue
                            if len(dst_polys[di].vertices) != len(src_poly.vertices):
                                continue

                            dco = dst_centroids[di]
                            dx = dco[0] - centroid[0]
                            dy = dco[1] - centroid[1]
                            dz = dco[2] - centroid[2]
                            dist = dx * dx + dy * dy + dz * dz

                            if dist <= best_dist:
                                best_dist = dist
                                best_di = di

            if best_di < 0:
                unmatched += 1
                continue

            claimed_faces.add(best_di)
            dst_poly = dst_polys[best_di]

            src_start, src_end = polygon_loop_range(src_poly)
            dst_start, dst_end = polygon_loop_range(dst_poly)

            # Pair the loops of the two matched faces by vertex position. The
            # winding may be rotated or reversed by the roundtrip, so this is a
            # positional match rather than an offset.
            used = set()

            for si in range(src_start, src_end):
                s_co = src_verts[int(src_mesh.loops[si].vertex_index)].co
                sx, sy, sz = float(s_co[0]), float(s_co[1]), float(s_co[2])

                target = -1
                for dj in range(dst_start, dst_end):
                    if dj in used:
                        continue

                    d_co = dst_verts[int(dst_mesh.loops[dj].vertex_index)].co
                    dx = float(d_co[0]) - sx
                    dy = float(d_co[1]) - sy
                    dz = float(d_co[2]) - sz

                    if dx * dx + dy * dy + dz * dz <= tol_sq:
                        target = dj
                        break

                if target < 0:
                    continue

                used.add(target)
                uv = loop_uv(src_uv_layer, si)
                if uv is not None and set_loop_uv(dst_uv_layer, target, uv[0], uv[1]):
                    copied += 1

        return copied, unmatched, total


    @classmethod
    def export_object_fbx(cls, obj, filepath):
        """
        Exports a single object to FBX, UVs included.

        Shared by the automated bridge and by the manual Export operator, so
        both produce byte-identical files and a fix to one benefits the other.
        """
        cls._select_only(obj)

        try:
            with bpy.context.temp_override(object=obj, active_object=obj):
                bpy.ops.export_scene.fbx(
                    filepath=filepath,
                    use_selection=True,
                    apply_scale_options='FBX_SCALE_ALL',
                    add_leaf_bones=False,
                    use_mesh_modifiers=False,
                    bake_space_transform=False,
                )
        except TypeError:
            # A: FBX exporter options differ between Blender versions.
            with bpy.context.temp_override(object=obj, active_object=obj):
                bpy.ops.export_scene.fbx(
                    filepath=filepath,
                    use_selection=True,
                )

        if not os.path.isfile(filepath):
            raise RuntimeError(f"The FBX export did not produce a file at {filepath}.")

        return filepath

    @classmethod
    def fit_uv_layer_to_tile(cls, mesh, uv_layer, margin_uv=0.0):
        """
        Uniformly rescales and recentres a UV layer so every loop lies inside
        the 0-1 tile, keeping `margin_uv` of clearance on each side.

        A no-op when the layout already fits. Returns a dict describing what
        happened: {"fitted": bool, "scale": float, "outside_loops": int,
        "bounds_before": (min_u, max_u, min_v, max_v)}.
        """
        info = {"fitted": False, "scale": 1.0, "outside_loops": 0,
                "bounds_before": None}

        data = getattr(uv_layer, "data", None)
        if not data or len(data) == 0:
            return info

        eps = 1e-5
        margin = min(max(float(margin_uv or 0.0), 0.0), 0.45)

        min_u = min(l.uv.x for l in data)
        max_u = max(l.uv.x for l in data)
        min_v = min(l.uv.y for l in data)
        max_v = max(l.uv.y for l in data)
        info["bounds_before"] = (min_u, max_u, min_v, max_v)

        outside = sum(
            1 for l in data
            if l.uv.x < -eps or l.uv.x > 1.0 + eps
            or l.uv.y < -eps or l.uv.y > 1.0 + eps)
        info["outside_loops"] = outside
        if outside == 0:
            return info

        width = max(max_u - min_u, eps)
        height = max(max_v - min_v, eps)
        avail = max(1.0 - 2.0 * margin, eps)
        scale = min(avail / width, avail / height, 1.0)

        centre_u = 0.5 * (min_u + max_u)
        centre_v = 0.5 * (min_v + max_v)
        for l in data:
            l.uv.x = (l.uv.x - centre_u) * scale + 0.5
            l.uv.y = (l.uv.y - centre_v) * scale + 0.5

        # Numeric drift guard: nudge the layout back if a loop still pokes
        # out (can only happen by a few eps after a uniform scale).
        min_u = min(l.uv.x for l in data)
        max_u = max(l.uv.x for l in data)
        min_v = min(l.uv.y for l in data)
        max_v = max(l.uv.y for l in data)
        shift_u = 0.0
        shift_v = 0.0
        if min_u < margin:
            shift_u = margin - min_u
        elif max_u > 1.0 - margin:
            shift_u = (1.0 - margin) - max_u
        if min_v < margin:
            shift_v = margin - min_v
        elif max_v > 1.0 - margin:
            shift_v = (1.0 - margin) - max_v
        if shift_u or shift_v:
            for l in data:
                l.uv.x += shift_u
                l.uv.y += shift_v

        info["fitted"] = True
        info["scale"] = scale
        return info

    @classmethod
    def import_uvs_from_fbx(cls, obj, settings, filepath, margin_uv=0.0):
        """
        Imports an FBX and copies its UVs onto `obj` by spatial correspondence.

        Shared by finalize() and by the manual Import operator. The imported
        object is always removed, whether the copy succeeded or not.

        After the copy the layer is checked against the 0-1 tile: RizomUV's
        packer grows the packing box instead of shrinking islands when the
        layout does not fit (the post-layout scaling that would force a fit
        is not reachable through the 2025.0 link API), so anything outside
        the tile is uniformly scaled back into it here, keeping `margin_uv`
        of breathing room. Relative island sizes are preserved.

        Returns (uv_layer_name, copied_loops, unmatched_faces, total_faces,
        fit_info) where fit_info describes the tile-fit pass.
        """
        if not os.path.isfile(filepath):
            raise RuntimeError(f"FBX not found: {filepath}")

        imported_obj = None

        try:
            objects_before = {o.name for o in bpy.data.objects}

            try:
                with bpy.context.temp_override(object=obj, active_object=obj):
                    bpy.ops.import_scene.fbx(filepath=filepath)
            except Exception as exc:
                raise RuntimeError(f"FBX import failed: {exc}") from exc

            new_objects = [o for o in bpy.data.objects if o.name not in objects_before]

            best_vertices = -1
            for candidate in new_objects:
                if candidate.type != 'MESH':
                    continue
                vcount = len(getattr(candidate.data, "vertices", []))
                if vcount > best_vertices:
                    best_vertices = vcount
                    imported_obj = candidate

            if not imported_obj:
                raise RuntimeError("No mesh object found after the FBX import.")

            src_mesh = imported_obj.data
            dst_mesh = obj.data

            if len(getattr(src_mesh, "uv_layers", [])) == 0:
                raise RuntimeError("The imported FBX contains no UV layer to copy.")

            src_uv_layer = (
                getattr(src_mesh.uv_layers, "active", None) or src_mesh.uv_layers[0]
            )

            dst_uv_name = str(getattr(settings, "uv_layer_name", "SmartUV") or "SmartUV")
            dst_uv_layer = MinimalUVExecutor.ensure_uv_layer(dst_mesh, dst_uv_name)

            if dst_uv_layer is None:
                raise RuntimeError("Unable to create the destination UV layer.")

            # Copy-back by spatial correspondence: loop order is not preserved
            # across an FBX roundtrip, so an index-based copy would assign the
            # UVs to essentially random faces.
            copied, unmatched, total = cls.match_and_copy_uvs(
                src_mesh, src_uv_layer, dst_mesh, dst_uv_layer
            )

            if total == 0:
                raise RuntimeError("The imported mesh has no faces to copy back.")

            # copied == 0 is fatal regardless of the threshold: a run that wrote
            # nothing is not a success, however few faces were unmatched.
            if copied == 0 or (unmatched / float(total)) > cls.MAX_UNMAPPED_FRACTION:
                raise RuntimeError(
                    f"UV copy-back failed: {unmatched} of {total} faces could not be "
                    f"matched to the original mesh by position ({copied} loops "
                    "written). The imported topology does not correspond to the "
                    "exported one; the original UVs were left untouched."
                )

            fit_info = cls.fit_uv_layer_to_tile(
                dst_mesh, dst_uv_layer, margin_uv=margin_uv)

            if hasattr(dst_mesh, "update"):
                try:
                    dst_mesh.update()
                except (AttributeError, TypeError):
                    # A: mesh.update() is not required on every Blender version.
                    pass

            return dst_uv_name, copied, unmatched, total, fit_info

        finally:
            # imported_obj.name raises ReferenceError when the object was
            # already removed from bpy.data, and this runs inside a finally:
            # letting that escape would mask the real exception above.
            try:
                imported_name = (
                    imported_obj.name if imported_obj is not None else None
                )
            except ReferenceError:
                imported_name = None

            if imported_name is not None and imported_name in bpy.data.objects:
                try:
                    data_to_remove = getattr(imported_obj, "data", None)
                    bpy.data.objects.remove(imported_obj, do_unlink=True)
                    if data_to_remove is not None and data_to_remove.users == 0:
                        bpy.data.meshes.remove(data_to_remove)
                except Exception as exc:
                    # Best-effort: never let cleanup replace the real exception.
                    print(f"[IUV_RIZOMUV] Unable to remove the imported object: {exc}")

    # ------------------------------------------------------------------
    # Phased execution
    #
    # The external process is split into prepare / launch / finalize so the
    # caller can poll it from a modal operator instead of blocking Blender's
    # main thread. `execute()` keeps the simple blocking flow for convenience.
    # ------------------------------------------------------------------

    @classmethod
    def build_command(cls, rz_path, lua_path, settings):
        """
        Builds the command line.

        RizomUV's CLI flags vary between releases, so the arguments are
        user-editable. `-cfi <script>` runs a Lua file; some builds still show
        the GUI with it, which is why extra arguments are exposed.
        """
        template = str(getattr(settings, "rizomuv_args", "") or "").strip()
        if not template:
            template = "-cfi {script}"

        command = [rz_path]

        for token in template.split():
            command.append(token.replace("{script}", lua_path))

        return command

    @classmethod
    def prepare(cls, obj, settings, is_seam, margin_result, report=None):
        """
        Marks seams, pre-unwraps, exports the FBX and writes the Lua script.

        IMPORTANT — how the cuts reach RizomUV:
        FBX has no concept of a Blender UV seam, so `use_seam` flags are lost on
        export. The mesh is unwrapped natively first (that unwrap does honour
        the seams) and the resulting UV island borders travel inside the FBX.
        RizomUV then optimizes and packs those existing shells. Loop topology is
        untouched, so copying the UVs back stays valid.

        Returns a context dict for launch()/finalize().
        """
        if not obj or obj.type != 'MESH':
            raise RuntimeError("RizomUVBridge requires a valid mesh object.")

        if margin_result is None or not getattr(margin_result, "ok", False):
            raise RuntimeError("A valid margin calculation is required for the bridge.")

        rz_path = str(getattr(settings, "rizomuv_path", "") or "").strip()
        if not os.path.isfile(rz_path):
            raise FileNotFoundError(f"RizomUV not found at path: {rz_path}")

        def _say(level, message):
            if report:
                try:
                    report(level, message)
                except Exception as exc:
                    # B: a broken report callback must not take down the bridge.
                    print(f"[IUV_RIZOMUV] Report callback failed ({level}): {message} [{exc}]")

        tmp_dir = tempfile.gettempdir()
        safe_name = "".join(
            c for c in obj.name if c.isalnum() or c in ("_", "-")
        ) or "object"

        ctx = {
            "obj": obj,
            "rz_path": rz_path,
            "export_path": os.path.join(tmp_dir, f"iuv_{safe_name}_export.fbx"),
            "import_path": os.path.join(tmp_dir, f"iuv_{safe_name}_import.fbx"),
            "lua_path": os.path.join(tmp_dir, f"iuv_{safe_name}_script.lua"),
            "log_path": os.path.join(tmp_dir, f"iuv_{safe_name}_rizomuv.log"),
            "previous_selected": cls._save_selection(),
            "keep_temp": bool(getattr(settings, "keep_temp_files", False)),
            "margin_result": margin_result,
        }

        # Stale output from an earlier run would be mistaken for a fresh result.
        cls._remove_temp_files(ctx["import_path"], ctx["log_path"])

        # 1. Seams + native pre-unwrap.
        success, message = SeamMarker.mark_real_seams(obj.data, is_seam)
        if not success:
            raise RuntimeError(f"Unable to apply seams before FBX export: {message}")

        seam_count = sum(1 for s in is_seam if s)
        if seam_count == 0:
            _say("WARNING", "No seams planned: RizomUV will receive a single UV shell.")

        try:
            MinimalUVExecutor.execute_unwrap(
                obj=obj,
                settings=settings,
                margin_uv=margin_result.margin_uv,
                use_seams=seam_count > 0,
            )
        except Exception as exc:
            raise RuntimeError(f"Pre-unwrap before the FBX export failed: {exc}") from exc

        # 2. Export the object alone, UVs included.
        cls.export_object_fbx(obj, ctx["export_path"])

        # 3. Lua script. Margins go in normalized UV units; kept minimal because
        #    every extra parameter is a chance to hit a version mismatch.
        margin_uv = float(margin_result.margin_uv)

        lua_script = build_lua_script(
            export_path=ctx["export_path"],
            import_path=ctx["import_path"],
            margin_uv=margin_uv,
            texture_resolution=margin_result.texture_resolution,
            margin_px=margin_result.margin_px,
        )

        with open(ctx["lua_path"], "w", encoding="utf-8") as lf:
            lf.write(lua_script)

        ctx["command"] = cls.build_command(rz_path, ctx["lua_path"], settings)

        if ctx["keep_temp"]:
            print(f"[IUV_RIZOMUV] Command: {' '.join(ctx['command'])}")
            print(f"[IUV_RIZOMUV] Lua script: {ctx['lua_path']}")
            print(f"[IUV_RIZOMUV] Contents:\n{lua_script}")

        return ctx

    @classmethod
    def launch(cls, ctx):
        """
        Starts RizomUV without waiting. Returns the Popen handle.

        Output goes to a log file, not a PIPE. A pipe that is never drained
        fills its OS buffer (~64 KB on Windows) and the child then blocks on
        its next write: the process never exits, the modal poll hits the
        timeout and the run is killed for no real reason. Chatty RizomUV
        builds crossed that buffer on every run. The log file also survives
        the process, which makes failed runs diagnosable afterwards.
        """
        log_file = None
        log_path = ctx.get("log_path")

        if log_path:
            try:
                log_file = open(log_path, "wb")
            except OSError as exc:
                # B: losing the log degrades diagnostics, not the run itself.
                print(f"[IUV_RIZOMUV] Unable to open the RizomUV log file: {exc}")

        try:
            if log_file is not None:
                proc = subprocess.Popen(
                    ctx["command"],
                    stdout=log_file,
                    stderr=subprocess.STDOUT,
                )
                ctx["_log_file"] = log_file
            else:
                proc = subprocess.Popen(
                    ctx["command"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
        except Exception as exc:
            if log_file is not None:
                try:
                    log_file.close()
                except Exception:
                    # A: closing an already-closed handle raises. The log has been
                    # written by this point, so nothing is lost.
                    pass
            raise RuntimeError(f"Unable to launch RizomUV: {exc}") from exc

        ctx["proc"] = proc
        return proc

    @classmethod
    def _close_log_file(cls, ctx):
        """Closes the process log handle, if one is open."""
        log_file = ctx.pop("_log_file", None)
        if log_file is not None:
            try:
                log_file.close()
            except Exception:
                # A: closing an already-closed handle raises. The log has been
                # written by this point, so nothing is lost.
                pass

    @classmethod
    def terminate(cls, ctx):
        """Kills the external process if it is still running."""
        proc = ctx.get("proc")
        if proc is None or proc.poll() is not None:
            cls._close_log_file(ctx)
            return

        for stop in (proc.terminate, proc.kill):
            try:
                stop()
                proc.wait(timeout=5)
                cls._close_log_file(ctx)
                return
            except (OSError, subprocess.SubprocessError) as exc:
                # B: fall through to the harder stop method, but say so - a
                # process that refuses to die will otherwise hold the temp files.
                print(f"[IUV_RIZOMUV] Stop attempt failed: {exc}")
                continue

        cls._close_log_file(ctx)

    @classmethod
    def check_exit(cls, ctx, returncode):
        """Raises a descriptive error when the process failed."""
        cls._close_log_file(ctx)

        output = ""
        log_path = ctx.get("log_path")

        if log_path and os.path.isfile(log_path):
            try:
                with open(log_path, "rb") as handle:
                    handle.seek(0, os.SEEK_END)
                    size = handle.tell()
                    # The tail is what carries the error; the head is banner.
                    handle.seek(max(0, size - 8192))
                    output = handle.read().decode("utf-8", errors="ignore").strip()
            except OSError as exc:
                # B: without the output a failed run is much harder to diagnose.
                print(f"[IUV_RIZOMUV] Unable to read the RizomUV log: {exc}")

        if output:
            print(f"[IUV_RIZOMUV] output:\n{output}")

        if returncode != 0:
            details = output or "no output captured"
            raise RuntimeError(
                f"RizomUV exited with code {returncode}"
                f"{cls._describe_exit_code(returncode)}. "
                f"Details: {details}. Lua script kept at: {ctx['lua_path']}"
            )

    @classmethod
    def finalize(cls, obj, settings, ctx):
        """Imports the processed FBX and copies the UVs back."""
        import_path = ctx["import_path"]

        if not os.path.isfile(import_path):
            raise RuntimeError(
                "RizomUV did not produce the output FBX. The Lua script may not "
                f"have reached ZomSave. Script kept at: {ctx['lua_path']}"
            )

        margin_result = ctx["margin_result"]

        uv_name, copied, unmatched, total, fit_info = cls.import_uvs_from_fbx(
            obj, settings, import_path,
            margin_uv=float(getattr(margin_result, "margin_uv", 0.0) or 0.0),
        )

        if unmatched:
            print(
                f"[IUV_RIZOMUV] {unmatched} of {total} faces were not matched "
                "and kept their previous UVs."
            )

        return {
            "uv_layer": uv_name,
            "copied_loops": copied,
            "unmatched_faces": unmatched,
            "total_faces": total,
            "margin_px": margin_result.margin_px,
            "texture_resolution": margin_result.texture_resolution,
            "fit_to_tile": bool(fit_info.get("fitted")),
            "fit_scale": float(fit_info.get("scale", 1.0)),
        }

    @classmethod
    def cleanup(cls, ctx, failed=False):
        """Restores the selection and removes (or keeps) the temp files."""
        cls._restore_selection(ctx.get("previous_selected", ()))

        paths = (
            ctx.get("export_path"),
            ctx.get("import_path"),
            ctx.get("lua_path"),
            ctx.get("log_path"),
        )

        # Temp files survive a failure so the Lua and FBX can be replayed by hand.
        if failed or ctx.get("keep_temp"):
            print(
                "[IUV_RIZOMUV] Temp files kept for inspection:\n"
                f"  Lua:    {ctx.get('lua_path')}\n"
                f"  Export: {ctx.get('export_path')}\n"
                f"  Import: {ctx.get('import_path')}\n"
                f"  Log:    {ctx.get('log_path')}"
            )
        else:
            cls._remove_temp_files(*paths)

    @classmethod
    def execute(cls, obj, settings, is_seam, margin_result, report=None):
        """Blocking convenience wrapper around the phased API."""
        ctx = cls.prepare(obj, settings, is_seam, margin_result, report)
        failed = False

        try:
            cls.launch(ctx)

            try:
                timeout = max(10, int(getattr(settings, "rizomuv_timeout", 300) or 300))
            except (AttributeError, TypeError, ValueError):
                # B: a broken setting should not stop the run, but must be visible.
                print("[IUV_RIZOMUV] Invalid rizomuv_timeout setting; using 300 seconds.")
                timeout = 300

            try:
                returncode = ctx["proc"].wait(timeout=timeout)
            except subprocess.TimeoutExpired as exc:
                cls.terminate(ctx)
                raise RuntimeError(
                    f"RizomUV exceeded the execution timeout ({timeout}s)."
                ) from exc

            cls.check_exit(ctx, returncode)
            return cls.finalize(obj, settings, ctx)

        except Exception as exc:
            failed = True
            raise RuntimeError(f"RizomUV Bridge failed: {exc}") from exc

        finally:
            cls.cleanup(ctx, failed)
