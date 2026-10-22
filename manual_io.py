# pylint: disable=invalid-name
"""
Intelligent UV Mapping — MANUAL FBX ROUND TRIP

Two operators that split the RizomUV bridge into its halves so the external
step can be done by hand:

    Export UV to FBX   plan seams, pre-unwrap, write an FBX
    Import UV from FBX  read an FBX and copy its UVs back by position

Why this exists beside the automated bridge:
when the automated run produces a bad layout there is no way to tell whether
the export, the Lua script, the external engine or the copy-back is at fault.
Doing the middle step by hand isolates it — if the manual round trip is clean,
the problem is in the automation; if it is not, the problem is upstream.

It is also a usable workflow in its own right: RizomUV and Marmoset both reward
hand tuning, and this keeps that possible without giving up the seam planning.

Both operators reuse RizomUVBridge.export_object_fbx and
RizomUVBridge.import_uvs_from_fbx, so the file written here is byte-identical
to the one the bridge writes, and the UVs come back through the same spatially
matched copy-back.
"""

import os
import subprocess

import bpy

from .rizomuv_bridge import RizomUVBridge
from .uv_executor import MinimalUVExecutor
from .validation import ContextGuard


def open_in_rizomuv(settings, filepath):
    """
    Opens RizomUV on a file and returns immediately.

    Deliberately the simplest thing that works: the executable is handed the
    path and nothing else. No Lua script, no `-cfi` remote file, no socket, no
    polling, no modal operator. Those exist to make the round trip automatic,
    and every one of them is a way for the run to hang or die.

    The process is left completely alone. Blender does not wait for it, does
    not read its output and does not care when it exits, so RizomUV crashing or
    being closed cannot affect the add-on. The user saves over the file and
    presses Import when ready.

    Returns (launched: bool, message: str).
    """
    rz_path = str(getattr(settings, "rizomuv_path", "") or "").strip()

    if not rz_path:
        return False, "No RizomUV path set; the FBX was written but not opened."

    if not os.path.isfile(rz_path):
        return False, (
            f"RizomUV not found at {rz_path}; the FBX was written but not opened."
        )

    try:
        subprocess.Popen([rz_path, filepath], close_fds=True)
    except Exception as exc:
        return False, f"Could not launch RizomUV: {exc}"

    return True, f"RizomUV opened with {os.path.basename(filepath)}."


def last_import_candidate(settings):
    """
    The file a one-click import should read.

    An external editor is normally pointed at the exported file and told to
    save over it, or beside it. Both conventions are checked so the common case
    needs no file dialog at all:

        <name>.fbx          saved in place
        <name>_import.fbx   saved alongside, matching the bridge's own naming

    Returns a path that exists, or "".
    """
    exported = str(getattr(settings, "last_export_path", "") or "")
    if not exported:
        return ""

    root, ext = os.path.splitext(exported)
    ext = ext or ".fbx"

    # Newest first: if the editor wrote a separate file, that is the result;
    # if it saved in place, the original is.
    candidates = [f"{root}_import{ext}", exported]
    existing = [p for p in candidates if os.path.isfile(p)]

    if not existing:
        return ""

    return max(existing, key=lambda p: os.path.getmtime(p))


def _mesh_poll(context):
    obj = ContextGuard.get_context_object(context)
    scene = getattr(context, "scene", None)
    return (
        bool(obj)
        and obj.type == 'MESH'
        and bool(scene)
        and hasattr(scene, "intelligent_uv_settings")
    )


class IntelligentUV_OT_ExportFBX(bpy.types.Operator):
    """Plans seams, unwraps natively and writes an FBX for an external editor."""

    bl_idname = "intelligent_uv.export_fbx"
    bl_label = "Export UV to FBX"
    bl_description = (
        "Plan the seams, run the native unwrap, and export the object to FBX "
        "so it can be edited in RizomUV or another external tool"
    )
    bl_options = {'REGISTER', 'UNDO'}

    filepath: bpy.props.StringProperty(subtype='FILE_PATH')
    filename_ext = ".fbx"

    filter_glob: bpy.props.StringProperty(default="*.fbx", options={'HIDDEN'})

    open_in_editor: bpy.props.BoolProperty(
        name="Open in RizomUV",
        description=(
            "Launch RizomUV with the exported file after writing it. RizomUV "
            "opens normally and you work in it by hand; nothing is scripted "
            "and nothing is polled. Save over the file when done, then press "
            "Import"
        ),
        default=True,
    )

    plan_seams: bpy.props.BoolProperty(
        name="Plan Seams First",
        description=(
            "Run the seam planner and the native unwrap before exporting. "
            "Disable to export the object exactly as it is now"
        ),
        default=True,
    )

    @classmethod
    def poll(cls, context):
        return _mesh_poll(context)

    def invoke(self, context, event):
        obj = ContextGuard.get_context_object(context)

        if not self.filepath:
            safe = "".join(
                c for c in obj.name if c.isalnum() or c in ("_", "-")
            ) or "object"
            self.filepath = f"{safe}_uv.fbx"

        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        obj = ContextGuard.get_context_object(context)
        settings = context.scene.intelligent_uv_settings

        filepath = bpy.path.ensure_ext(self.filepath, ".fbx")

        if context.mode != 'OBJECT':
            try:
                bpy.ops.object.mode_set(mode='OBJECT')
            except Exception as exc:
                self.report({'ERROR'}, f"Unable to switch to Object Mode: {exc}")
                return {'CANCELLED'}

        # Seam planning is optional: the point of a manual round trip is
        # sometimes to send out the mesh exactly as the user left it.
        if self.plan_seams:
            try:
                bpy.ops.intelligent_uv.run()
            except Exception as exc:
                self.report({'WARNING'}, f"Seam planning skipped: {exc}")

        try:
            RizomUVBridge.export_object_fbx(obj, filepath)
        except Exception as exc:
            self.report({'ERROR'}, f"Export failed: {exc}")
            return {'CANCELLED'}

        # Remember where it went, so Import can offer the same file back.
        try:
            settings.last_export_path = filepath
        except (AttributeError, TypeError):
            # A: the property may be missing on an older settings version.
            pass

        launched = False
        if self.open_in_editor:
            launched, message = open_in_rizomuv(settings, filepath)
            self.report({'INFO'} if launched else {'WARNING'}, message)

        self.report(
            {'INFO'},
            f"Exported '{obj.name}' to {os.path.basename(filepath)}. "
            + (
                "Work on it in RizomUV, save over the same file, then press "
                "Import."
                if launched else
                "Edit it externally, save it, then press Import."
            )
        )
        return {'FINISHED'}


