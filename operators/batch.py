# pylint: disable=invalid-name
"""
Intelligent UV Mapping — BATCH QUEUE

The queue half of the Run operator, kept apart from the unwrapping itself.

Processing several objects is not a loop around a single-object run. The
external engine path is modal: it starts a process, returns control to Blender
and is called back on a timer, so the "next object" cannot be the next
iteration of a for loop — there is no loop to be in by then. The queue is
therefore explicit state that both the synchronous and the modal path advance,
which is why it reads as more machinery than the job seems to need.
"""


import bpy

from ..validation import ContextGuard


class BatchQueueMixin:
    """Queue state and its bookkeeping. Mixed into the Run operator."""

    def _drain_queue(self, context, already_modal=False):
        """
        Processes queue items until one starts an external process or the
        queue runs out.

        This loop is what makes the native path handle more than one object:
        _process_current() only ever handles a single item.
        """
        while not self._queue_is_finished():
            status = self._process_current(context, already_modal=already_modal)
            if status is not None:
                return status

        return self._finish_batch(context, aborted=False)

    def _build_queue(self, context):
        """Mesh objects to process, or None when there is nothing valid."""
        settings = context.scene.intelligent_uv_settings
        process_selected = bool(getattr(settings, "process_selected", False))

        if process_selected:
            selected = list(getattr(context, "selected_objects", ()) or ())
            queue = [o for o in selected if o is not None and o.type == 'MESH']
        else:
            active = ContextGuard.get_context_object(context)
            queue = [active] if (active and active.type == 'MESH') else []

        if not queue:
            self._report(
                "ERROR",
                "No selected mesh objects found. Select at least one mesh object, "
                "or disable Process Selected."
                if process_selected else
                "No active mesh object found. Select a mesh object first."
            )
            return None

        unique = []
        seen = set()
        for obj in queue:
            if obj.name not in seen:
                seen.add(obj.name)
                unique.append(obj)

        return unique

    def _init_batch(self, queue):
        self._queue = queue
        self._queue_index = 0
        self._queue_total = len(queue)
        self._ok_names = []
        self._failed_names = []
        self._failed_reasons = []

        type(self)._busy = True

        if self._queue_total > 1:
            names = ", ".join(o.name for o in queue[:8])
            more = "" if len(queue) <= 8 else f", +{len(queue) - 8} more"
            self._report(
                "INFO",
                f"Batch started for {self._queue_total} objects: {names}{more}."
            )

    def _queue_is_finished(self):
        return self._queue_index >= self._queue_total

    def _current_object(self):
        if self._queue_is_finished() or not self._queue:
            return None
        return self._queue[self._queue_index]

    def _mark_ok(self, name):
        if name and name not in self._ok_names and name not in self._failed_names:
            self._ok_names.append(name)

    def _mark_failed(self, name, reason):
        # Remove from the success list: an object counted twice makes the final
        # summary lie about how many actually completed.
        if name in self._ok_names:
            self._ok_names.remove(name)
        if name not in self._failed_names:
            self._failed_names.append(name)
        self._failed_reasons.append(f"{name}: {reason}")

    def _advance_queue(self):
        self._queue_index += 1
        self._update_progress(0 if not self._queue_is_finished() else 100)

    def _update_progress(self, percent):
        """Maps per-object progress onto the whole batch."""
        if self._queue_total <= 0:
            return

        base = 100.0 * self._queue_index / self._queue_total
        span = 100.0 / self._queue_total
        overall = base + span * (max(0.0, min(100.0, float(percent))) / 100.0)

        try:
            bpy.context.window_manager.progress_update(
                int(round(max(0.0, min(100.0, overall))))
            )
        except Exception:
            # A: the progress bar is decoration. Blender has no progress
            # context in every situation the operator can run from, and a
            # missing one must never stop the work.
            pass

    def _batch_summary(self, aborted):
        ok = len(self._ok_names or [])
        failed = len(self._failed_names or [])
        remaining = max(0, self._queue_total - self._queue_index)

        if aborted:
            text = f"Batch aborted — {ok} completed, {failed} failed, {remaining} not started."
        else:
            text = f"Batch finished — {ok} completed, {failed} failed."

        if failed:
            names = ", ".join(self._failed_names[:10])
            more = "" if failed <= 10 else f", +{failed - 10} more"
            text += f" Failed: {names}{more}."

        return text

    def _finish_batch(self, context, aborted=False):
        """Releases all batch state and reports the summary."""
        type(self)._busy = False
        self._release_timer(context)

        self._cleanup_bridge(failed=True)

        self._state = None
        self._end_progress(context)

        summary = self._batch_summary(aborted)
        self._report(
            "WARNING" if (aborted or self._failed_names) else "INFO", summary
        )

        # FINISHED even on abort: CANCELLED would make Blender discard the UVs
        # and seams already written to the objects that did complete.
        return {'FINISHED'}

    def _abort_batch(self, context, reason):
        self._report("WARNING", reason)
        return self._finish_batch(context, aborted=True)

    # ------------------------------------------------------------------
    # Single object
    # ------------------------------------------------------------------

    def _process_current(self, context, already_modal=False):
        """
        Handles one queue item.

        Returns a modal status when an external process was started, or None
        when the object finished synchronously and the queue can advance.
        """
        obj = self._current_object()

        # obj.name raises ReferenceError when the object was deleted after the
        # queue was built (e.g. while a previous object was being processed).
        try:
            name = obj.name if obj is not None else "unknown"
            exists = obj is not None and name in bpy.data.objects
        except ReferenceError:
            name, exists = "deleted", False

        self._update_progress(0)

        if not exists:
            self._mark_failed(name, "object no longer exists")
            self._advance_queue()
            return None

        if obj.type != 'MESH':
            self._mark_failed(name, "not a mesh object")
            self._advance_queue()
            return None

        # The shared pipeline in base.py resolves the object through
        # ContextGuard, which reads the active object, so the queued object has
        # to become active first.
        try:
            context.view_layer.objects.active = obj
        except Exception as exc:
            self._mark_failed(name, f"could not be made active: {exc}")
            self._advance_queue()
            return None

        state = self._run_analysis(context)
        if state is None:
            self._mark_failed(name, "analysis failed")
            self._advance_queue()
            return None

        self._update_progress(40)

        if not self._prepare_write(context, state):
            # Dry run: nothing was written, and nothing should be.
            self._mark_ok(name)
            self._advance_queue()
            return None

        status = self._start_external(context, state, already_modal=already_modal)
        if status is not None:
            return status

        if self._run_native(context, state):
            self._mark_ok(name)
        self._advance_queue()
        return None

    # ------------------------------------------------------------------
    # Write preparation
    # ------------------------------------------------------------------
