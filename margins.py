# pylint: disable=invalid-name
"""
Intelligent UV Mapping — MARGIN CALCULATOR

Single source of truth for island margins and seam margins.
"""

import math


# =============================================================================
# 6. MARGIN CALCULATOR — Automatic Margin / Texture Resolution
# =============================================================================

class MarginResult:
    """Result of the automatic margin calculation."""

    def __init__(self):
        self.ok = False
        self.errors = []
        self.warnings = []

        self.texture_resolution = 2048
        self.margin_px = 4
        self.spacing_px = 4
        self.margin_uv = 0.002
        self.min_seam_edge_length = 0.0
        self.is_auto = True
        # How many edges the seam-margin filter excludes, and whether the
        # threshold had to be capped to keep that number sane.
        self.excluded_edge_fraction = 0.0
        self.seam_margin_capped = False


class MarginCalculator:
    """
    Single source of truth for margins.

    Produces, from the same inputs:
    - native Blender packing margin (UV units)
    - RizomUV MarginPX / SpacingPX (pixels)
    - minimum seam edge length derived from the effective margin
    """

    # The seam-margin filter refuses to cut edges shorter than roughly one
    # margin's worth of texels. Sensible in isolation, but it scales with
    # 1/sqrt(mesh area), so a small dense model sees it explode relative to its
    # own edges: a 47k-face gun measuring 10 square units had 68% of its edges
    # excluded, which left whole cylinders uncuttable no matter what curvature
    # threshold was used. The filter is capped by the real edge length
    # distribution rather than trusted blindly.
    MAX_EXCLUDED_EDGE_FRACTION = 0.15

    @staticmethod
    def get_texture_resolution(settings):
        mode = str(getattr(settings, "texture_resolution_mode", '2K') or '2K').upper()

        if mode == '1K':
            return 1024
        if mode == '2K':
            return 2048
        if mode == '4K':
            return 4096

        try:
            custom = int(getattr(settings, "custom_texture_resolution", 2048) or 2048)
        except Exception:
            custom = 2048

        return max(64, min(16384, custom))

    @classmethod
    def calculate(cls, settings, mesh_analysis=None, island_count=1):
        result = MarginResult()

        if not settings:
            result.errors.append("Settings are unavailable.")
            return result

        try:
            tex_res = cls.get_texture_resolution(settings)
        except Exception as exc:
            result.errors.append(f"Invalid texture resolution: {exc}")
            return result

        result.texture_resolution = tex_res

        try:
            n_islands = max(1, int(island_count or 1))
        except Exception:
            n_islands = 1

        face_count = 0
        edge_count = 0
        total_area = 0.0

        if mesh_analysis is not None and getattr(mesh_analysis, "ok", False):
            try:
                face_count = max(0, int(getattr(mesh_analysis, "face_count", 0) or 0))
                edge_count = max(0, int(getattr(mesh_analysis, "edge_count", 0) or 0))
                total_area = float(getattr(mesh_analysis, "total_area", 0.0) or 0.0)
            except Exception:
                # A: a malformed setting must not stop the run; the caller
                # substitutes a default just below.
                pass

        # ------------------------------------------------------------------
        # Automatic margin in pixels
        # ------------------------------------------------------------------
        base_px = max(2, int(round(tex_res * 0.002)))

        # More islands -> slightly larger spacing to reduce bleed risk.
        count_factor = 1.0 + min(0.5, math.log2(max(n_islands, 1)) / 16.0)

        # Mesh complexity: polygon count and edge density.
        poly_factor = 1.0
        if face_count > 0:
            log_faces = math.log10(max(face_count, 1))
            poly_factor *= max(0.9, min(1.35, 1.0 + (log_faces - 3.0) * 0.04))

            edges_per_face = edge_count / float(max(face_count, 1))
            poly_factor *= max(0.9, min(1.25, 0.85 + edges_per_face * 0.075))

        auto_margin_px = base_px * count_factor * poly_factor

        # Never below 2px, never above ~1% of the resolution.
        max_margin_px = max(16, int(tex_res * 0.01))
        auto_margin_px = max(2, min(max_margin_px, int(round(auto_margin_px))))

        # ------------------------------------------------------------------
        # Resolve the EFFECTIVE margin (auto or manual override) FIRST, so the
        # seam margin below is always derived from the margin actually in use.
        # ------------------------------------------------------------------
        use_auto = bool(getattr(settings, "auto_island_margin", True))
        result.is_auto = use_auto

        if use_auto:
            margin_px = auto_margin_px
            margin_uv = float(margin_px) / float(tex_res)
        else:
            try:
                margin_uv = float(getattr(settings, "island_margin", 0.02) or 0.02)
            except Exception:
                margin_uv = 0.02

            margin_uv = max(0.005, min(0.1, margin_uv))
            margin_px = max(1, int(round(margin_uv * tex_res)))

        result.margin_px = margin_px
        result.spacing_px = margin_px
        result.margin_uv = margin_uv

        # ------------------------------------------------------------------
        # Seam margin: convert the EFFECTIVE pixel margin into a 3D length
        # ------------------------------------------------------------------
        auto_seam_length = 0.0

        if bool(getattr(settings, "auto_seam_margin", True)) and total_area > 1e-8:
            try:
                target_coverage = float(getattr(settings, "target_coverage", 0.95) or 0.95)
            except Exception:
                target_coverage = 0.95
            target_coverage = max(0.2, min(1.0, target_coverage))

            # Estimated UV area once packed into a square of side target_coverage.
            estimated_uv_area = target_coverage * target_coverage

            # pixels_per_world_unit = sqrt(uv_area / mesh_area) * resolution
            try:
                pixels_per_world_unit = (
                    math.sqrt(estimated_uv_area / total_area) * float(tex_res)
                )
            except Exception:
                pixels_per_world_unit = 0.0

            if pixels_per_world_unit > 1e-8:
                auto_seam_length = float(margin_px) / pixels_per_world_unit

        try:
            manual_min_seam = max(0.0, float(getattr(settings, "min_seam_edge_length", 0.0) or 0.0))
        except Exception:
            manual_min_seam = 0.0

        requested = max(auto_seam_length, manual_min_seam)
        capped = requested

        edge_lengths = getattr(mesh_analysis, "edge_lengths", None) or []

        if requested > 0.0 and edge_lengths:
            positive = [length for length in edge_lengths if length > 0.0]

            if positive:
                excluded = sum(1 for length in positive if length < requested)
                fraction = excluded / float(len(positive))

                if fraction > cls.MAX_EXCLUDED_EDGE_FRACTION:
                    ordered = sorted(positive)
                    index = int(len(ordered) * cls.MAX_EXCLUDED_EDGE_FRACTION)
                    index = max(0, min(len(ordered) - 1, index))
                    capped = ordered[index]
                    result.seam_margin_capped = True

                    result.warnings.append(
                        f"Seam margin {requested:.5f} would have excluded "
                        f"{fraction * 100.0:.0f}% of edges from seam planning; "
                        f"capped to {capped:.5f} so the planner can still reach them."
                    )

                recount = sum(1 for length in positive if length < capped)
                result.excluded_edge_fraction = recount / float(len(positive))

        result.min_seam_edge_length = capped

        if not result.errors:
            result.ok = True

        return result
