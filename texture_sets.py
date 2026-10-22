# pylint: disable=invalid-name
"""
Intelligent UV Mapping — TEXTURE SETS

Packs each material into its own full UV square instead of sharing one.

A game asset with three materials gets three textures, and each of those
textures is addressed by the same 0-1 coordinates. Packing every island into a
single square therefore wastes two thirds of every texture: the metal parts
occupy a corner of the metal texture and nothing else uses the rest, while the
same corner of the fabric texture sits empty.

Packing per material fixes that. The sets overlap in UV space, which looks
alarming in the UV editor and is exactly right — two faces at the same
coordinate read from different images, so they never collide. The overlap check
knows about this and stops reporting sets against each other.

Blender's packer already accepts a selection, so each set is packed by selecting
that material's faces and packing what is selected. That keeps the C packer
doing the work rather than reimplementing placement per group.
"""

import bpy

from .uv_executor import MinimalUVExecutor


class TextureSetResult:
    """How many material sets were found, packed and skipped."""
    def __init__(self):
        self.sets = 0
        self.packed = 0
        self.skipped = 0
        self.messages = []


def material_slot_count(obj):
    """Number of material slots on the object, zero when it has none."""
    slots = getattr(obj, "material_slots", None)
    return len(slots) if slots is not None else 0


def pack_per_material(obj, margin_uv, uv_layer_name, preserve_scale=True,
                      report=None):
    """
    Packs each material's faces into the UV square on their own.

    Returns a TextureSetResult. A material with no faces is skipped rather
    than counted as a failure: empty slots are common and mean nothing.
    """
    result = TextureSetResult()

    slots = material_slot_count(obj)
    if slots < 2:
        result.messages.append(
            "Texture sets need at least two materials; packed as one set."
        )
        return result

    mesh = getattr(obj, "data", None)
    uv_layers = getattr(mesh, "uv_layers", None)
    target = uv_layers.get(uv_layer_name) if uv_layers is not None else None

    if target is None:
        result.messages.append(
            f"UV layer '{uv_layer_name}' not found; nothing packed per material."
        )
        return result

    if not MinimalUVExecutor.set_active_uv_layer(uv_layers, target):
        result.messages.append(
            f"Could not activate '{uv_layer_name}'; packing would have "
            "rearranged another layer."
        )
        return result

    island_margin = max(0.0, min(0.5, float(margin_uv)))

    def say(level, message):
        result.messages.append(message)
        if report:
            report(level, message)

    original_index = getattr(obj, "active_material_index", 0)

    try:
        with MinimalUVExecutor._edit_mode(obj):
            for index in range(slots):
                try:
                    obj.active_material_index = index
                except Exception as exc:
                    say("WARNING", f"Material slot {index} unavailable: {exc}")
                    continue

                material = obj.material_slots[index].material
                name = getattr(material, "name", f"slot {index}")

                try:
                    with bpy.context.temp_override(object=obj, active_object=obj):
                        bpy.ops.mesh.select_all(action='DESELECT')
                        bpy.ops.object.material_slot_select()
                except Exception as exc:
                    say("WARNING", f"Could not select '{name}': {exc}")
                    continue

                result.sets += 1

                # An empty slot selects nothing, and packing nothing would
                # report a success that never happened.
                selected = sum(
                    1 for poly in mesh.polygons
                    if getattr(poly, "select", False)
                )
                if selected == 0:
                    result.skipped += 1
                    continue

                from .utils import uv_editor_override

                with uv_editor_override() as has_uv_editor:
                    try:
                        bpy.ops.uv.select_all(action='SELECT')
                    except (RuntimeError, AttributeError, TypeError):
                        # A: UV selection needs a UV editor and is not always
                        # available; the mesh selection still constrains it.
                        pass

                    try:
                        bpy.ops.uv.pack_islands(
                            margin=island_margin,
                            scale=not preserve_scale,
                            rotate=True,
                            shape_method='CONCAVE',
                            rotate_method='ANY',
                        )
                    except TypeError:
                        # A: shed the newer keywords one tier at a time.
                        try:
                            bpy.ops.uv.pack_islands(
                                margin=island_margin,
                                scale=not preserve_scale,
                                rotate=True,
                            )
                        except TypeError:
                            bpy.ops.uv.pack_islands(margin=island_margin)
                    except RuntimeError as exc:
                        if not has_uv_editor:
                            say(
                                "WARNING",
                                "Texture set packing needs an open UV Editor "
                                "area.",
                            )
                            break
                        say("WARNING", f"Packing '{name}' failed: {exc}")
                        continue

                result.packed += 1
                say("INFO", f"Texture set '{name}': {selected} faces packed.")
    except Exception as exc:
        say("WARNING", f"Texture set packing failed: {exc}")
    finally:
        try:
            obj.active_material_index = original_index
        except Exception:
            # A: restoring the slot is cosmetic; never mask the real error.
            pass

    if result.packed:
        say(
            "INFO",
            f"Packed {result.packed} texture sets into their own UV square. "
            "Sets overlap each other on purpose: they read from different "
            "images."
            + (
                f" {result.skipped} material slots had no faces."
                if result.skipped else ""
            )
        )

    return result


def island_material_groups(island_analysis, material_analysis):
    """
    Island id -> material group, so the overlap check can ignore pairs that
    belong to different sets.

    Two islands at the same coordinates are only a problem when the same image
    is sampled at that coordinate. Across texture sets they are not.
    """
    groups = {}
    islands = getattr(island_analysis, "islands", None) or []
    face_group = getattr(material_analysis, "face_material_group", None) or {}

    for record in islands:
        faces = record.get("faces", ())
        tally = {}
        for fidx in faces:
            group = face_group.get(fidx)
            if group is not None:
                tally[group] = tally.get(group, 0) + 1

        if tally:
            groups[record.get("id")] = max(tally, key=tally.get)

    return groups
