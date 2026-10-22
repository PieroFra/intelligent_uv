# pylint: disable=invalid-name
"""
Intelligent UV Mapping — REGION MERGER

Island merging to control fragmentation.
"""

from .utils import angle_between_degrees, normalize_vector


class MergeResult:
    """Result of the region merging pass."""

    def __init__(self):
        self.ok = False
        self.warnings = []
        self.info = []

        self.is_seam = []
        self.region_ids = []
        self.region_count = 0

        self.regions_before = 0
        self.seams_before = 0
        self.merges_performed = 0
        self.micro_absorbed = 0


class RegionMerger:
    """
    Reduces island fragmentation after seam planning.

    A pure angle threshold cuts wherever the surface bends, which shatters
    curved models into many small regions (a monkey head becomes ~30 islands).
    Most of those cuts buy nothing: two adjacent regions often flatten perfectly
    well together.

    The merge criterion is the *normal cone* of the merged region: the maximum
    angle between any face normal and the region's area-weighted average normal.
    A small cone means the patch is close to developable and will unwrap with
    low distortion; a large cone means it wraps around and genuinely needs the
    cut.

    Candidate cones are memoized per root pair and invalidated only for pairs
    touching a region that changed, which is what keeps the greedy loop from
    rescanning the same unchanged pairs on every pass.

    Merging never crosses a material boundary when the user asked to separate
    by material, and never merges disconnected components.
    """

    # Safety guard only. The real termination condition is "no merge happened in
    # the last pass". Each merge removes one live region, so len(regions) + 1 is
    # a hard upper bound on useful passes; the constant only caps pathological
    # states. Never raise this above the region bound: a lower cap would stop
    # merging early and silently leave extra islands.
    _SAFETY_PASS_CAP = 1024

    @classmethod
    def _weighted_normal_sum(cls, faces, face_normals, face_areas):
        acc = [0.0, 0.0, 0.0]

        for fidx in faces:
            if not (0 <= fidx < len(face_normals)):
                continue

            normal = face_normals[fidx]
            weight = face_areas[fidx] if 0 <= fidx < len(face_areas) else 1.0
            weight = max(weight, 1e-12)

            acc[0] += normal[0] * weight
            acc[1] += normal[1] * weight
            acc[2] += normal[2] * weight

        return acc

    @classmethod
    def _add_weighted_sums(cls, sum_a, sum_b):
        return [sum_a[0] + sum_b[0], sum_a[1] + sum_b[1], sum_a[2] + sum_b[2]]

    @classmethod
    def _worst_angle_to_mean(cls, mean, face_lists, face_normals):
        worst = 0.0

        for faces in face_lists:
            for fidx in faces:
                if not (0 <= fidx < len(face_normals)):
                    continue

                angle = angle_between_degrees(mean, face_normals[fidx])
                worst = max(worst, angle)

        return worst

    @classmethod
    def _cone_half_angle_from_sum(cls, weighted_sum, faces, face_normals):
        mean = normalize_vector(weighted_sum)
        if mean is None:
            return 180.0

        return cls._worst_angle_to_mean(mean, (faces,), face_normals)

    @classmethod
    def _cone_half_angle_from_two_sums_and_face_lists(
        cls, weighted_sum, faces_a, faces_b, face_normals
    ):
        mean = normalize_vector(weighted_sum)
        if mean is None:
            return 180.0

        return cls._worst_angle_to_mean(mean, (faces_a, faces_b), face_normals)

    @classmethod
    def _build_adjacency(cls, is_seam, region_ids, faces_per_edge, material_boundary):
        adjacency = {}

        for eidx, face_list in enumerate(faces_per_edge):
            if eidx >= len(is_seam) or not is_seam[eidx]:
                continue
            if len(face_list) != 2:
                continue
            if eidx in material_boundary:
                continue

            r1 = region_ids[face_list[0]]
            r2 = region_ids[face_list[1]]
            if r1 == r2 or r1 < 0 or r2 < 0:
                continue

            adjacency.setdefault((min(r1, r2), max(r1, r2)), []).append(eidx)

        return adjacency

    @classmethod
    def _evaluate_candidate_core(
        cls, root_a, root_b, region_faces, region_sums, face_normals,
        max_cone, relaxed_cone, min_faces, absorb_micro,
    ):
        faces_a = region_faces[root_a]
        faces_b = region_faces[root_b]
        if not faces_a or not faces_b:
            return None

        merged_sum = cls._add_weighted_sums(region_sums[root_a], region_sums[root_b])
        merged_cone = cls._cone_half_angle_from_two_sums_and_face_lists(
            merged_sum, faces_a, faces_b, face_normals
        )

        smaller = min(len(faces_a), len(faces_b))
        larger = max(len(faces_a), len(faces_b))

        is_micro = (
            absorb_micro
            and smaller < min_faces
            and larger >= min_faces
            and merged_cone <= relaxed_cone
        )

        if merged_cone <= max_cone or is_micro:
            return (0 if is_micro else 1, smaller, merged_cone, is_micro)

        return None

    @classmethod
    def _apply_merges(cls, candidates, parent, region_faces, region_sums, find):
        merged_count = 0
        micro_absorbed_count = 0
        touched = set()
        touched_roots = set()

        for _prio, _size, _cone, root_a, root_b, is_micro in candidates:
            if root_a in touched or root_b in touched:
                continue

            root_a = find(root_a)
            root_b = find(root_b)
            if root_a == root_b:
                continue

            if len(region_faces[root_a]) < len(region_faces[root_b]):
                root_a, root_b = root_b, root_a

            parent[root_b] = root_a
            # extend() reuses the existing list; `a + b` allocates a full copy
            # per merge, which is O(F^2) over a long merge chain.
            region_faces[root_a].extend(region_faces[root_b])
            region_faces[root_b] = []
            region_sums[root_a] = cls._add_weighted_sums(
                region_sums[root_a], region_sums[root_b]
            )
            region_sums[root_b] = [0.0, 0.0, 0.0]

            touched.add(root_a)
            touched.add(root_b)
            touched_roots.add(root_a)
            touched_roots.add(root_b)

            merged_count += 1
            if is_micro:
                micro_absorbed_count += 1

        return merged_count, micro_absorbed_count, touched_roots

    @classmethod
    def _renumber_regions(cls, region_ids, parent, find):
        remap = {}
        new_region_ids = [-1] * len(region_ids)

        for fidx, rid in enumerate(region_ids):
            if rid < 0:
                continue

            root = find(rid)
            if root not in remap:
                remap[root] = len(remap)
            new_region_ids[fidx] = remap[root]

        return new_region_ids, len(remap)

    @classmethod
    def _invalidate_candidate_cache(cls, candidate_cache, touched_roots):
        if not touched_roots:
            return

        stale_keys = [
            key for key in candidate_cache
            if key[0] in touched_roots or key[1] in touched_roots
        ]
        for key in stale_keys:
            del candidate_cache[key]

    @classmethod
    def merge(cls, mesh_analysis, material_analysis, seam_plan, settings):
        result = MergeResult()

        is_seam = list(seam_plan.is_seam)
        region_ids = list(seam_plan.region_ids)

        result.is_seam = is_seam
        result.region_ids = region_ids
        result.region_count = seam_plan.region_count
        result.regions_before = seam_plan.region_count
        result.seams_before = len(seam_plan.seam_edges)

        if seam_plan.region_count <= 1:
            result.ok = True
            return result

        try:
            max_cone = float(getattr(settings, "merge_max_cone_angle", 60.0) or 60.0)
        except Exception:
            max_cone = 60.0
        max_cone = max(5.0, min(120.0, max_cone))

        relaxed_cone = min(120.0, max_cone * 1.5)

        min_faces = max(1, int(getattr(settings, "minimum_island_face_count", 3) or 3))
        absorb_micro = bool(getattr(settings, "absorb_micro_islands", True))
        respect_materials = bool(getattr(settings, "separate_by_material", True))

        faces_per_edge = mesh_analysis.faces_per_edge or []
        face_normals = mesh_analysis.face_normals or []
        face_areas = mesh_analysis.face_areas or []

        material_boundary = set()
        if respect_materials:
            material_boundary = set(
                getattr(material_analysis, "material_boundary_edges", set())
            )

        region_faces = {}
        for fidx, rid in enumerate(region_ids):
            if rid >= 0:
                region_faces.setdefault(rid, []).append(fidx)

        region_sums = {}
        for rid, faces in region_faces.items():
            region_sums[rid] = cls._weighted_normal_sum(faces, face_normals, face_areas)

        adjacency = cls._build_adjacency(
            is_seam, region_ids, faces_per_edge, material_boundary
        )

        if not adjacency:
            result.ok = True
            result.info.append("No mergeable region pairs found.")
            return result

        parent = {rid: rid for rid in region_faces}

        def find(rid):
            while parent[rid] != rid:
                parent[rid] = parent[parent[rid]]
                rid = parent[rid]
            return rid

        merges = 0
        micro_absorbed = 0
        dissolved_edges = set()

        candidate_cache = {}

        safety_cap = min(cls._SAFETY_PASS_CAP, len(region_faces) + 1)
        for _ in range(safety_cap):
            candidates = []

            for (ra, rb), _edge_list in adjacency.items():
                root_a = find(ra)
                root_b = find(rb)
                if root_a == root_b:
                    continue

                cache_key = (root_a, root_b) if root_a < root_b else (root_b, root_a)

                if cache_key in candidate_cache:
                    core = candidate_cache[cache_key]
                else:
                    core = cls._evaluate_candidate_core(
                        root_a, root_b, region_faces, region_sums, face_normals,
                        max_cone, relaxed_cone, min_faces, absorb_micro,
                    )
                    candidate_cache[cache_key] = core

                if core is None:
                    continue

                priority, smaller, merged_cone, is_micro = core
                candidates.append(
                    (priority, smaller, merged_cone, root_a, root_b, is_micro)
                )

            if not candidates:
                break

            candidates.sort(key=lambda c: (c[0], c[1], c[2]))

            merged_this_pass, micro_this_pass, touched_roots = cls._apply_merges(
                candidates, parent, region_faces, region_sums, find
            )

            if merged_this_pass == 0:
                break

            merges += merged_this_pass
            micro_absorbed += micro_this_pass

            cls._invalidate_candidate_cache(candidate_cache, touched_roots)

        for (ra, rb), edge_list in adjacency.items():
            if find(ra) == find(rb):
                for eidx in edge_list:
                    if is_seam[eidx]:
                        is_seam[eidx] = False
                        dissolved_edges.add(eidx)

        new_region_ids, new_region_count = cls._renumber_regions(region_ids, parent, find)

        result.is_seam = is_seam
        result.region_ids = new_region_ids
        result.region_count = new_region_count
        result.merges_performed = merges
        result.micro_absorbed = micro_absorbed
        result.ok = True

        if merges:
            result.info.append(
                f"Island merge: {result.regions_before} -> {result.region_count} "
                f"regions ({merges} merges, {micro_absorbed} micro absorbed, "
                f"{len(dissolved_edges)} seams dissolved)."
            )
        else:
            result.info.append(
                f"Island merge: nothing merged at {max_cone:.0f} degrees flatness."
            )

        return result

