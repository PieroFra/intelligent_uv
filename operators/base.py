# pylint: disable=invalid-name
"""Intelligent UV Mapping — shared operator base."""

import bpy

from ..margins import MarginCalculator
from ..material_analysis import MaterialAnalyzer
from ..mesh_analysis import MeshAnalyzer
from .. import auto_params
from .. import symmetry
from ..preflight import Preflight
from ..region_merge import RegionMerger, RegionSplitter
from .. import vsa
from ..seam_planning import SeamPlanResult, SeamPlanner
from ..validation import ContextGuard


class IntelligentUVBaseOperator(bpy.types.Operator):
    """Shared analysis pipeline for the add-on operators."""

    bl_options = {'REGISTER', 'UNDO'}

    def _report(self, msg_type, message):
        if message:
            self.report({msg_type}, message)

    def _run_analysis(self, context):
        """
        Runs guard -> mesh -> material -> margin -> seam planning.

        Returns a dict on success, or None after reporting the error.
        """
        guard_result = ContextGuard.validate_for_uv(context)
        if not guard_result.ok:
            self._report("ERROR", f"Blocked: {guard_result.error_message()}")
            return None

        obj = guard_result.object
        settings = context.scene.intelligent_uv_settings

        # Seam marking and UV writes require Object Mode.
        if context.mode != 'OBJECT':
            try:
                bpy.ops.object.mode_set(mode='OBJECT')
            except Exception as exc:
                self._report("ERROR", f"Unable to switch to Object Mode: {exc}")
                return None

        try:
            mesh_analysis = MeshAnalyzer.analyze(obj.data)
        except Exception as exc:
            self._report("ERROR", f"Mesh analysis failed: {exc}")
            return None

        if not mesh_analysis.ok:
            self._report(
                "ERROR",
                "Mesh analysis failed: " + (
                    " | ".join(mesh_analysis.errors) or "unknown error."
                ),
            )
            return None

        # Pre-flight quality gate: non-manifold edges are the top cause of
        # failed unfolds downstream (RizomUV reports them as
        # BijectionFailedIslandIDs and keeps the pre-computed UVs), so warn
        # early while the mesh is still cheap to fix.
        non_manifold = len(
            getattr(mesh_analysis, "non_manifold_edges", None) or ())
        if non_manifold:
            self._report(
                "WARNING",
                f"{obj.name}: {non_manifold} non-manifold edges. Unfold "
                "may fail on the affected islands; consider Mesh > Clean Up "
                "> Merge by Distance and Select > All by Trait > "
                "Non Manifold to inspect them."
            )

        try:
            material_analysis = MaterialAnalyzer.analyze(obj, mesh_analysis)
        except Exception as exc:
            self._report("ERROR", f"Material analysis failed: {exc}")
            return None

        if not material_analysis.ok:
            self._report(
                "ERROR",
                "Material analysis failed: " + (
                    " | ".join(material_analysis.errors) or "unknown error."
                ),
            )
            return None

        # First margin pass: island count estimated from mesh components.
        margin_result = MarginCalculator.calculate(
            settings=settings,
            mesh_analysis=mesh_analysis,
            island_count=max(1, mesh_analysis.component_count or 1),
        )

        method = str(getattr(settings, "seam_method", "THRESHOLD") or "THRESHOLD")

        # Derive the clustering parameters from this mesh before planning with
        # them. Done here rather than in the UI because the margin is only
        # known once the texture size and the mesh have both been measured.
        if method == 'VSA' and bool(getattr(settings, "auto_parameters", True)):
            try:
                derived = auto_params.derive(
                    mesh_analysis, margin_result, settings
                )
                auto_params.apply_to(settings, derived, report=self._report)

                ceiling = derived.island_ceiling
                if ceiling and 0 < ceiling < 4000:
                    state_ceiling = ceiling
                else:
                    state_ceiling = 0
            except Exception as exc:
                self._report("WARNING", f"Automatic parameters failed: {exc}")
                state_ceiling = 0
        else:
            state_ceiling = 0

        try:
            if method == 'VSA':
                # Clustering decides regions first and derives seams from their
                # borders, rather than judging each edge on its own. The result
                # is adapted to the shape the rest of the pipeline expects.
                vsa_result = vsa.plan_seams(
                    mesh_analysis, material_analysis, settings
                )

                if not vsa_result.ok:
                    self._report(
                        "WARNING",
                        "Shape clustering failed (" + (
                            " | ".join(vsa_result.errors) or "unknown error"
                        ) + "); falling back to the curvature threshold."
                    )
                    seam_plan = SeamPlanner.plan(
                        mesh_analysis, material_analysis, settings, margin_result
                    )
                else:
                    seam_plan = SeamPlanResult()
                    seam_plan.ok = True
                    seam_plan.is_seam = vsa_result.is_seam
                    seam_plan.seam_edges = vsa_result.seam_edges
                    seam_plan.warnings = list(vsa_result.warnings)
                    seam_plan.info = list(vsa_result.info)
                    seam_plan.effective_curvature_threshold = float(
                        getattr(settings, "vsa_max_angle_deviation", 25.0) or 25.0
                    )

                    # The clusters ARE the regions, so there is no need to
                    # re-derive them by flood filling across the new seams.
                    seam_plan.region_ids = vsa_result.face_cluster
                    seam_plan.region_count = vsa_result.cluster_count
            else:
                seam_plan = SeamPlanner.plan(
                    mesh_analysis, material_analysis, settings, margin_result
                )
        except Exception as exc:
            self._report("ERROR", f"Seam planning failed: {exc}")
            return None

        if not seam_plan.ok:
            self._report(
                "ERROR",
                "Seam planning failed: " + (
                    " | ".join(seam_plan.errors) or "unknown error."
                ),
            )
            return None

        # Second margin pass: now the real region count is known.
        margin_result = MarginCalculator.calculate(
            settings=settings,
            mesh_analysis=mesh_analysis,
            island_count=max(1, seam_plan.region_count or 1),
        )

        # Split regions that cannot be flattened BEFORE merging: the merger
        # would otherwise happily fuse them into something even less
        # developable, and the unwrap solver would fail on the result.
        if method != 'VSA' and bool(getattr(settings, "split_non_developable", True)):
            try:
                added, split_count, notes = RegionSplitter.split(
                    mesh_analysis, seam_plan, settings
                )
            except Exception as exc:
                self._report("WARNING", f"Region splitting failed: {exc}")
                added, notes = 0, []

            for note in notes:
                self._report("INFO", note)

            if added:
                # The extra cuts change the regions, so recompute them.
                seam_plan.seam_edges = {
                    i for i, flag in enumerate(seam_plan.is_seam) if flag
                }
                region_ids, region_count = SeamPlanner._compute_regions_after_cut(
                    mesh_analysis, seam_plan.is_seam
                )
                seam_plan.region_ids = region_ids
                seam_plan.region_count = region_count

        # Mirror the seams before merging or writing. Clustering runs over the
        # whole mesh at once and grows the two halves independently, so a
        # border that lands on a crease on one side drifts a face off it on the
        # other. Nothing is wrong with that and it reads as a mistake.
        if bool(getattr(settings, "symmetrize_seams", True)):
            try:
                symmetry.apply(
                    mesh_analysis, seam_plan.is_seam, settings,
                    report=self._report,
                )
                seam_plan.seam_edges = {
                    i for i, flag in enumerate(seam_plan.is_seam) if flag
                }
                region_ids, region_count = SeamPlanner._compute_regions_after_cut(
                    mesh_analysis, seam_plan.is_seam
                )
                seam_plan.region_ids = region_ids
                seam_plan.region_count = region_count
            except Exception as exc:
                self._report("WARNING", f"Symmetry pass failed: {exc}")

        # Merge over-fragmented regions before anything is written.
        #
        # Skipped under VSA: clustering already produced coherent regions, so
        # the merger has nothing to repair, and it is the slowest stage in the
        # pipeline by a wide margin — on a 47k-face mesh it runs for minutes
        # while clustering finishes in under a second.
        merge_enabled = bool(getattr(settings, "merge_islands", True))

        if method == 'VSA' and merge_enabled:
            if bool(getattr(settings, "vsa_merge_clusters", False)):
                self._report(
                    "INFO",
                    "Merging VSA clusters: this is slow on dense meshes."
                )
            else:
                merge_enabled = False

        if merge_enabled:
            try:
                merge_result = RegionMerger.merge(
                    mesh_analysis, material_analysis, seam_plan, settings
                )
            except Exception as exc:
                self._report("WARNING", f"Island merging failed: {exc}")
                merge_result = None

            if merge_result is not None and merge_result.ok:
                seam_plan.is_seam = merge_result.is_seam
                seam_plan.seam_edges = {
                    i for i, flag in enumerate(merge_result.is_seam) if flag
                }
                seam_plan.region_ids = merge_result.region_ids
                seam_plan.region_count = merge_result.region_count

                for note in merge_result.info:
                    self._report("INFO", note)

        # Pre-flight before anything is planned. A blocker means the unwrap
        # will produce garbage, and finding that out from the quality report
        # afterwards costs a full run and leaves the user guessing why.
        if bool(getattr(settings, "run_preflight", True)):
            try:
                preflight = Preflight.run(obj, mesh_analysis)
            except Exception as exc:
                self._report("WARNING", f"Pre-flight check failed: {exc}")
                preflight = None

            if preflight is not None:
                for finding in preflight.blockers:
                    self._report("ERROR", finding.format())
                for finding in preflight.warnings:
                    self._report("WARNING", finding.format())

                if not preflight.ok and bool(
                    getattr(settings, "stop_on_blockers", True)
                ):
                    self._report(
                        "ERROR",
                        "Stopped before unwrapping: fix the blocking problems "
                        "above, or turn off Stop On Problems to run anyway."
                    )
                    return None

        for warning in getattr(margin_result, "warnings", []) or []:
            self._report("WARNING", f"Margin: {warning}")

        for warning in mesh_analysis.warnings:
            self._report("WARNING", f"Mesh: {warning}")
        for warning in material_analysis.warnings:
            self._report("WARNING", f"Materials: {warning}")
        for warning in seam_plan.warnings:
            self._report("WARNING", f"Seams: {warning}")
        for note in seam_plan.info:
            self._report("INFO", note)

        return {
            "island_ceiling": state_ceiling,
            "obj": obj,
            "settings": settings,
            "mesh_analysis": mesh_analysis,
            "material_analysis": material_analysis,
            "seam_plan": seam_plan,
            "margin_result": margin_result,
        }