class IntelligentUV_OT_ImportFBX(bpy.types.Operator):
    """Reads an FBX and copies its UVs onto the active object."""

    bl_idname = "intelligent_uv.import_fbx"
    bl_label = "Import UV from FBX"
    bl_description = (
        "Copy the UVs of an externally edited FBX back onto the active object, "
        "matching faces by position rather than by index"
    )
    bl_options = {'REGISTER', 'UNDO'}

    filepath: bpy.props.StringProperty(subtype='FILE_PATH')
    filename_ext = ".fbx"

    filter_glob: bpy.props.StringProperty(default="*.fbx", options={'HIDDEN'})

    @classmethod
    def poll(cls, context):
        return _mesh_poll(context)

    def invoke(self, context, event):
        settings = context.scene.intelligent_uv_settings

        if not self.filepath:
            self.filepath = str(getattr(settings, "last_export_path", "") or "")

        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        obj = ContextGuard.get_context_object(context)
        settings = context.scene.intelligent_uv_settings

        if not self.filepath or not os.path.isfile(self.filepath):
            self.report({'ERROR'}, "Select an existing FBX file.")
            return {'CANCELLED'}

        if context.mode != 'OBJECT':
            try:
                bpy.ops.object.mode_set(mode='OBJECT')
            except Exception as exc:
                self.report({'ERROR'}, f"Unable to switch to Object Mode: {exc}")
                return {'CANCELLED'}

        if bool(getattr(settings, "backup_uv_layer", True)):
            backed_up, message = MinimalUVExecutor.backup_uv_layer(
                obj.data,
                str(getattr(settings, "uv_layer_name", "SmartUV") or "SmartUV"),
            )
            if backed_up:
                self.report({'INFO'}, message)

        try:
            uv_name, copied, unmatched, total, fit_info = \
                RizomUVBridge.import_uvs_from_fbx(obj, settings, self.filepath)
        except Exception as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}

        matched = total - unmatched
        level = {'WARNING'} if unmatched else {'INFO'}

        self.report(
            level,
            f"UVs imported onto '{obj.name}' — layer '{uv_name}', "
            f"{matched}/{total} faces matched, {copied} loops written"
            + (f", {unmatched} faces kept their previous UVs." if unmatched else ".")
        )

        return {'FINISHED'}


class IntelligentUV_OT_ImportLast(bpy.types.Operator):
    """Imports the UVs from the file the last export produced, without a dialog."""

    bl_idname = "intelligent_uv.import_last"
    bl_label = "Import Last"
    bl_description = (
        "Copy the UVs back from the file written by the last export. No file "
        "dialog: the path is remembered"
    )
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        if not _mesh_poll(context):
            return False

        return bool(last_import_candidate(context.scene.intelligent_uv_settings))

    def execute(self, context):
        obj = ContextGuard.get_context_object(context)
        settings = context.scene.intelligent_uv_settings

        path = last_import_candidate(settings)
        if not path:
            self.report(
                {'ERROR'},
                "No previous export found. Use Export FBX first, or Import FBX "
                "to pick a file."
            )
            return {'CANCELLED'}

        if context.mode != 'OBJECT':
            try:
                bpy.ops.object.mode_set(mode='OBJECT')
            except Exception as exc:
                self.report({'ERROR'}, f"Unable to switch to Object Mode: {exc}")
                return {'CANCELLED'}

        if bool(getattr(settings, "backup_uv_layer", True)):
            backed_up, message = MinimalUVExecutor.backup_uv_layer(
                obj.data,
                str(getattr(settings, "uv_layer_name", "SmartUV") or "SmartUV"),
            )
            if backed_up:
                self.report({'INFO'}, message)

        try:
            uv_name, copied, unmatched, total, fit_info = \
                RizomUVBridge.import_uvs_from_fbx(obj, settings, path)
        except Exception as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}

        matched = total - unmatched
        self.report(
            {'WARNING'} if unmatched else {'INFO'},
            f"UVs imported from {os.path.basename(path)} onto '{obj.name}' — "
            f"layer '{uv_name}', {matched}/{total} faces matched, "
            f"{copied} loops written."
        )
        return {'FINISHED'}


MANUAL_IO_CLASSES = (
    IntelligentUV_OT_ExportFBX,
    IntelligentUV_OT_ImportFBX,
    IntelligentUV_OT_ImportLast,
)
