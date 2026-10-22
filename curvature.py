# pylint: disable=invalid-name
"""
Intelligent UV Mapping — CURVATURE ESTIMATOR

Automatic curvature threshold estimation (Otsu on dihedral angles).
"""

from .utils import angle_between_degrees

try:
    import numpy as np
except Exception:  # pragma: no cover - numpy ships with Blender
    np = None


# =============================================================================
# 6b. CURVATURE ESTIMATOR — Automatic Threshold
# =============================================================================

class CurvatureEstimateResult:
    """Result of the automatic curvature threshold estimation."""

    def __init__(self):
        self.ok = False
        self.threshold = 60.0
        self.method = "default"
        self.sample_count = 0
        self.min_angle = 0.0
        self.max_angle = 0.0
        self.mean_angle = 0.0
        self.message = ""


class CurvatureEstimator:
    """
    Derives a curvature threshold from the mesh instead of a fixed slider value.

    The dihedral angles of manifold edges usually form two clusters: the many
    small angles of smooth surfaces and the few large angles of hard edges.
    Otsu's method finds the split between those clusters without magic numbers.

    Degenerate cases (a cube, where every angle is identical) have no valid
    split, so the estimator falls back to sitting just under the largest angle.
    """

    HISTOGRAM_BINS = 180
    # Below this, the mesh has no real hard edges (organic / subdivided shapes).
    HARD_EDGE_FLOOR_DEG = 30.0
    MIN_THRESHOLD_DEG = 15.0
    MAX_THRESHOLD_DEG = 170.0

    @staticmethod
    def collect_angles(mesh_analysis):
        """Dihedral angles, in degrees, of every manifold edge."""
        faces_per_edge = getattr(mesh_analysis, "faces_per_edge", []) or []
        face_normals = getattr(mesh_analysis, "face_normals", []) or []
        face_normals_np = getattr(mesh_analysis, "face_normals_np", None)

        # Vectorized path: the whole dot/arccos runs in numpy instead of one
        # Python call per edge. Numerically identical inputs (float64) produce
        # the same angles as the scalar path.
        if np is not None and face_normals_np is not None:
            pairs = [
                (fl[0], fl[1])
                for fl in faces_per_edge
                if len(fl) == 2
                and 0 <= fl[0] < len(face_normals_np)
                and 0 <= fl[1] < len(face_normals_np)
            ]

            if not pairs:
                return []

            idx = np.asarray(pairs, dtype=np.int64)
            n1 = face_normals_np[idx[:, 0]]
            n2 = face_normals_np[idx[:, 1]]

            len1 = np.sqrt(np.sum(n1 * n1, axis=1))
            len2 = np.sqrt(np.sum(n2 * n2, axis=1))
            denom = len1 * len2

            valid = denom > 1e-12
            dot = np.zeros(len(pairs), dtype=np.float64)
            dot[valid] = np.sum(n1[valid] * n2[valid], axis=1) / denom[valid]
            dot = np.clip(dot, -1.0, 1.0)

            return np.degrees(np.arccos(dot)).tolist()

        angles = []

        for face_list in faces_per_edge:
            if len(face_list) != 2:
                continue

            f1, f2 = face_list[0], face_list[1]
            if not (0 <= f1 < len(face_normals) and 0 <= f2 < len(face_normals)):
                continue

            angles.append(
                angle_between_degrees(face_normals[f1], face_normals[f2])
            )

        return angles

    @classmethod
    def _otsu_threshold(cls, angles):
        """
        Otsu's method on the angle histogram.

        Returns the threshold in degrees, or None when no valid split exists
        (single cluster: between-class variance never becomes positive).
        """
        bins = cls.HISTOGRAM_BINS
        bin_width = 180.0 / bins
        histogram = [0] * bins

        for angle in angles:
            idx = int(angle / bin_width)
            histogram[min(max(idx, 0), bins - 1)] += 1

        total = len(angles)
        if total == 0:
            return None

        sum_all = sum(i * histogram[i] for i in range(bins))

        weight_bg = 0
        sum_bg = 0.0
        best_variance = 0.0
        best_bin = -1

        for i in range(bins):
            weight_bg += histogram[i]
            if weight_bg == 0:
                continue

            weight_fg = total - weight_bg
            if weight_fg == 0:
                break

            sum_bg += i * histogram[i]

            mean_bg = sum_bg / weight_bg
            mean_fg = (sum_all - sum_bg) / weight_fg

            variance = weight_bg * weight_fg * (mean_bg - mean_fg) ** 2

            if variance > best_variance:
                best_variance = variance
                best_bin = i

        if best_bin < 0 or best_variance <= 0.0:
            return None

        split = (best_bin + 1) * bin_width

        # Sitting on the bin edge is fragile: the smooth cluster can sit a hair
        # below it and be re-captured by the planner's comparison epsilon.
        # Place the threshold midway through the empty gap between clusters.
        below = [a for a in angles if a < split]
        above = [a for a in angles if a >= split]

        if not below or not above:
            return split

        return (max(below) + min(above)) * 0.5

    @classmethod
    def estimate(cls, mesh_analysis, fallback=60.0):
        result = CurvatureEstimateResult()
        result.threshold = float(fallback)

        angles = cls.collect_angles(mesh_analysis)
        result.sample_count = len(angles)

        if not angles:
            result.method = "default"
            result.message = (
                "No manifold edges available: using the manual threshold."
            )
            return result

        result.min_angle = min(angles)
        result.max_angle = max(angles)
        result.mean_angle = sum(angles) / float(len(angles))

        # No hard edges at all: curvature cuts would carve up a smooth surface.
        if result.max_angle < cls.HARD_EDGE_FLOOR_DEG:
            result.threshold = float(fallback)
            result.method = "no_hard_edges"
            result.ok = True
            result.message = (
                f"No hard edges detected (max angle {result.max_angle:.1f} degrees): "
                "keeping the manual threshold."
            )
            return result

        threshold = cls._otsu_threshold(angles)
        method = "otsu"

        if threshold is None or threshold >= result.max_angle:
            # Single cluster (e.g. a cube: every angle is 90 degrees).
            # Sit just below the largest angle so those edges still get cut.
            threshold = result.max_angle * 0.9
            method = "uniform_fallback"

        threshold = max(cls.MIN_THRESHOLD_DEG, min(cls.MAX_THRESHOLD_DEG, threshold))

        result.threshold = threshold
        result.method = method
        result.ok = True
        result.message = (
            f"Auto curvature: {threshold:.1f} degrees ({method}, "
            f"{len(angles)} edges, range {result.min_angle:.1f}-{result.max_angle:.1f})."
        )

        return result
