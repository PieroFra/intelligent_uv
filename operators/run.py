# pylint: disable=invalid-name
"""Intelligent UV Mapping — main Run operator."""


import bpy

from ..seam_marking import SeamMarker
from ..uv_executor import MinimalUVExecutor
from ..validation import ContextGuard

from .base import IntelligentUVBaseOperator
from .batch import BatchQueueMixin
from .external import ExternalEngineMixin
from .native import NativePipelineMixin


class IntelligentUV_OT_ResetState(bpy.types.Operator):
    """Clears a stuck busy flag so Run becomes available again."""

    bl_idname = "intelligent_uv.reset_state"
    bl_label = "Reset Run State"
    bl_description = (
        "Unlock the Run button. Only needed if a previous run crashed and left "
        "the operator marked as busy"
    )
    bl_options = {'REGISTER'}

    def execute(self, context):
        was_busy = IntelligentUV_OT_Run._busy
        IntelligentUV_OT_Run._busy = False

        try:
            context.window_manager.progress_end()
        except Exception:
            # A: the progress bar is decoration. Blender has no progress
            # context in every situation the operator can run from, and a
            # missing one must never stop the work.
            pass

        self.report(
            {'INFO'},
            "Run unlocked." if was_busy else "Run was not locked."
        )
        return {'FINISHED'}


class IntelligentUV_OT_Run(
    BatchQueueMixin,
    ExternalEngineMixin,
    NativePipelineMixin,
    IntelligentUVBaseOperator,
):
    """Runs the full intelligent UV mapping workflow."""

    bl_idname = "intelligent_uv.run"
    bl_label = "Run Intelligent UV"
    bl_description = "Analysis, seam planning, unwrap, texel density and packing."

    # Modal state for the external engine
    _timer = None
    _bridge_ctx = None
    _state = None
    _elapsed = 0.0
    _timeout = 300.0

    POLL_INTERVAL = 0.25

    # Set for the WHOLE batch, so a second Run cannot start while a queue is
    # still being processed.
    _busy = False

    # Batch state
    _queue = None
    _queue_index = 0
    _queue_total = 0
    _ok_names = None
    _failed_names = None
    _failed_reasons = None

    @classmethod
    def poll(cls, context):
        if cls._busy:
            return False

        obj = ContextGuard.get_context_object(context)
        return bool(obj) and obj.type == 'MESH'

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    def execute(self, context):
        wm = context.window_manager

        try:
            wm.progress_begin(0, 100)
            wm.progress_update(0)
        except Exception:
            # A: the progress bar is decoration. Blender has no progress
            # context in every situation the operator can run from, and a
            # missing one must never stop the work.
            pass

        queue = self._build_queue(context)
        if queue is None:
            self._end_progress(context)
            return {'CANCELLED'}

        self._init_batch(queue, context)

        # An exception escaping here would leave _busy set and grey out the Run
        # button until Blender restarts, so the flag is released on any failure
        # that is not a normal completion.
        try:
            status = self._drain_queue(context)
        except Exception as exc:
            self._release_busy(context)
            self._report("ERROR", f"Run failed: {exc}")
            raise

        if status != {'RUNNING_MODAL'}:
            IntelligentUV_OT_Run._busy = False

        return status

    # ------------------------------------------------------------------
    # Queue
    # ------------------------------------------------------------------

    def _prepare_write(self, context, state):
        """
        Backup, dry-run gate and seam marking.

        Returns False when this was a dry run and nothing must be written.
        A bool is used deliberately: the previous version returned the state
        dict in the dry-run branch, which the caller read as "keep going" and
        happily wrote UVs anyway.
        """
        obj = state["obj"]
        settings = state["settings"]
        seam_plan = state["seam_plan"]
        margin = state["margin_result"]

        if bool(getattr(settings, "dry_run", False)):
            self._report(
                "INFO",
                f"Dry run — {obj.name}: "
                f"curvature {seam_plan.effective_curvature_threshold:.1f} degrees, "
                f"{len(seam_plan.seam_edges)} seams, {seam_plan.region_count} islands, "
                f"margin {margin.margin_px}px @ {margin.texture_resolution}. "
                "Nothing was written."
            )
            return False

        if bool(getattr(settings, "backup_uv_layer", True)):
            backed_up, backup_msg = MinimalUVExecutor.backup_uv_layer(
                obj.data,
                str(getattr(settings, "uv_layer_name", "SmartUV") or "SmartUV"),
            )
            # A failed backup is not fatal, but it must be visible: it means
            # the active layer may be wrong for everything that follows.
            self._report("INFO" if backed_up else "WARNING", backup_msg)

        success, message = SeamMarker.mark_real_seams(obj.data, seam_plan.is_seam)
        self._report("INFO" if success else "WARNING", message)

        if bool(getattr(settings, "mark_bevel_debug", False)):
            bevel_ok, bevel_msg = SeamMarker.mark_bevel_debug(
                obj.data, seam_plan.is_seam
            )
            self._report("INFO" if bevel_ok else "WARNING", bevel_msg)

        self._update_progress(55)
        return True

    # ------------------------------------------------------------------
    # External engine start
    # ------------------------------------------------------------------
