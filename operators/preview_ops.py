# pylint: disable=invalid-name
"""Intelligent UV Mapping — preview / apply / discard operators."""

import bpy

from .. import preview
from ..validation import ContextGuard


def _settings(context):
    scene = getattr(context, "scene", None)
    return getattr(scene, "intelligent_uv_settings", None)


def _target_layer(settings):
    return str(getattr(settings, "uv_layer_name", "SmartUV") or "SmartUV")


def _mesh_poll(context):
    obj = ContextGuard.get_context_object(context)
    return bool(obj) and obj.type == 'MESH' and _settings(context) is not None


class IntelligentUV_OT_Preview(bpy.types.Operator):
    """Runs the unwrap, keeping everything it overwrites so it can be undone."""

    bl_idname = "intelligent_uv.preview"
    bl_label = "Preview"
    bl_description = (
        "Unwrap, but record the seams and UVs first so the result can be "
        "discarded exactly. Blender's own undo cannot be relied on here: the "
        "run enters Edit Mode repeatedly and calls operators that push their "
        "own undo steps"
    )
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        obj = ContextGuard.get_context_object(context)
        if not _mesh_poll(context):
            return False
        # One preview at a time: a second capture would overwrite the first
        # backup and strand the original state.
        return not preview.has_pending(obj.data)

    def execute(self, context):
        obj = ContextGuard.get_context_object(context)
        settings = _settings(context)

        if context.mode != 'OBJECT':
            try:
                bpy.ops.object.mode_set(mode='OBJECT')
            except Exception as exc:
                self.report({'ERROR'}, f"Could not switch to Object Mode: {exc}")
                return {'CANCELLED'}

        ok, messages = preview.capture(obj.data, _target_layer(settings))

        if not ok:
            for message in messages:
                self.report({'WARNING'}, message)
            self.report(
                {'ERROR'},
                "Could not record the current state, so the run was not "
                "started. Use Unwrap if you want to proceed without a preview."
            )
            return {'CANCELLED'}

        try:
            bpy.ops.intelligent_uv.run()
        except Exception as exc:
            self.report({'ERROR'}, f"The run failed: {exc}")
            # The mesh may be half written; put it back rather than leaving a
            # preview the user did not get to see.
            preview.revert(obj.data, _target_layer(settings))
            return {'CANCELLED'}

        self.report(
            {'INFO'},
            "Preview ready. Keep it with Apply, or put the mesh back with "
            "Discard."
        )
        return {'FINISHED'}


class IntelligentUV_OT_ApplyPreview(bpy.types.Operator):
    """Keeps the previewed result and drops the recorded state."""

    bl_idname = "intelligent_uv.apply_preview"
    bl_label = "Apply"
    bl_description = "Keep this result and delete the recorded previous state"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        obj = ContextGuard.get_context_object(context)
        return _mesh_poll(context) and preview.has_pending(obj.data)

    def execute(self, context):
        obj = ContextGuard.get_context_object(context)
        settings = _settings(context)

        removed = preview.clear_backups(obj.data, _target_layer(settings))

        self.report(
            {'INFO'},
            "Preview applied."
            + (f" Dropped the recorded {' and '.join(removed)}." if removed else "")
        )
        return {'FINISHED'}


class IntelligentUV_OT_DiscardPreview(bpy.types.Operator):
    """Puts the mesh back exactly as it was before the preview."""

    bl_idname = "intelligent_uv.discard_preview"
    bl_label = "Discard"
    bl_description = (
        "Restore the seams and UVs recorded before the preview, and remove "
        "the UV layer if the preview created it"
    )
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = ContextGuard.get_context_object(context)
        return _mesh_poll(context) and preview.has_pending(obj.data)

    def execute(self, context):
        obj = ContextGuard.get_context_object(context)
        settings = _settings(context)

        if context.mode != 'OBJECT':
            try:
                bpy.ops.object.mode_set(mode='OBJECT')
            except Exception as exc:
                self.report({'ERROR'}, f"Could not switch to Object Mode: {exc}")
                return {'CANCELLED'}

        ok, messages = preview.revert(obj.data, _target_layer(settings))

        for message in messages:
            self.report({'INFO'}, message)

        if not ok:
            self.report({'WARNING'}, "Nothing was restored.")
            return {'CANCELLED'}

        self.report({'INFO'}, "Preview discarded; the mesh is back as it was.")
        return {'FINISHED'}


PREVIEW_CLASSES = (
    IntelligentUV_OT_Preview,
    IntelligentUV_OT_ApplyPreview,
    IntelligentUV_OT_DiscardPreview,
)
