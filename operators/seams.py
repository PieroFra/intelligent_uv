# pylint: disable=invalid-name
"""Intelligent UV Mapping — seam-only operator."""

from ..seam_marking import SeamMarker

from .base import IntelligentUVBaseOperator


class IntelligentUV_OT_MarkSeams(IntelligentUVBaseOperator):
    """Computes and marks the seams without unwrapping."""

    bl_idname = "intelligent_uv.mark_seam_candidates"
    bl_label = "Mark Seams Only"
    bl_description = "Computes the seam plan and marks the UV seams, without unwrapping."

    def execute(self, context):
        state = self._run_analysis(context)
        if state is None:
            return {'CANCELLED'}

        obj = state["obj"]
        settings = state["settings"]
        seam_plan = state["seam_plan"]

        success, message = SeamMarker.mark_real_seams(obj.data, seam_plan.is_seam)
        self._report("INFO" if success else "WARNING", message)

        if bool(getattr(settings, "mark_bevel_debug", False)):
            bevel_ok, bevel_msg = SeamMarker.mark_bevel_debug(obj.data, seam_plan.is_seam)
            self._report("INFO" if bevel_ok else "WARNING", bevel_msg)

        return {'FINISHED' if success else 'CANCELLED'}