class RegionSplitter:
    """
    Cuts regions that cannot be flattened, which is the opposite job to the
    merger and the one the angle threshold cannot do.

    A cylinder has no sharp edge anywhere on it. No curvature threshold will
    ever cut one, because lowering the threshold enough to catch its gentle
    curvature shatters every other part of the model first. Yet a cylinder must
    be cut: unwrapping a tube without a seam forces the solver to flatten a
    closed loop, and it gives up. Blender says so out loud — "Unwrap failed to
    solve N of M islands" — and the faces come back with zero UV area.

    The signal is already available: the normal cone of a region. A region whose
    normals span more than roughly a half turn wraps around and is not
    developable, whatever its dihedral angles look like. Such regions get their
    own, much lower threshold applied to their interior edges only, so the rest
    of the model keeps the seams the user asked for.
    """

    # Above this spread a region has wrapped far enough that flattening it
    # must distort badly. 100 degrees is past a quarter turn on each side of the
    # mean normal, which no flat patch reaches.
    DEFAULT_MAX_CONE = 100.0

    # Interior thresholds to try, in order. Each pass cuts more of the region.
    # Stopping at 8 degrees avoids shattering a dense mesh into single faces.
    FALLBACK_THRESHOLDS = (45.0, 30.0, 20.0, 12.0, 8.0)

    @classmethod
    def split(cls, mesh_analysis, seam_plan, settings):
        """
        Adds seams inside regions that are too wrapped to flatten.

        Returns (added_seams, regions_split, notes).
        """
        try:
            max_cone = float(
                getattr(settings, "split_max_cone_angle", cls.DEFAULT_MAX_CONE)
                or cls.DEFAULT_MAX_CONE
            )
        except (TypeError, ValueError):
            max_cone = cls.DEFAULT_MAX_CONE
        max_cone = max(30.0, min(180.0, max_cone))

        is_seam = seam_plan.is_seam
        region_ids = seam_plan.region_ids

        faces_per_edge = mesh_analysis.faces_per_edge or []
        face_normals = mesh_analysis.face_normals or []
        face_areas = mesh_analysis.face_areas or []

        if not region_ids or not faces_per_edge:
            return 0, 0, []

        region_faces = {}
        for fidx, rid in enumerate(region_ids):
            if rid >= 0:
                region_faces.setdefault(rid, []).append(fidx)

        # Interior edges per region: both sides in the same region and not
        # already a seam. Only these may be cut.
        interior = {}
        for eidx, face_list in enumerate(faces_per_edge):
            if eidx >= len(is_seam) or is_seam[eidx] or len(face_list) != 2:
                continue

            f1, f2 = face_list[0], face_list[1]
            if not (0 <= f1 < len(region_ids) and 0 <= f2 < len(region_ids)):
                continue

            rid = region_ids[f1]
            if rid >= 0 and rid == region_ids[f2]:
                interior.setdefault(rid, []).append((eidx, f1, f2))

        added = 0
        split_count = 0
        notes = []

        for rid, faces in region_faces.items():
            if len(faces) < 8:
                # Too small to be a wrapped shell, and splitting it would only
                # make fragments.
                continue

            cone = RegionMerger._cone_half_angle_from_sum(
                RegionMerger._weighted_normal_sum(faces, face_normals, face_areas),
                faces,
                face_normals,
            )

            if cone <= max_cone:
                continue

            edges = interior.get(rid, [])
            if not edges:
                notes.append(
                    f"Region {rid} spans {cone:.0f} degrees but has no interior "
                    "edge left to cut."
                )
                continue

            # Pre-compute each interior edge's dihedral angle once.
            scored = []
            for eidx, f1, f2 in edges:
                if 0 <= f1 < len(face_normals) and 0 <= f2 < len(face_normals):
                    scored.append((
                        angle_between_degrees(face_normals[f1], face_normals[f2]),
                        eidx,
                    ))

            if not scored:
                continue

            region_added = 0
            for threshold in cls.FALLBACK_THRESHOLDS:
                for angle, eidx in scored:
                    if angle >= threshold and not is_seam[eidx]:
                        is_seam[eidx] = True
                        region_added += 1

                if region_added:
                    break

            if not region_added:
                # Nothing bends even slightly: a perfect tube. Cut the single
                # sharpest ring of edges available so the solver has an opening.
                scored.sort(reverse=True)
                for _angle, eidx in scored[: max(1, len(scored) // 20)]:
                    if not is_seam[eidx]:
                        is_seam[eidx] = True
                        region_added += 1

            if region_added:
                added += region_added
                split_count += 1

        if split_count:
            notes.append(
                f"Split {split_count} non-developable regions with {added} extra "
                f"seams (normal cone over {max_cone:.0f} degrees)."
            )

        return added, split_count, notes
