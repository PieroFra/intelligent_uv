# pylint: disable=invalid-name
"""
Intelligent UV Mapping — NATIVE UV EXECUTOR

Native Blender unwrap, packing, coverage scaling and UV backup.
"""

import math
from contextlib import contextmanager

import bpy

from .utils import (
    loop_uv,
    read_all_uvs,
    set_loop_uv,
    uv_editor_override,
    write_all_uvs,
)


# =============================================================================
# 9. NATIVE UV EXECUTOR — Unwrap / Pack / Coverage
# =============================================================================

class MinimalUVExecutor:
    """
    Native Blender UV generation.

    - `unwrap` respects the seams marked by SeamMarker, so the resulting
      islands match the planned regions (Smart UV Project ignores seams and is
      used only as a fallback when no seam was produced).
    - packing and coverage scaling are separate steps so they always run,
      independently of the island analysis outcome.
    """

    @staticmethod
    def set_active_uv_layer(uv_layers, uv):
        """
        Makes `uv` the active UV layer and VERIFIES it took effect.

        This matters more than it looks. `uv.unwrap` and `uv.pack_islands`
        write to whatever layer is active, while the analysis reads the layer
        by name. If the assignment silently fails, the tool unwraps into one
        layer and then measures another: every island reports near-zero UV
        area, texel density normalization is skipped, and coverage scaling
        reports degenerate bounds — all while the operators claim success.

        Two mechanisms are tried (direct assignment, then the index), and the
        result is read back rather than assumed. Returns True on success.
        """
        if uv_layers is None or uv is None:
            return False

        target_name = getattr(uv, "name", None)

        def _is_active():
            try:
                current = getattr(uv_layers, "active", None)
                if current is uv:
                    return True
                return (
                    target_name is not None
                    and getattr(current, "name", None) == target_name
                )
            except (AttributeError, TypeError):
                return False

        try:
            uv_layers.active = uv
        except (AttributeError, TypeError):
            # A: direct assignment is not available on every Blender build.
            pass

        if _is_active():
            return True

        # Fallback: address the layer by index instead of by reference.
        try:
            for index, layer in enumerate(uv_layers):
                if layer is uv or getattr(layer, "name", None) == target_name:
                    uv_layers.active_index = index
                    break
        except (AttributeError, TypeError, IndexError):
            # A: active_index is not exposed on every Blender build.
            pass

        if _is_active():
            return True

        print(
            f"[IUV_UV_EXECUTOR] Could not activate UV layer '{target_name}'. "
            "Unwrapping would write to a different layer than the one measured."
        )
        return False

    @classmethod
    def ensure_uv_layer(cls, mesh, name):
        """
        Returns the target UV layer, creating it if needed, and makes it active.

        Raises when the layer cannot be made active: continuing would unwrap
        into one layer while reading another, which produces a silently empty
        result instead of a visible error.
        """
        uv_layers = getattr(mesh, "uv_layers", None)
        if uv_layers is None:
            return None

        uv = uv_layers.get(name)
        if not uv:
            try:
                uv = uv_layers.new(name=name)
            except (AttributeError, TypeError):
                # A: the keyword form of uv_layers.new() is not on every build.
                try:
                    uv = uv_layers.new()
                except (AttributeError, TypeError) as exc:
                    # C: without a UV layer the whole pipeline is pointless;
                    # failing here beats an opaque failure later during unwrap.
                    raise RuntimeError(
                        f"Unable to create UV layer '{name}': {exc}"
                    ) from exc

        if not cls.set_active_uv_layer(uv_layers, uv):
            raise RuntimeError(
                f"UV layer '{name}' exists but could not be made active. "
                "Unwrapping would write to a different layer than the one the "
                "analysis reads, producing empty islands and zero UV area."
            )

        return uv

    @staticmethod
    def get_uv_layer(mesh, name):
        try:
            uv_layers = getattr(mesh, "uv_layers", [])
            uv = uv_layers.get(name) if hasattr(uv_layers, "get") else None
            if not uv and len(uv_layers) > 0:
                uv = uv_layers[0]
            return uv
        except (AttributeError, TypeError, KeyError, IndexError) as exc:
            # B: callers treat None as "no layer", but a failed lookup on a mesh
            # that should have one needs to be traceable.
            print(f"[IUV_UV_EXECUTOR] Unable to read UV layer '{name}': {exc}")
            return None

    @classmethod
    def backup_uv_layer(cls, mesh, name):
        """
        Copies an existing UV layer to '<name>_backup' before it is overwritten.

        Undo across a modal operator that shells out to an external process is
        not something to rely on, so the previous layout gets an explicit copy.
        Returns (backed_up: bool, message: str).
        """
        try:
            uv_layers = getattr(mesh, "uv_layers", None)
            if uv_layers is None:
                return False, "No UV layers on this mesh."

            source = uv_layers.get(name)
            if source is None:
                return False, "No existing UV layer to back up."

            backup_name = f"{name}_backup"

            existing = uv_layers.get(backup_name)
            if existing is not None:
                uv_layers.remove(existing)

            backup = uv_layers.new(name=backup_name)
            if backup is None:
                return False, "Unable to create the backup UV layer."

            count = min(len(source.data), len(backup.data))

            # Bulk copy: one RNA call each way instead of two per loop.
            copied = False
            flat = read_all_uvs(source, count)
            if flat is not None and len(backup.data) == count:
                copied = write_all_uvs(backup, flat)

            if not copied:
                for i in range(count):
                    backup.data[i].uv = (source.data[i].uv[0], source.data[i].uv[1])

            # Creating a layer steals the active slot, and everything
            # downstream writes to whatever is active.
            if not cls.set_active_uv_layer(uv_layers, source):
                return False, (
                    f"Backup created, but '{name}' could not be restored as the "
                    "active UV layer; aborting before the unwrap writes to the "
                    "wrong layer."
                )

            return True, f"Previous UV layer copied to '{backup_name}'."
        except Exception as exc:
            return False, f"UV backup failed: {exc}"

    @staticmethod
    @contextmanager
    def _edit_mode(obj):
        """Enters Edit Mode on obj, restores the previous mode on exit."""
        previous_mode = bpy.context.mode or 'OBJECT'
        switched = False

        try:
            if previous_mode != 'EDIT_MESH':
                with bpy.context.temp_override(object=obj, active_object=obj):
                    bpy.ops.object.mode_set(mode='EDIT')
                switched = True

            yield
        finally:
            if switched:
                try:
                    with bpy.context.temp_override(object=obj, active_object=obj):
                        bpy.ops.object.mode_set(mode='OBJECT')
                except Exception as exc:
                    # Best-effort restore inside a finally: this must stay broad,
                    # or a failure here would mask the exception being propagated.
                    print(f"[IUV_UV_EXECUTOR] Unable to restore Object Mode: {exc}")

    @staticmethod
    def _select_all(obj):
        try:
            with bpy.context.temp_override(object=obj, active_object=obj):
                bpy.ops.mesh.select_all(action='SELECT')
        except Exception as exc:
            raise RuntimeError(f"Unable to select all faces: {exc}") from exc

    @classmethod
    def execute_unwrap(cls, obj, settings, margin_uv, use_seams=True):
        """
        Creates/activates the target UV layer and unwraps the mesh.

        Returns a dict describing what was executed.
        """
        mesh = getattr(obj, "data", None)
        if not mesh:
            raise RuntimeError("Mesh data is unavailable.")

        uv_name = str(getattr(settings, "uv_layer_name", "SmartUV") or "SmartUV")
        if cls.ensure_uv_layer(mesh, uv_name) is None:
            raise RuntimeError(f"Unable to ensure UV layer '{uv_name}'.")

        island_margin = max(0.0, min(0.5, float(margin_uv)))
        method_used = "unwrap"

        with cls._edit_mode(obj):
            cls._select_all(obj)

            with bpy.context.temp_override(object=obj, active_object=obj):
                if use_seams:
                    try:
                        bpy.ops.uv.unwrap(
                            method='ANGLE_BASED',
                            margin=island_margin,
                        )
                    except TypeError:
                        # A: the margin keyword is not on every unwrap signature.
                        bpy.ops.uv.unwrap()
                    except Exception as exc:
                        raise RuntimeError(f"Unwrap failed: {exc}") from exc
                else:
                    # No seams planned: fall back to Smart UV Project so the
                    # mesh does not end up as one overlapping island.
                    method_used = "smart_project"
                    angle_deg = float(getattr(settings, "curvature_threshold", 60.0))
                    angle_rad = math.radians(max(1.0, min(179.0, angle_deg)))

                    try:
                        bpy.ops.uv.smart_project(
                            angle_limit=angle_rad,
                            island_margin=island_margin,
                            correct_aspect=True,
                            scale_to_bounds=False,
                        )
                    except TypeError:
                        # A: older Smart UV Project signatures reject some keywords.
                        try:
                            bpy.ops.uv.smart_project(angle_limit=angle_rad)
                        except Exception as exc:
                            raise RuntimeError(f"Smart UV Project failed: {exc}") from exc
                    except Exception as exc:
                        raise RuntimeError(f"Smart UV Project failed: {exc}") from exc

        return {
            "uv_layer": uv_name,
            "method": method_used,
            "margin_uv": island_margin,
        }


    @classmethod
    def minimize_stretch(cls, obj, uv_layer_name, iterations=32):
        """
        Relaxes the UVs to reduce angular and area stretch.

        `uv.unwrap` solves for angle preservation and stops. It does not try to
        even out the stretch that remains, which is what leaves a checker
        pattern looking sheared on long or twisted shapes even when the seams
        are placed well. `uv.minimize_stretch` iteratively relaxes the layout
        toward lower distortion while keeping the island boundaries fixed, so
        it improves the interior without changing what was cut.

        Runs before packing: it moves UVs inside each island, so the layout has
        to be re-packed afterwards.

        Returns (success: bool, message: str).
        """
        try:
            iterations = max(1, min(1000, int(iterations)))
        except (TypeError, ValueError):
            iterations = 32

        mesh = getattr(obj, "data", None)
        uv_layers = getattr(mesh, "uv_layers", None)

        if uv_layers is None:
            return False, "No UV layers to relax."

        target = uv_layers.get(uv_layer_name) if uv_layer_name else None
        if target is None:
            return False, f"UV layer '{uv_layer_name}' not found; nothing relaxed."

        if not cls.set_active_uv_layer(uv_layers, target):
            return False, (
                f"UV layer '{uv_layer_name}' could not be made active; "
                "relaxation would have moved a different layer."
            )

        try:
            with cls._edit_mode(obj):
                cls._select_all(obj)

                with uv_editor_override() as has_uv_editor:
                    try:
                        bpy.ops.uv.select_all(action='SELECT')
                    except (RuntimeError, AttributeError, TypeError):
                        # A: the UV selection operator needs a UV editor and is
                        # not always available; relaxation can still proceed.
                        pass

                    try:
                        bpy.ops.uv.minimize_stretch(iterations=iterations)
                    except TypeError:
                        # A: the iterations keyword is not on every signature.
                        bpy.ops.uv.minimize_stretch()
                    except RuntimeError as exc:
                        if not has_uv_editor:
                            return False, (
                                "Minimize Stretch needs an open UV Editor area."
                            )
                        return False, f"Minimize Stretch failed: {exc}"

            return True, f"UV stretch relaxed ({iterations} iterations)."
        except Exception as exc:
            return False, f"Minimize Stretch failed: {exc}"

    @classmethod
    def pack_islands(cls, obj, margin_uv, preserve_scale=False, uv_layer_name=None):
        """
        Packs the UV islands. Returns (success: bool, message: str).

        `uv_layer_name` is not optional in practice: `uv.pack_islands` operates
        on whatever layer is ACTIVE, while everything downstream reads the layer
        by name. Creating the backup layer steals the active slot, so without an
        explicit activation here the packer rearranges the backup and leaves the
        real layer unpacked — which shows up as hundreds of overlapping islands
        while every step still reports success.

        `preserve_scale` maps to the packer's `scale` option, inverted.
        Blender rescales islands to fill the UV square by default, which
        silently undoes texel density normalization: the islands are made
        uniform, then the packer resizes them again to fit. When normalization
        is on, the packer must only translate and rotate.

        `uv.pack_islands` polls for a UV editor, hence the context override.
        """
        island_margin = max(0.0, min(0.5, float(margin_uv)))

        if uv_layer_name:
            mesh = getattr(obj, "data", None)
            uv_layers = getattr(mesh, "uv_layers", None)
            target = uv_layers.get(uv_layer_name) if uv_layers is not None else None

            if target is None:
                return False, f"UV layer '{uv_layer_name}' not found; nothing packed."

            if not cls.set_active_uv_layer(uv_layers, target):
                return False, (
                    f"UV layer '{uv_layer_name}' could not be made active; "
                    "packing would have rearranged a different layer."
                )

        try:
            with cls._edit_mode(obj):
                cls._select_all(obj)

                with uv_editor_override() as has_uv_editor:
                    try:
                        bpy.ops.uv.select_all(action='SELECT')
                    except (RuntimeError, AttributeError, TypeError):
                        # A: the UV selection operator polls for a UV editor and
                        # is not always available; packing can still proceed.
                        pass

                    try:
                        bpy.ops.uv.pack_islands(
                            margin=island_margin,
                            scale=not preserve_scale,
                            # Rotation is what lets long thin islands nest
                            # instead of each claiming a wide empty row. The
                            # default has changed between versions, so it is
                            # set explicitly.
                            rotate=True,
                            # Pack against the island's real outline rather
                            # than its bounding box. A UV shell is almost never
                            # rectangular, so AABB packing reserves the empty
                            # corners of every island and wastes them.
                            shape_method='CONCAVE',
                            # Free rotation beats the axis-aligned and cardinal
                            # modes on organic outlines; on hard surface the
                            # packer settles on an axis anyway.
                            rotate_method='ANY',
                        )
                    except TypeError:
                        # A: the newer keywords are not on every build. Shed
                        # them one tier at a time rather than dropping straight
                        # to a bare call, so a slightly older Blender still
                        # gets rotation and the correct scale behaviour.
                        try:
                            bpy.ops.uv.pack_islands(
                                margin=island_margin,
                                scale=not preserve_scale,
                                rotate=True,
                            )
                        except TypeError:
                            try:
                                bpy.ops.uv.pack_islands(margin=island_margin)
                            except TypeError:
                                bpy.ops.uv.pack_islands()
                    except RuntimeError as exc:
                        if not has_uv_editor:
                            return False, (
                                "Pack Islands needs an open UV Editor area. "
                                "Open a UV Editor and run again to pack the islands."
                            )
                        return False, f"Pack Islands failed: {exc}"

            return True, (
                "UV islands packed (relative sizes preserved)."
                if preserve_scale else "UV islands packed."
            )
        except Exception as exc:
            return False, f"Pack Islands failed: {exc}"

    @classmethod
    def apply_target_coverage(cls, mesh, uv_layer, settings):
        """
        Uniformly scales the whole UV layout to the target coverage.

        Relative island sizes (and therefore texel density) are preserved.
        Returns (success: bool, message: str).
        """
        if not mesh or not uv_layer:
            return False, "Mesh or UV layer unavailable for coverage scaling."

        try:
            target_coverage = float(getattr(settings, "target_coverage", 0.95) or 0.95)
        except (AttributeError, TypeError, ValueError):
            # B: a broken setting should not stop the run, but must be visible.
            print("[IUV_UV_EXECUTOR] Invalid target_coverage setting; using 0.95.")
            target_coverage = 0.95

        target_coverage = max(0.2, min(1.0, target_coverage))

        # Keep the active layer in sync with the one being scaled, so a later
        # operator does not act on a different layer than the one just written.
        try:
            uv_layers = getattr(mesh, "uv_layers", None)
            if uv_layers is not None:
                cls.set_active_uv_layer(uv_layers, uv_layer)
        except (AttributeError, TypeError):
            # A: not every build exposes an assignable active layer.
            pass

        try:
            loop_count = len(mesh.loops)
            if loop_count == 0:
                return False, "The mesh has no loops."

            # Bulk read: one RNA call for the whole layer.
            flat = read_all_uvs(uv_layer, loop_count)

            if flat is not None:
                us = flat[0::2]
                vs = flat[1::2]
                min_u, max_u = float(min(us)), float(max(us))
                min_v, max_v = float(min(vs)), float(max(vs))
            else:
                min_u = min_v = float("inf")
                max_u = max_v = -float("inf")

                for i in range(loop_count):
                    uv = loop_uv(uv_layer, i)
                    if uv is None:
                        continue

                    u, v = uv
                    min_u = min(min_u, u)
                    max_u = max(max_u, u)
                    min_v = min(min_v, v)
                    max_v = max(max_v, v)

            if not (min_u < max_u and min_v < max_v):
                return False, "Degenerate UV bounds: coverage scaling skipped."

            max_dim = max(max_u - min_u, max_v - min_v)
            if max_dim <= 1e-8:
                return False, "Degenerate UV bounds: coverage scaling skipped."

            scale = target_coverage / max_dim

            # Rescale around the layout centre, then recentre on (0.5, 0.5).
            center_u = (min_u + max_u) * 0.5
            center_v = (min_v + max_v) * 0.5

            if flat is not None:
                for i in range(loop_count):
                    flat[i * 2] = 0.5 + (float(flat[i * 2]) - center_u) * scale
                    flat[i * 2 + 1] = 0.5 + (float(flat[i * 2 + 1]) - center_v) * scale

                if not write_all_uvs(uv_layer, flat):
                    return False, "Coverage scaling failed: bulk UV write refused."
            else:
                for i in range(loop_count):
                    uv = loop_uv(uv_layer, i)
                    if uv is None:
                        continue

                    u, v = uv
                    new_u = 0.5 + (u - center_u) * scale
                    new_v = 0.5 + (v - center_v) * scale
                    set_loop_uv(uv_layer, i, new_u, new_v)

            if hasattr(mesh, "update"):
                mesh.update()

            return True, f"UV layout scaled to {target_coverage:.0%} coverage."
        except Exception as exc:
            return False, f"Coverage scaling failed: {exc}"
