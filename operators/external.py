# pylint: disable=invalid-name
"""
Intelligent UV Mapping — EXTERNAL ENGINE DRIVING

The modal half of the Run operator: starting RizomUV, polling it without
freezing Blender, and handing control back to the queue when it finishes.

Everything here exists because an external process cannot be waited on. A
blocking wait would lock the interface for as long as the engine runs, so the
work is split across timer ticks, and the price is that the operator's state
has to survive between callbacks rather than living on the stack.
"""

import bpy

import os

from ..rizomuv_bridge import RizomUVBridge
from ..rizomuv_link import (
    RizomUVLinkBridge,
    ensure_link_on_path,
    is_available as link_available,
    unavailable_reason as link_unavailable_reason,
)


class ExternalEngineMixin:
    """Launching, polling and tearing down the external engine."""

    def _start_external(self, context, state, already_modal=False):
        """
        Starts the RizomUV bridge if requested and available.

        `already_modal` is set when chaining to the next queue item from inside
        modal(): the handler is registered once for the whole batch, and adding
        it again would deliver every event twice.
        """
        obj = state["obj"]
        settings = state["settings"]
        seam_plan = state["seam_plan"]

        use_riz = bool(getattr(settings, "use_rizomuv", False))
        rz_path = str(getattr(settings, "rizomuv_path", "") or "").strip()
        use_riz_effective = use_riz and os.path.isfile(rz_path)

        if use_riz and not use_riz_effective:
            self._report(
                "WARNING",
                f"RizomUV not found at {rz_path}: falling back to the native engine."
            )

        if not use_riz_effective:
            return None

        # Heavy-mesh early warning: RizomUV 64-bit copes with a lot, but
        # unfold + pack on millions of faces is where it runs out of memory
        # or stops answering — say so up front instead of after the timeout.
        try:
            face_count = len(obj.data.polygons)
        except Exception:
            face_count = 0
        if face_count > 1_000_000:
            self._report(
                "WARNING",
                f"{obj.name} has {face_count:,} faces: RizomUV may take a "
                "long time or run out of memory. Consider a decimated copy."
            )

        # Engine choice. The live link is preferred where it exists: it drives
        # RizomUV through its documented API instead of a Lua script whose
        # syntax cannot be verified, and `-cfi` never terminates on its own.
        # The API ships inside the RizomUV install dir, not on sys.path.
        ensure_link_on_path(rz_path)
        mode = str(getattr(settings, "rizomuv_engine_mode", "AUTO") or "AUTO")
        use_link = (mode == 'LINK') or (mode == 'AUTO' and link_available())

        if mode == 'LINK' and not link_available():
            self._report("WARNING", link_unavailable_reason())
            self._report("WARNING", "Falling back to the Lua script engine.")
            use_link = False

        try:
            if use_link:
                self._bridge_ctx = RizomUVLinkBridge.prepare(
                    obj, settings, state["seam_plan"].is_seam,
                    state["margin_result"], report=self._report,
                )
                RizomUVLinkBridge.start(self._bridge_ctx, settings)
            else:
                self._bridge_ctx = RizomUVBridge.prepare(
                    obj, settings, state["seam_plan"].is_seam,
                    state["margin_result"], report=self._report,
                )
                RizomUVBridge.launch(self._bridge_ctx)
        except Exception as exc:
            self._report("WARNING", str(exc))
            self._report(
                "WARNING",
                "RizomUV could not be started: keeping the native result."
            )
            if self._bridge_ctx is not None:
                self._cleanup_bridge(failed=True)
            return None

        try:
            self._timeout = float(max(10, int(
                getattr(settings, "rizomuv_timeout", 300) or 300
            )))
        except Exception:
            self._timeout = 300.0

        self._state = state
        self._elapsed = 0.0
        type(self)._busy = True

        wm = context.window_manager
        self._timer = wm.event_timer_add(self.POLL_INTERVAL, window=context.window)
        if not already_modal:
            wm.modal_handler_add(self)

        engine = "live link" if use_link else "Lua script"
        version = self._bridge_ctx.get("version", "")
        detail = f" (RizomUV {version})" if version and version != "unknown" else ""
        self._report(
            "INFO",
            f"RizomUV {engine}{detail} running for {obj.name}. Blender stays "
            "responsive; press ESC to abort the batch and keep the current result."
        )

        return {'RUNNING_MODAL'}

    # ------------------------------------------------------------------
    # Modal polling
    # ------------------------------------------------------------------

    def modal(self, context, event):
        try:
            return self._modal_impl(context, event)
        except Exception as exc:
            # Same reasoning as execute(): a crash inside the polling loop must
            # not leave the operator permanently locked.
            self._release_busy(context)
            self._report("ERROR", f"Run failed while polling: {exc}")
            # FINISHED, not CANCELLED: with UNDO enabled, CANCELLED makes
            # Blender discard the seams and UVs already written to the objects
            # that completed before the failure.
            return {'FINISHED'}

    def _cleanup_bridge(self, failed=False):
        """Cleans up whichever bridge is active, then clears it."""
        ctx = self._bridge_ctx
        if ctx is None:
            return

        try:
            if ctx.get("mode") == "link":
                RizomUVLinkBridge.cleanup(ctx, failed=failed)
            else:
                RizomUVBridge.cleanup(ctx, failed=failed)
        except Exception as exc:
            print(f"[IUV] Bridge cleanup failed: {exc}")

        self._bridge_ctx = None

    def _release_busy(self, context):
        """Unlocks the operator and tears down any modal state."""
        type(self)._busy = False
        try:
            self._release_timer(context)
        except Exception:
            # Runs while tearing down after a failure. Anything raised here
            # would replace the error being reported with a less useful one.
            pass
        try:
            self._cleanup_bridge(failed=True)
        except Exception:
            # Runs while tearing down after a failure. Anything raised here
            # would replace the error being reported with a less useful one.
            pass
        self._state = None
        self._end_progress(context)

    def _modal_impl(self, context, event):
        if event.type in {'ESC'}:
            ctx = self._bridge_ctx
            if ctx is not None:
                if ctx.get("mode") == "link":
                    # Force: a graceful Quit would block on a busy app.
                    RizomUVLinkBridge.terminate(ctx, force=True)
                else:
                    RizomUVBridge.terminate(ctx)
            if self._state is not None:
                self._mark_failed(self._state["obj"].name, "aborted by user")
            return self._abort_batch(
                context,
                "Batch stopped by user. Remaining objects were not started."
            )

        if event.type != 'TIMER':
            return {'PASS_THROUGH'}

        ctx = self._bridge_ctx
        if ctx is None:
            self._report("WARNING", "The RizomUV bridge is unavailable.")
            return self._finish_external(context, success=False)

        self._elapsed += self.POLL_INTERVAL

        if self._elapsed >= self._timeout:
            self._report(
                "WARNING",
                f"RizomUV exceeded the timeout ({int(self._timeout)}s) and was "
                "stopped. Keeping the native result for this object."
            )
            if ctx.get("mode") == "link":
                RizomUVLinkBridge.terminate(ctx, force=True)
            else:
                RizomUVBridge.terminate(ctx)
            return self._finish_external(context, success=False)

        # --- Live link: commands run on a worker thread, so a long unfold
        # --- or pack never blocks the UI, and a crashed RizomUV is caught
        # --- by the process watch instead of freezing Blender on a socket
        # --- that will never answer.
        if ctx.get("mode") == "link":
            try:
                if ctx.get("job") is not None:
                    status, label, exc = RizomUVLinkBridge.step_poll(ctx)
                    if status == "error":
                        raise exc
                    if status == "running":
                        self._update_progress(
                            55 + 30 * RizomUVLinkBridge.progress_fraction(ctx)
                        )
                        return {'RUNNING_MODAL'}

                # No command running: chain the next one in the same tick.
                label = RizomUVLinkBridge.step_begin(ctx)
                if label is not None:
                    self._report("INFO", f"RizomUV: {label}…")
                    self._update_progress(
                        55 + 30 * RizomUVLinkBridge.progress_fraction(ctx)
                    )
                    return {'RUNNING_MODAL'}
            except Exception as exc:
                self._report("WARNING", str(exc))
                self._report(
                    "WARNING",
                    "RizomUV failed: keeping the native unwrap result for this "
                    "object. Seams and UVs have been preserved."
                )
                return self._finish_external(context, success=False)

            try:
                execution_info = RizomUVLinkBridge.finalize(
                    self._state["obj"], self._state["settings"], ctx
                )
            except Exception as exc:
                self._report("WARNING", str(exc))
                self._report(
                    "WARNING",
                    "RizomUV finished but the result could not be read back: "
                    "keeping the native unwrap."
                )
                return self._finish_external(context, success=False)

            matched = execution_info.get("total_faces", 0) - execution_info.get(
                "unmatched_faces", 0
            )
            if execution_info.get("unfold_failed_islands"):
                self._report(
                    "WARNING",
                    f"RizomUV could not unfold "
                    f"{execution_info['unfold_failed_islands']} islands "
                    "(non-manifold or degenerate geometry): they kept the "
                    "pre-computed UVs. Clean the mesh (Merge by Distance, "
                    "Non Manifold select) for a full unfold."
                )
            if execution_info.get("fit_to_tile"):
                self._report(
                    "INFO",
                    "The layout exceeded the 0-1 tile and was uniformly "
                    "rescaled to fit (island proportions preserved)."
                )
            closing = (
                "RizomUV left open for inspection."
                if ctx.get("keep_open")
                else "RizomUV was closed automatically."
            )
            self._report(
                "INFO",
                f"RizomUV live link OK — {self._state['obj'].name}: "
                f"layer {execution_info.get('uv_layer', '?')}, "
                f"{matched}/{execution_info.get('total_faces', 0)} faces matched, "
                f"{execution_info.get('copied_loops', 0)} loops written "
                f"({self._elapsed:.1f}s). {closing}"
            )
            return self._finish_external(context, success=True)

        # --- Lua script: poll the external process.
        proc = ctx.get("proc")
        if proc is None:
            self._report("WARNING", "RizomUV process is unavailable.")
            return self._finish_external(context, success=False)

        returncode = proc.poll()

        if returncode is None:
            return {'RUNNING_MODAL'}

        try:
            RizomUVBridge.check_exit(ctx, returncode)
            execution_info = RizomUVBridge.finalize(
                self._state["obj"], self._state["settings"], ctx
            )
        except Exception as exc:
            self._report("WARNING", str(exc))
            self._report(
                "WARNING",
                "RizomUV failed: keeping the native unwrap result for this "
                "object. Seams and UVs have been preserved."
            )
            return self._finish_external(context, success=False)

        if execution_info.get("fit_to_tile"):
            self._report(
                "INFO",
                "The layout exceeded the 0-1 tile and was uniformly "
                "rescaled to fit (island proportions preserved)."
            )
        self._report(
            "INFO",
            f"RizomUV OK — {self._state['obj'].name}: "
            f"layer {execution_info.get('uv_layer', '?')}, "
            f"{execution_info.get('copied_loops', 0)} loops written "
            f"({self._elapsed:.1f}s)."
        )

        return self._finish_external(context, success=True)

    def cancel(self, context):
        type(self)._busy = False

        # Dispatch on the bridge mode: RizomUVBridge.terminate only knows the
        # script engine's Popen handle, so calling it on a live-link context
        # left the RizomUV instance launched via RunRizomUV running forever.
        ctx = self._bridge_ctx
        if ctx is not None:
            try:
                if ctx.get("mode") == "link":
                    RizomUVLinkBridge.terminate(ctx)
                else:
                    RizomUVBridge.terminate(ctx)
            except Exception as exc:
                print(f"[IUV] Bridge terminate failed on cancel: {exc}")

        self._cleanup_bridge(failed=True)
        self._release_timer(context)
        self._end_progress(context)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _end_progress(self, context=None):
        try:
            wm = getattr(context, "window_manager", None) if context else None
            if wm is None:
                wm = bpy.context.window_manager
            wm.progress_end()
        except Exception:
            # A: the progress bar is decoration. Blender has no progress
            # context in every situation the operator can run from, and a
            # missing one must never stop the work.
            pass

    def _release_timer(self, context):
        if self._timer is not None:
            try:
                context.window_manager.event_timer_remove(self._timer)
            except Exception:
                # A: the timer may already be gone, which is the normal case when
                # the operator is torn down twice. Removing it again is harmless.
                pass
            self._timer = None

    def _finish_external(self, context, success):
        """Closes the current external object, then continues the queue."""
        self._release_timer(context)

        self._cleanup_bridge(failed=not success)

        state = self._state
        self._state = None

        if state is None:
            self._advance_queue()
            return self._drain_queue(context, already_modal=True)

        name = state["obj"].name
        completed = True

        if success:
            state["island_analysis"] = self._analyze_islands(state, native=False)
            self._final_report(state)
        else:
            # prepare() already ran the native pre-unwrap, so the mesh holds a
            # valid result; finish the native pipeline on top of it.
            completed = self._run_native(context, state, skip_unwrap=True)

        if completed:
            self._mark_ok(name)

        self._advance_queue()

        # Stay modal while draining: the handler is already registered.
        return self._drain_queue(context, already_modal=True)
