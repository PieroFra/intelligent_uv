# pylint: disable=invalid-name
"""
Intelligent UV Mapping — NATIVE PIPELINE

Everything that happens to a single object once its seams are decided: unwrap,
recover what failed, relax, measure, orient, stack, pack, report.

The order is not arbitrary and most of it is load-bearing. Recovery has to see
a finished unwrap to know what failed. Relaxation moves UVs inside islands, so
it must precede packing. Orientation and stacking change island shapes and
positions, so they precede packing too. UDIM comes last because it assumes
everything already sits in 0-1.
"""

import bpy

from .. import orientation, recovery, stacking, texture_sets, udim
from ..distortion import DistortionAnalyzer
from ..island_extraction import IslandExtractor
from ..seam_marking import SeamMarker
from ..texel_density import TexelDensityNormalizer
from ..uv_executor import MinimalUVExecutor


class NativePipelineMixin:
    """The per-object unwrap pipeline."""

    def _run_native(self, context, state, skip_unwrap=False):
        """
        Native unwrap (optional), texel density, packing and coverage.

        Returns True when the object completed. The caller uses this instead of
        marking every object successful unconditionally, which would report a
        failed object as completed.
        """
        obj = state["obj"]
        settings = state["settings"]
        seam_plan = state["seam_plan"]
        margin_result = state["margin_result"]

        if not skip_unwrap:
            try:
                execution_info = MinimalUVExecutor.execute_unwrap(
                    obj=obj,
                    settings=settings,
                    margin_uv=margin_result.margin_uv,
                    use_seams=len(seam_plan.seam_edges) > 0,
                )
            except Exception as exc:
                self._mark_failed(obj.name, f"native unwrap failed: {exc}")
                self._report("ERROR", f"Native unwrap failed for {obj.name}: {exc}")
                return False

            if execution_info.get("method") == "smart_project":
                self._report(
                    "WARNING",
                    "No seams were planned: Smart UV Project used as a fallback."
                )

        # Rescue the islands the solver could not flatten. Blender already
        # said which ones by count; this finds them and cuts them open.
        if not skip_unwrap and bool(
            getattr(settings, "recover_failed_islands", True)
        ):
            uv_name = str(
                getattr(settings, "uv_layer_name", "SmartUV") or "SmartUV"
            )

            def _layer():
                return MinimalUVExecutor.get_uv_layer(obj.data, uv_name)

            def _islands():
                return self._analyze_islands(state, native=True)

            def _unwrap():
                MinimalUVExecutor.execute_unwrap(
                    obj=obj,
                    settings=settings,
                    margin_uv=margin_result.margin_uv,
                    use_seams=True,
                )

            def _mark(mask):
                return SeamMarker.mark_real_seams(obj.data, mask)

            try:
                recovery.recover(
                    obj.data, _layer, _islands, state["mesh_analysis"],
                    seam_plan.is_seam, _unwrap, _mark,
                    start_tolerance=float(
                        getattr(settings, "recovery_tolerance", 15.0) or 15.0
                    ),
                    max_rounds=int(
                        getattr(settings, "recovery_rounds", 2) or 0
                    ),
                    report=self._report,
                )
            except Exception as exc:
                self._report("WARNING", f"Island recovery failed: {exc}")

        # Relax before measuring: the island analysis and the density
        # normalization should both see the final interior layout.
        if bool(getattr(settings, "minimize_stretch", True)):
            relax_ok, relax_msg = MinimalUVExecutor.minimize_stretch(
                obj,
                str(getattr(settings, "uv_layer_name", "SmartUV") or "SmartUV"),
                iterations=getattr(settings, "minimize_stretch_iterations", 32),
            )
            self._report("INFO" if relax_ok else "WARNING", relax_msg)

        island_analysis = self._analyze_islands(state, native=True)
        state["island_analysis"] = island_analysis

        if bool(getattr(settings, "normalize_texel_density", True)):
            if island_analysis is not None and island_analysis.ok:
                norm_result = TexelDensityNormalizer.normalize(
                    obj=obj,
                    island_analysis=island_analysis,
                    mesh_analysis=state["mesh_analysis"],
                    settings=settings,
                )
                self._report(
                    "INFO" if norm_result.get("ok") else "WARNING",
                    norm_result.get("message", ""),
                )
            else:
                self._report(
                    "WARNING",
                    "Texel density normalization skipped: island analysis unavailable."
                )

        # Orient before stacking and packing: the packer arranges islands but
        # never reshapes them, so a shell left at an angle carries its oversized
        # bounding rectangle into whatever the packer does with it.
        if bool(getattr(settings, "orient_islands", True)):
            uv_layer = MinimalUVExecutor.get_uv_layer(
                obj.data,
                str(getattr(settings, "uv_layer_name", "SmartUV") or "SmartUV"),
            )
            if (uv_layer is not None and island_analysis is not None
                    and island_analysis.ok):
                try:
                    orientation.orient_islands(
                        obj.data, uv_layer, island_analysis,
                        report=self._report,
                    )
                except Exception as exc:
                    self._report("WARNING", f"Island orientation failed: {exc}")

        # Stack repeats BEFORE packing, so the space they free is actually
        # redistributed. Doing it afterwards would leave holes where the
        # duplicates used to be.
        if bool(getattr(settings, "stack_duplicates", False)):
            uv_layer = MinimalUVExecutor.get_uv_layer(
                obj.data,
                str(getattr(settings, "uv_layer_name", "SmartUV") or "SmartUV"),
            )
            if (uv_layer is not None and island_analysis is not None
                    and island_analysis.ok):
                try:
                    stacking.stack_duplicates(
                        obj.data, uv_layer, island_analysis,
                        state["mesh_analysis"], report=self._report,
                    )
                except Exception as exc:
                    self._report("WARNING", f"Duplicate stacking failed: {exc}")

        try:
            bpy.context.window_manager.progress_update(85)
        except Exception:
            # A: the progress bar is decoration. Blender has no progress
            # context in every situation the operator can run from, and a
            # missing one must never stop the work.
            pass

        # One texture per material means each material addresses the same 0-1
        # square, so sharing one square between them wastes most of every
        # texture: the metal parts sit in a corner of the metal image and
        # nothing uses the rest.
        target_layer = str(
            getattr(settings, "uv_layer_name", "SmartUV") or "SmartUV"
        )
        preserve = bool(getattr(settings, "normalize_texel_density", True))

        use_sets = (
            bool(getattr(settings, "texture_sets", False))
            and texture_sets.material_slot_count(obj) > 1
        )

        pack_ok, pack_msg = False, ""

        if use_sets:
            try:
                set_result = texture_sets.pack_per_material(
                    obj, margin_result.margin_uv, target_layer,
                    preserve_scale=preserve, report=self._report,
                )
            except Exception as exc:
                self._report("WARNING", f"Texture set packing failed: {exc}")
                set_result = None

            if set_result is not None and set_result.packed:
                state["texture_sets"] = set_result.packed
                pack_ok = True
                pack_msg = f"Packed {set_result.packed} texture sets."
            else:
                # Fall through to a single square rather than leaving the
                # islands wherever the unwrap put them.
                use_sets = False

        if not use_sets:
            # The packer rescales islands by default, which would undo the
            # normalization performed just above.
            pack_ok, pack_msg = MinimalUVExecutor.pack_islands(
                obj,
                margin_result.margin_uv,
                preserve_scale=preserve,
                uv_layer_name=target_layer,
            )

        self._report("INFO" if pack_ok else "WARNING", pack_msg)

        # UDIM runs last, after everything is packed into 0-1: moving an island
        # to tile N is then adding an integer, and nothing here has to know how
        # the packing was decided.
        if bool(getattr(settings, "use_udim", False)):
            uv_layer = MinimalUVExecutor.get_uv_layer(obj.data, target_layer)
            island_analysis = state.get("island_analysis")
            try:
                udim_result = udim.apply(
                    obj.data, uv_layer, island_analysis,
                    state["material_analysis"], settings, report=self._report,
                )
            except Exception as exc:
                self._report("WARNING", f"UDIM layout failed: {exc}")
                udim_result = None

            if udim_result is not None and udim_result.tiles > 1:
                state["udim_tiles"] = udim_result.tiles

        uv_layer = MinimalUVExecutor.get_uv_layer(
            obj.data,
            str(getattr(settings, "uv_layer_name", "SmartUV") or "SmartUV"),
        )
        if state.get("udim_tiles"):
            # Coverage scaling normalises the whole layout into the unit
            # square, which would collapse every tile back onto tile 1001.
            self._report(
                "INFO",
                "Coverage scaling skipped: the layout spans several UDIM tiles."
            )
            cov_ok, cov_msg = True, ""
        else:
            cov_ok, cov_msg = MinimalUVExecutor.apply_target_coverage(
                obj.data, uv_layer, settings
            )

        if not cov_ok:
            self._report("WARNING", f"{obj.name}: {cov_msg}")

        self._final_report(state)
        return True

    def _analyze_islands(self, state, native):
        # Region ids are per-face and survive the RizomUV round trip, so the
        # planner partition is a valid hint regardless of the native flag. The
        # parameter is kept for signature stability.
        obj = state["obj"]
        face_count = len(obj.data.polygons)
        region_ids = None
        try:
            plan = state.get("seam_plan")
            candidate = getattr(plan, "region_ids", None)
            if candidate is not None and len(candidate) == face_count:
                region_ids = candidate
            else:
                planned = len(candidate) if candidate is not None else 0
                self._report(
                    "WARNING",
                    f"{obj.name}: unusable region ids ({face_count} faces vs "
                    f"{planned} ids), falling back to mesh components.",
                )
        except Exception as exc:
            self._report(
                "WARNING",
                f"{obj.name}: region ids unavailable ({exc}), "
                "falling back to mesh components.",
            )

        try:
            island_analysis = IslandExtractor.analyze(
                obj=obj,
                settings=state["settings"],
                material_analysis=state["material_analysis"],
                region_ids=region_ids,
            )
        except Exception as exc:
            self._report("WARNING", f"UV island analysis failed: {exc}")
            return None

        for warning in island_analysis.warnings:
            self._report("WARNING", f"UV islands: {warning}")

        return island_analysis

    def _final_report(self, state):
        obj = state["obj"]
        settings = state["settings"]
        seam_plan = state["seam_plan"]
        margin_result = state["margin_result"]

        # Quality metrics on the finished layout.
        if bool(getattr(settings, "report_distortion", True)):
            uv_layer = MinimalUVExecutor.get_uv_layer(
                obj.data,
                str(getattr(settings, "uv_layer_name", "SmartUV") or "SmartUV"),
            )

            try:
                distortion = DistortionAnalyzer.analyze(
                    obj.data, uv_layer, state["mesh_analysis"]
                )
            except Exception as exc:
                self._report("WARNING", f"Distortion analysis failed: {exc}")
                distortion = None

            target_name = str(
                getattr(settings, "uv_layer_name", "SmartUV") or "SmartUV"
            )
            measured_name = getattr(uv_layer, "name", None)

            if measured_name != target_name:
                # get_uv_layer falls back to the first layer when the target is
                # missing. Measuring that would report on a layout this add-on
                # never produced.
                self._report(
                    "WARNING",
                    f"Quality metrics skipped: '{target_name}' was not found, "
                    f"so the only readable layer is '{measured_name}'."
                )
                distortion = None

            if distortion is not None and distortion.ok:
                layer_name = measured_name
                self._report(
                    "INFO", f"Quality [{layer_name}] — {distortion.summary()}"
                )

                # Distortion says whether the texture is stretched; this says
                # how much of it the asset never uses. Both matter and neither
                # implies the other.
                island_analysis = state.get("island_analysis")
                if island_analysis is not None and island_analysis.ok:
                    try:
                        fill = DistortionAnalyzer.measure_fill(
                            obj.data, uv_layer, island_analysis
                        )
                    except Exception as exc:
                        self._report("WARNING", f"Fill measurement failed: {exc}")
                        fill = None

                    if fill:
                        self._report(
                            "INFO",
                            f"Packing — {fill['coverage'] * 100.0:.1f}% of the UV "
                            f"square covered, {fill['efficiency'] * 100.0:.1f}% of "
                            f"the occupied area used, {fill['island_count']} islands."
                        )

                        ceiling = state.get("island_ceiling") or 0
                        if ceiling and fill["island_count"] > ceiling:
                            self._report(
                                "WARNING",
                                f"{fill['island_count']} islands is past the "
                                f"~{ceiling} where padding costs more than the "
                                "extra cuts save. Raise the cluster tolerance "
                                "or set a lower island target."
                            )

                        if fill["efficiency"] < 0.5:
                            self._report(
                                "WARNING",
                                "Less than half the occupied area is island: the "
                                "islands are packed loosely rather than scaled small."
                            )
                for warning in distortion.warnings:
                    self._report("WARNING", warning)

                # An aggregate figure cannot say whether the damage is
                # concentrated or spread out, and those need opposite fixes.
                island_analysis = state.get("island_analysis")
                if island_analysis is not None and island_analysis.ok:
                    try:
                        rows = DistortionAnalyzer.per_island_report(
                            obj.data, uv_layer, state["mesh_analysis"],
                            island_analysis,
                        )
                    except Exception as exc:
                        self._report("WARNING", f"Per-island report failed: {exc}")
                        rows = []

                    worst = [r for r in rows if r["collapsed"] or r["relative"] < 0.5
                             or r["relative"] > 2.0]
                    if worst:
                        self._report(
                            "WARNING",
                            "Worst islands (id: faces, collapsed, density x mean): "
                            + "; ".join(
                                f"{r['id']}: {r['faces']}f, {r['collapsed']} collapsed, "
                                f"{r['relative']:.2f}x"
                                for r in worst[:6]
                            )
                        )

        if bool(getattr(settings, "check_overlaps", True)):
            island_analysis = state.get("island_analysis")
            if island_analysis is not None and island_analysis.ok:
                uv_layer = MinimalUVExecutor.get_uv_layer(
                    obj.data,
                    str(getattr(settings, "uv_layer_name", "SmartUV") or "SmartUV"),
                )

                try:
                    overlaps, checked, gave_up = DistortionAnalyzer.find_real_overlaps(
                        obj.data, uv_layer, island_analysis
                    )

                    # Islands in different texture sets share coordinates by
                    # design: they sample different images, so they can never
                    # collide however much they overlap.
                    if state.get("texture_sets"):
                        groups = texture_sets.island_material_groups(
                            island_analysis, state["material_analysis"]
                        )
                        overlaps = [
                            (a, b) for a, b in overlaps
                            if groups.get(a) == groups.get(b)
                        ]
                except Exception as exc:
                    self._report("WARNING", f"Overlap test failed: {exc}")
                    overlaps, checked, gave_up = [], 0, False

                if gave_up:
                    self._report(
                        "WARNING",
                        f"{len(overlaps)} island bounding boxes intersect, too many "
                        "to verify precisely. Check the UV editor."
                    )
                elif overlaps:
                    shown = ", ".join(f"{a}/{b}" for a, b in overlaps[:5])
                    more = "" if len(overlaps) <= 5 else f" (+{len(overlaps) - 5} more)"
                    self._report(
                        "WARNING",
                        f"{len(overlaps)} island pairs genuinely overlap ({shown}{more}). "
                        "Verified by edge intersection rather than bounding boxes "
                        f"({checked} candidate pairs tested)."
                    )
                elif checked:
                    self._report(
                        "INFO",
                        f"No real overlaps: all {checked} bounding-box candidates "
                        "cleared the edge intersection test."
                    )

        try:
            from .. import bl_info as _bl_info
            version = ".".join(str(n) for n in _bl_info.get("version", ()))
        except Exception:
            version = "?"

        self._report(
            "INFO",
            f"Intelligent UV v{version} OK — {obj.name}: "
            f"{state['mesh_analysis'].face_count} faces, "
            f"curvature {seam_plan.effective_curvature_threshold:.1f} degrees, "
            f"{len(seam_plan.seam_edges)} seams, {seam_plan.region_count} islands, "
            f"margin {margin_result.margin_px}px @ {margin_result.texture_resolution} "
            f"({margin_result.margin_uv:.5f} UV)."
        )
