# pylint: disable=invalid-name
"""
Intelligent UV Mapping — SEAM PLANNER

Seam candidate planning from curvature and material boundaries.
"""

from .curvature import CurvatureEstimator
from .margins import MarginCalculator
from .utils import angle_between_degrees

try:
    import numpy as np
except Exception:  # pragma: no cover - numpy ships with Blender
    np = None


# =============================================================================
# 7. SEAM PLANNER — Cut Candidate Calculation
# =============================================================================

class SeamPlanResult:
    """Result of the seam planning."""

    def __init__(self):
        self.ok = False
        self.errors = []
        self.warnings = []
        self.info = []

        self.is_seam = []
        self.seam_edges = set()

        self.total_edge_count = 0
        self.total_face_count = 0
        self.material_seam_count = 0
        self.preserved_seam_count = 0
        self.angle_seam_count = 0

        self.region_ids = []
        self.region_count = 0
        self.region_face_counts = {}

        # Curvature actually used (manual value or automatic estimate)
        self.effective_curvature_threshold = 60.0
        self.curvature_estimate = None


class SeamPlanner:
    """
    Generates the cut-candidate mask combining:
    - dihedral angle / curvature
    - material boundaries (if enabled)
    - minimum edge length derived from the automatic seam margin
    """

    @staticmethod
    def edge_is_concave(center_a, normal_a, center_b):
        """
        True when the edge between two faces is a valley rather than a ridge.

        `angle_between_degrees` is unsigned, so a 90 degree cube corner and a
        90 degree interior crease look identical to it — yet a seam on the
        corner runs along the silhouette where it shows, while a seam in the
        crease is hidden. Comparing the direction to the neighbour's centre
        against the first face's normal recovers the sign: if the neighbour
        sits on the side the normal points to, the surface folds inwards.
        """
        try:
            dx = float(center_b[0]) - float(center_a[0])
            dy = float(center_b[1]) - float(center_a[1])
            dz = float(center_b[2]) - float(center_a[2])
        except (TypeError, IndexError, ValueError):
            return False

        dot = dx * float(normal_a[0]) + dy * float(normal_a[1]) + dz * float(normal_a[2])
        return dot > 0.0


    @classmethod
    def prune_dangling_seams(cls, mesh_analysis, is_seam, protected=()):
        """
        Removes seam edges that dead-end inside a surface.

        A seam only separates geometry when it runs from boundary to boundary
        or closes a loop. An edge whose endpoint is touched by no other seam
        cuts nothing: the two sides stay connected around it. What it does do
        is add a jagged spur to the island outline, which wastes packing space
        and makes the border harder to hide.

        Real mesh boundaries count as valid endpoints, since the surface is
        already open there.

        The pruning is queue-driven: vertex valences are computed once, leaf
        edges are removed, and only the valences of the touched vertices are
        updated. The previous implementation rebuilt the valence map over
        every edge after every pass, which is O(E^2) on meshes with long spur
        chains; this is O(E).

        Returns the number of seam edges removed.
        """
        edge_vertices = getattr(mesh_analysis, "edge_vertices", None)
        if not edge_vertices:
            return 0

        boundary_edges = getattr(mesh_analysis, "boundary_edges", set()) or set()

        # Vertices that already sit on an open border are valid seam endpoints.
        boundary_verts = set()
        for eidx in boundary_edges:
            if 0 <= eidx < len(edge_vertices):
                boundary_verts.update(edge_vertices[eidx])

        valence = {}
        vert_edges = {}

        for eidx, flag in enumerate(is_seam):
            if not flag or eidx >= len(edge_vertices):
                continue
            for vi in edge_vertices[eidx]:
                valence[vi] = valence.get(vi, 0) + 1
                vert_edges.setdefault(vi, []).append(eidx)

        def is_dangling(eidx):
            # A hand-placed seam is never a spur to be removed: the user may be
            # part-way through cutting, and deleting their work is worse than
            # leaving a stub in the island outline.
            if eidx in protected:
                return False

            for vi in edge_vertices[eidx]:
                if valence.get(vi, 0) == 1 and vi not in boundary_verts:
                    return True
            return False

        queue = [
            eidx for eidx, flag in enumerate(is_seam)
            if flag and eidx < len(edge_vertices) and is_dangling(eidx)
        ]

        removed = 0

        # Removing a spur can expose the next edge as a spur; the queue
        # propagates that without rescanning the whole network.
        while queue:
            eidx = queue.pop()
            if not is_seam[eidx] or not is_dangling(eidx):
                continue

            is_seam[eidx] = False
            removed += 1

            for vi in edge_vertices[eidx]:
                valence[vi] = valence.get(vi, 0) - 1
                if valence[vi] == 1 and vi not in boundary_verts:
                    for other in vert_edges.get(vi, ()):
                        if is_seam[other]:
                            queue.append(other)

        return removed

    @classmethod
    def _compute_regions_after_cut(cls, mesh_analysis, is_seam):
        """
        Connected face regions once the seam edges are cut (union-find).

        One int list, near-linear time; the previous set-adjacency plus
        flood-fill dominated the planner's memory on dense meshes.
        """
        face_count = mesh_analysis.face_count
        parent = list(range(face_count))

        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        faces_per_edge = mesh_analysis.faces_per_edge or []
        edge_count = min(len(faces_per_edge), len(is_seam))

        for eidx in range(edge_count):
            face_list = faces_per_edge[eidx]
            if len(face_list) != 2 or is_seam[eidx]:
                continue

            f1, f2 = face_list[0], face_list[1]
            if 0 <= f1 < face_count and 0 <= f2 < face_count:
                r1, r2 = find(f1), find(f2)
                if r1 != r2:
                    parent[r2] = r1

        region_ids = [-1] * face_count
        remap = {}

        for fidx in range(face_count):
            root = find(fidx)
            rid = remap.get(root)
            if rid is None:
                rid = len(remap)
                remap[root] = rid
            region_ids[fidx] = rid

        return region_ids, len(remap)

    @classmethod
    def _dihedral_angles(cls, mesh_analysis, safe_len):
        """
        Per-edge dihedral angle in degrees, or None for non-manifold edges.

        Vectorized on the numpy copy of the face normals when available;
        the scalar fallback produces the same values.
        """
        faces_per_edge = mesh_analysis.faces_per_edge or []
        face_normals = mesh_analysis.face_normals or []
        face_normals_np = getattr(mesh_analysis, "face_normals_np", None)

        angles = [None] * safe_len

        if np is not None and face_normals_np is not None:
            edge_ids = []
            pairs = []

            for eidx in range(safe_len):
                face_list = faces_per_edge[eidx]
                if len(face_list) != 2:
                    continue

                f1, f2 = face_list[0], face_list[1]
                if 0 <= f1 < len(face_normals_np) and 0 <= f2 < len(face_normals_np):
                    edge_ids.append(eidx)
                    pairs.append((f1, f2))

            if not pairs:
                return angles

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

            computed = np.degrees(np.arccos(dot)).tolist()
            for eidx, angle in zip(edge_ids, computed):
                angles[eidx] = angle

            return angles

        for eidx in range(safe_len):
            face_list = faces_per_edge[eidx]
            if len(face_list) != 2:
                continue

            f1, f2 = face_list[0], face_list[1]
            if not (0 <= f1 < len(face_normals) and 0 <= f2 < len(face_normals)):
                continue

            angles[eidx] = angle_between_degrees(face_normals[f1], face_normals[f2])

        return angles

    @classmethod
    def plan(cls, mesh_analysis, material_analysis, settings, margin_result=None):
        result = SeamPlanResult()

        if not mesh_analysis or not getattr(mesh_analysis, "ok", False):
            result.errors.append("Mesh analysis is invalid.")
            return result

        if not material_analysis or not getattr(material_analysis, "ok", False):
            result.errors.append("Material analysis is invalid.")
            return result

        edge_count = mesh_analysis.edge_count
        face_count = mesh_analysis.face_count

        result.total_edge_count = edge_count
        result.total_face_count = face_count

        is_seam = [False] * edge_count

        # Seed with the seams already on the mesh. The planner adds to the
        # user's work rather than replacing it: a hand-placed cut encodes intent
        # no curvature threshold can infer, and silently deleting it on the next
        # run is the worst possible behaviour.
        preserved = 0
        if bool(getattr(settings, "preserve_existing_seams", True)):
            for eidx in getattr(mesh_analysis, "existing_seams", ()) or ():
                if 0 <= eidx < edge_count:
                    is_seam[eidx] = True
                    result.seam_edges.add(eidx)
                    preserved += 1

        result.preserved_seam_count = preserved

        manual_threshold = max(10.0, min(170.0, float(
            getattr(settings, "curvature_threshold", 60.0)
        )))

        if bool(getattr(settings, "auto_curvature_threshold", True)):
            estimate = CurvatureEstimator.estimate(mesh_analysis, fallback=manual_threshold)
            threshold_deg = estimate.threshold
            result.curvature_estimate = estimate
            if estimate.message:
                result.info.append(estimate.message)
        else:
            threshold_deg = manual_threshold

        result.effective_curvature_threshold = threshold_deg

        separate_by_material = bool(getattr(settings, "separate_by_material", True))

        # Seam margin (minimum edge length). Reuse the caller's margin when given.
        if margin_result is None:
            try:
                margin_result = MarginCalculator.calculate(
                    settings=settings,
                    mesh_analysis=mesh_analysis,
                    island_count=max(1, int(getattr(mesh_analysis, "component_count", 1) or 1)),
                )
            except Exception:
                margin_result = None

        try:
            min_edge_length = max(0.0, float(getattr(margin_result, "min_seam_edge_length", 0.0) or 0.0))
        except Exception:
            min_edge_length = 0.0

        material_boundary_edges = set()
        if separate_by_material:
            material_boundary_edges.update(
                getattr(material_analysis, "material_boundary_edges", set())
            )

        faces_per_edge = mesh_analysis.faces_per_edge or []
        face_normals = mesh_analysis.face_normals or []
        face_centers = getattr(mesh_analysis, "face_centers", None) or []
        edge_lengths = mesh_analysis.edge_lengths or []

        try:
            concave_bias = float(getattr(settings, "concave_seam_bias", 0.0) or 0.0)
        except (TypeError, ValueError):
            concave_bias = 0.0
        concave_bias = max(0.0, min(60.0, concave_bias))

        if concave_bias > 0.0 and not face_centers:
            result.warnings.append(
                "Face centres unavailable: seams cannot prefer concave edges."
            )
            concave_bias = 0.0

        concave_count = 0

        safe_len = min(edge_count, len(faces_per_edge), len(edge_lengths))

        if safe_len == 0:
            result.errors.append(
                "Edge/face topology is empty. Seam planning cannot be performed."
            )
            return result

        material_cut_count = 0
        angle_cut_count = 0

        # Dihedral angles for every manifold edge, computed once (vectorized
        # when the numpy normals are available).
        edge_angles = cls._dihedral_angles(mesh_analysis, safe_len)

        # The sharpest angle in the mesh. The concave bias RAISES the
        # threshold on ridges, but it must never raise it past this value:
        # on a cube (every edge 90 degrees, uniform fallback threshold 81)
        # a +15 degree ridge bias produced a 96 degree threshold and the
        # whole mesh got zero seams. The bias may only decide *which* of the
        # sharp edges cut, never silence all of them.
        max_mesh_angle = 0.0
        for angle in edge_angles:
            if angle is not None and angle > max_mesh_angle:
                max_mesh_angle = angle

        for eidx in range(safe_len):
            face_list = faces_per_edge[eidx]

            # 1. Material boundary: forced cut when the option is active.
            if separate_by_material and eidx in material_boundary_edges:
                is_seam[eidx] = True
                result.seam_edges.add(eidx)
                material_cut_count += 1
                continue

            # 2. Curvature / dihedral angle (manifold edges only).
            if len(face_list) != 2:
                continue

            f1, f2 = face_list[0], face_list[1]
            if not (0 <= f1 < len(face_normals) and 0 <= f2 < len(face_normals)):
                continue

            # Minimum length filter (seam margin).
            if min_edge_length > 0.0 and float(edge_lengths[eidx]) < min_edge_length:
                continue

            angle_deg = edge_angles[eidx]
            if angle_deg is None:
                continue

            # A seam in a valley is hidden; a seam on a ridge runs along the
            # silhouette where it shows. Bias the threshold accordingly instead
            # of treating both the same, which is what a UV artist does by hand.
            effective_threshold = threshold_deg

            if concave_bias > 0.0 and face_centers:
                if 0 <= f1 < len(face_centers) and 0 <= f2 < len(face_centers):
                    if cls.edge_is_concave(
                        face_centers[f1], face_normals[f1], face_centers[f2]
                    ):
                        effective_threshold -= concave_bias
                        concave_count += 1
                    else:
                        effective_threshold += concave_bias

            effective_threshold = max(5.0, min(179.0, effective_threshold))

            # Never above the sharpest angle present (see max_mesh_angle).
            if max_mesh_angle > 0.0:
                effective_threshold = min(effective_threshold, max_mesh_angle)

            # Epsilon keeps exact angles (e.g. a 90 degree cube) reliable.
            if angle_deg >= effective_threshold - 1e-4:
                is_seam[eidx] = True
                result.seam_edges.add(eidx)
                angle_cut_count += 1

        # Drop seams that dead-end inside the surface: they cut nothing and
        # only add spurs to the island outline.
        pruned = 0
        if bool(getattr(settings, "prune_dangling_seams", True)):
            try:
                pruned = cls.prune_dangling_seams(
                    mesh_analysis,
                    is_seam,
                    protected=getattr(mesh_analysis, "existing_seams", ()) or (),
                )
            except Exception as exc:
                result.warnings.append(f"Seam pruning failed: {exc}")

            if pruned:
                result.seam_edges = {
                    i for i, flag in enumerate(is_seam) if flag
                }
                result.info.append(
                    f"Pruned {pruned} dangling seam edges that separated nothing."
                )

        result.is_seam = is_seam
        result.material_seam_count = material_cut_count
        result.angle_seam_count = angle_cut_count

        # Region candidates after the cut
        region_ids, region_count = cls._compute_regions_after_cut(mesh_analysis, is_seam)
        result.region_ids = region_ids
        result.region_count = region_count

        face_counts_by_region = {rid: 0 for rid in range(region_count)}
        for rid in region_ids:
            if rid >= 0:
                face_counts_by_region[rid] += 1

        result.region_face_counts = face_counts_by_region

        # Non-blocking warnings
        min_island_faces = max(1, int(getattr(settings, "minimum_island_face_count", 3) or 3))
        micro_regions = [
            rid for rid, cnt in face_counts_by_region.items() if cnt < min_island_faces
        ]

        if not result.seam_edges:
            result.warnings.append(
                "No seam candidates found with the current parameters."
            )
        elif len(result.seam_edges) > max(32, face_count * 2):
            result.warnings.append(
                f"Very many seam candidates ({len(result.seam_edges)}). "
                "Consider raising the curvature threshold."
            )

        if mesh_analysis.non_manifold_edges:
            result.warnings.append(
                f"Detected {len(mesh_analysis.non_manifold_edges)} non-manifold edges: "
                "inter-region connectivity assumed conservatively."
            )

        if micro_regions:
            result.warnings.append(
                f"Detected {len(micro_regions)} region candidates below the "
                f"minimum face threshold ({min_island_faces})."
            )

        bias_note = ""
        if concave_bias > 0.0:
            bias_note = (
                f", concave bias {concave_bias:.0f} degrees on "
                f"{concave_count} edges"
            )

        if preserved:
            result.info.append(
                f"Kept {preserved} seams already on the mesh."
            )

        result.info.append(
            f"Seam candidates: {len(result.seam_edges)} "
            f"(material: {material_cut_count}, angle: {angle_cut_count}), "
            f"candidate regions: {result.region_count}, "
            f"threshold {threshold_deg:.1f} degrees{bias_note}."
        )

        if not result.errors:
            result.ok = True

        return result
