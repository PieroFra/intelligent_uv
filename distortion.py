# pylint: disable=invalid-name
"""
Intelligent UV Mapping — DISTORTION ANALYZER

Output quality metrics: texel density spread and angular distortion.
"""

import math

from .utils import (
    bulk_loop_attribute,
    bulk_loop_ranges,
    bulk_vertex_coords,
    loop_uv,
    polygon_loop_range,
    read_all_uvs,
)


# =============================================================================
# 7c. DISTORTION ANALYZER — Output Quality Metrics
# =============================================================================

class DistortionResult:
    """Quality metrics of a finished UV layout."""

    def __init__(self):
        self.ok = False
        self.warnings = []

        # Texel density: UV area per unit of 3D area, normalized to the mean.
        self.density_min = 0.0
        self.density_max = 0.0
        self.density_mean = 0.0
        self.density_deviation = 0.0

        # Angular distortion, in degrees, per face corner.
        self.angle_error_mean = 0.0
        self.angle_error_max = 0.0

        self.faces_measured = 0
        self.degenerate_faces = 0
        self.overlapping_pairs = 0

    def summary(self):
        return (
            f"Texel density spread {self.density_deviation * 100.0:.1f}% "
            f"(min {self.density_min:.2f}x, max {self.density_max:.2f}x), "
            f"angle error {self.angle_error_mean:.1f} deg mean / "
            f"{self.angle_error_max:.1f} deg max."
        )


class DistortionAnalyzer:
    """
    Measures how faithful the UV layout is to the 3D surface.

    Two independent errors matter and a single number hides one of them:

    - Texel density variation: the ratio of UV area to 3D area per face. A
      layout can be perfectly angle-preserving yet still have one island at
      four times the resolution of another.
    - Angular distortion: the difference between each corner angle in 3D and
      its counterpart in UV space. This is what makes textures visibly shear.

    Densities are reported relative to the mean, so the numbers stay meaningful
    regardless of object scale.
    """

    @staticmethod
    def _corner_angles(points):
        """Interior angles, in degrees, of a polygon given as 2D or 3D points."""
        n = len(points)
        angles = []

        for i in range(n):
            prev_pt = points[(i - 1) % n]
            cur = points[i]
            next_pt = points[(i + 1) % n]

            v1 = [a - b for a, b in zip(prev_pt, cur)]
            v2 = [a - b for a, b in zip(next_pt, cur)]

            len1 = math.sqrt(sum(c * c for c in v1))
            len2 = math.sqrt(sum(c * c for c in v2))

            if len1 <= 1e-12 or len2 <= 1e-12:
                angles.append(None)
                continue

            dot = sum(a * b for a, b in zip(v1, v2)) / (len1 * len2)
            angles.append(math.degrees(math.acos(max(-1.0, min(1.0, dot)))))

        return angles

    @staticmethod
    def _polygon_area_2d(points):
        area2 = 0.0
        n = len(points)
        for i in range(n):
            x1, y1 = points[i]
            x2, y2 = points[(i + 1) % n]
            area2 += x1 * y2 - x2 * y1
        return abs(area2) * 0.5

    @classmethod
    def analyze(cls, mesh, uv_layer, mesh_analysis):
        result = DistortionResult()

        if not mesh or not uv_layer:
            result.warnings.append("Mesh or UV layer unavailable for distortion analysis.")
            return result

        polygons = getattr(mesh, "polygons", [])
        vertices = getattr(mesh, "vertices", [])
        loop_count = len(getattr(mesh, "loops", []))
        face_areas = getattr(mesh_analysis, "face_areas", []) or []

        # Bulk reads: one RNA call per attribute for the whole mesh, instead
        # of one per loop and per vertex.
        uv_flat = read_all_uvs(uv_layer, loop_count)
        ranges = bulk_loop_ranges(mesh, len(polygons))
        loop_vert = bulk_loop_attribute(mesh, "vertex_index", loop_count)
        coords = bulk_vertex_coords(mesh, len(vertices))
        use_bulk = (
            uv_flat is not None and ranges is not None
            and loop_vert is not None and coords is not None
        )

        densities = []
        weights = []
        angle_errors = []
        max_angle_error = 0.0

        for fidx, poly in enumerate(polygons):
            mesh_area = face_areas[fidx] if fidx < len(face_areas) else 0.0
            if mesh_area <= 1e-12:
                result.degenerate_faces += 1
                continue

            if use_bulk:
                start = ranges[0][fidx]
                end = min(start + ranges[1][fidx], loop_count)

                uvs = [
                    (float(uv_flat[i * 2]), float(uv_flat[i * 2 + 1]))
                    for i in range(start, end)
                ]
                verts_3d = []
                for i in range(start, end):
                    vi = int(loop_vert[i]) * 3
                    verts_3d.append((
                        float(coords[vi]),
                        float(coords[vi + 1]),
                        float(coords[vi + 2]),
                    ))
            else:
                start, end = polygon_loop_range(poly)

                uvs = []
                for i in range(start, min(end, loop_count)):
                    uv = loop_uv(uv_layer, i)
                    if uv is not None:
                        uvs.append(uv)

                # Angular error needs the 3D corners in the same order as the UVs.
                try:
                    verts_3d = [tuple(vertices[v].co) for v in poly.vertices]
                except Exception:
                    verts_3d = []

            if len(uvs) < 3:
                result.degenerate_faces += 1
                continue

            uv_area = cls._polygon_area_2d(uvs)
            if uv_area <= 1e-14:
                result.degenerate_faces += 1
                continue

            densities.append(uv_area / mesh_area)
            weights.append(mesh_area)

            if len(verts_3d) == len(uvs):
                angles_3d = cls._corner_angles(verts_3d)
                angles_uv = cls._corner_angles(uvs)

                for a3, a2 in zip(angles_3d, angles_uv):
                    if a3 is None or a2 is None:
                        continue
                    error = abs(a3 - a2)
                    angle_errors.append(error)
                    max_angle_error = max(max_angle_error, error)

            result.faces_measured += 1

        if not densities:
            result.warnings.append("No measurable faces for distortion analysis.")
            return result

        total_weight = sum(weights)
        mean_density = (
            sum(d * w for d, w in zip(densities, weights)) / total_weight
            if total_weight > 0 else sum(densities) / len(densities)
        )

        if mean_density <= 1e-14:
            result.warnings.append("Degenerate UV layout: mean density is zero.")
            return result

        # Report densities relative to the mean: 1.0 means perfectly uniform.
        relative = [d / mean_density for d in densities]

        result.density_min = min(relative)
        result.density_max = max(relative)
        result.density_mean = 1.0

        variance = sum(
            w * (r - 1.0) ** 2 for r, w in zip(relative, weights)
        ) / max(total_weight, 1e-12)
        result.density_deviation = math.sqrt(max(0.0, variance))

        if angle_errors:
            result.angle_error_mean = sum(angle_errors) / len(angle_errors)
            result.angle_error_max = max_angle_error

        if result.density_deviation > 0.35:
            # A handful of degenerate faces can dominate the spread, so name
            # them: "enable normalization" is useless advice when it is already
            # on and the real problem is a few zero-area islands.
            near_zero = sum(1 for r in relative if r < 0.01)
            extreme = sum(1 for r in relative if r > 4.0)

            detail = ""
            if near_zero or extreme:
                detail = (
                    f" {near_zero} faces are near-zero area and {extreme} are "
                    "more than 4x the mean; those outliers drive most of this "
                    "number."
                )

            result.warnings.append(
                f"High texel density variation "
                f"({result.density_deviation * 100.0:.0f}%).{detail}"
            )

        if result.angle_error_mean > 12.0:
            result.warnings.append(
                f"High angular distortion ({result.angle_error_mean:.1f} degrees mean): "
                "consider lowering the curvature threshold for more seams."
            )
        elif result.angle_error_max > 60.0:
            # A low mean with a large maximum is a different problem: the layout
            # is fine overall and a few faces are folded or inverted.
            result.warnings.append(
                f"Angular distortion is low on average ({result.angle_error_mean:.1f} "
                f"degrees) but reaches {result.angle_error_max:.0f} degrees on some "
                "faces: a few faces are likely folded or inverted rather than the "
                "layout being bad."
            )

        result.ok = True
        return result


    @classmethod
    def measure_fill(cls, mesh, uv_layer, island_analysis):
        """
        How much of the UV square the islands actually cover.

        Every other metric here describes distortion — whether the texture is
        stretched. This describes waste: how much of the texture the asset
        never touches. They are independent, and a layout can be perfect on one
        and terrible on the other.

        Two numbers are returned because they answer different questions:

        - `coverage` is island area over the whole unit square, which is what
          decides how much texture resolution the asset actually gets.
        - `efficiency` is island area over the area of the bounding box the
          layout occupies, which separates "packed loosely" from "packed well
          but scaled small". A layout can be 40% coverage and 95% efficient,
          in which case the fix is to scale up, not to repack.

        Returns a dict, or None when there is nothing to measure.
        """
        islands = getattr(island_analysis, "islands", None) or []
        if not islands or uv_layer is None:
            return None

        polygons = getattr(mesh, "polygons", [])
        loop_count = len(getattr(mesh, "loops", []))

        total_uv_area = 0.0
        min_u = min_v = float("inf")
        max_u = max_v = -float("inf")

        for record in islands:
            for fidx in record.get("faces", ()):
                if not (0 <= fidx < len(polygons)):
                    continue

                start, end = polygon_loop_range(polygons[fidx])
                uvs = []
                for i in range(start, min(end, loop_count)):
                    uv = loop_uv(uv_layer, i)
                    if uv is None:
                        continue
                    uvs.append(uv)
                    min_u = min(min_u, uv[0])
                    max_u = max(max_u, uv[0])
                    min_v = min(min_v, uv[1])
                    max_v = max(max_v, uv[1])

                if len(uvs) >= 3:
                    total_uv_area += cls._polygon_area_2d(uvs)

        if min_u == float("inf"):
            return None

        span_u = max(0.0, max_u - min_u)
        span_v = max(0.0, max_v - min_v)
        bbox_area = span_u * span_v

        return {
            "island_area": total_uv_area,
            "coverage": total_uv_area,          # the unit square has area 1
            "efficiency": (
                total_uv_area / bbox_area if bbox_area > 1e-12 else 0.0
            ),
            "bounds": (min_u, min_v, max_u, max_v),
            "island_count": len(islands),
        }

    @classmethod
    def per_island_report(cls, mesh, uv_layer, mesh_analysis, island_analysis,
                          worst=8):
        """
        Per-island density and collapse statistics.

        An aggregate spread figure cannot distinguish "three huge islands are
        broken" from "every island is slightly off", and those need opposite
        fixes: the first is a seam placement problem, the second a packing or
        normalization one. This lists the islands that actually carry the
        collapsed faces.

        Returns a list of dicts sorted worst-first, capped at `worst` entries.
        """
        islands = getattr(island_analysis, "islands", None) or []
        if not islands or not uv_layer:
            return []

        polygons = getattr(mesh, "polygons", [])
        loop_count = len(getattr(mesh, "loops", []))
        face_areas = getattr(mesh_analysis, "face_areas", []) or []

        uv_flat = read_all_uvs(uv_layer, loop_count)
        ranges = bulk_loop_ranges(mesh, len(polygons))
        use_bulk = uv_flat is not None and ranges is not None

        rows = []
        global_uv = 0.0
        global_mesh = 0.0

        for record in islands:
            faces = record.get("faces", [])
            uv_total = 0.0
            mesh_total = 0.0
            collapsed = 0

            for fidx in faces:
                if not (0 <= fidx < len(polygons)):
                    continue

                mesh_area = face_areas[fidx] if fidx < len(face_areas) else 0.0
                if mesh_area <= 1e-12:
                    continue

                if use_bulk:
                    start = ranges[0][fidx]
                    end = min(start + ranges[1][fidx], loop_count)
                    uvs = [
                        (float(uv_flat[i * 2]), float(uv_flat[i * 2 + 1]))
                        for i in range(start, end)
                    ]
                else:
                    start, end = polygon_loop_range(polygons[fidx])
                    uvs = []
                    for i in range(start, min(end, loop_count)):
                        uv = loop_uv(uv_layer, i)
                        if uv is not None:
                            uvs.append(uv)

                uv_area = cls._polygon_area_2d(uvs) if len(uvs) >= 3 else 0.0

                uv_total += uv_area
                mesh_total += mesh_area

                # Relative to this face's own share: a face whose UV area is a
                # vanishing fraction of its 3D area has been squashed flat.
                if uv_area <= 1e-12 or (uv_area / mesh_area) < 1e-6:
                    collapsed += 1

            global_uv += uv_total
            global_mesh += mesh_total

            rows.append({
                "id": record.get("id", -1),
                "faces": len(faces),
                "uv_area": uv_total,
                "mesh_area": mesh_total,
                "collapsed": collapsed,
                "density": (uv_total / mesh_total) if mesh_total > 1e-12 else 0.0,
            })

        mean_density = (global_uv / global_mesh) if global_mesh > 1e-12 else 0.0

        for row in rows:
            row["relative"] = (
                row["density"] / mean_density if mean_density > 1e-12 else 0.0
            )

        # Worst first: most collapsed faces, then furthest from uniform density.
        rows.sort(
            key=lambda r: (-r["collapsed"], -abs(r["relative"] - 1.0))
        )

        return rows[:worst]


    @staticmethod
    def _segments_intersect(p1, p2, p3, p4):
        """True when segment p1-p2 properly crosses segment p3-p4."""
        def orient(a, b, c):
            return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])

        d1 = orient(p3, p4, p1)
        d2 = orient(p3, p4, p2)
        d3 = orient(p1, p2, p3)
        d4 = orient(p1, p2, p4)

        # Strict products: a zero orientation means the segments only touch
        # (shared endpoint, collinear continuation, border contact), and
        # touching is not an overlap — adjacent islands legitimately touch at
        # the margin. Comparing (d > 0) signs misclassifies a zero as a side
        # and reported point contacts as crossings.
        return (d1 * d2 < 0) and (d3 * d4 < 0)

    @classmethod
    def _island_outline_segments(cls, mesh, uv_layer, faces, loop_count):
        """Every face edge of an island, as UV segments (RNA fallback)."""
        segments = []
        polygons = mesh.polygons

        for fidx in faces:
            if not (0 <= fidx < len(polygons)):
                continue

            start, end = polygon_loop_range(polygons[fidx])
            pts = []
            for i in range(start, min(end, loop_count)):
                uv = loop_uv(uv_layer, i)
                if uv is not None:
                    pts.append(uv)

            n = len(pts)
            for i in range(n):
                segments.append((pts[i], pts[(i + 1) % n]))

        return segments

    @classmethod
    def _island_boundary_segments_bulk(cls, faces, ranges, loop_edge, uv_flat,
                                       loop_count):
        """
        Only the island's OUTLINE, as UV segments.

        An edge shared by two faces of the same island is interior: it can
        never cross another island without the outline crossing it too, so
        testing it buys nothing. On a 10k-face island this takes the segment
        count from ~30k down to the few hundred of the actual border — the
        difference between an overlap check that takes minutes and one that
        takes milliseconds.
        """
        starts, totals = ranges
        edge_uses = {}  # edge index -> (count, loop_i, loop_next)

        for fidx in faces:
            if not (0 <= fidx < len(starts)):
                continue

            start = starts[fidx]
            end = min(start + totals[fidx], loop_count)

            for i in range(start, end):
                eidx = int(loop_edge[i])
                if eidx < 0:
                    continue

                nxt = i + 1 if i + 1 < end else start
                entry = edge_uses.get(eidx)
                if entry is None:
                    edge_uses[eidx] = [1, i, nxt]
                else:
                    entry[0] += 1

        segments = []
        for count, i, nxt in edge_uses.values():
            if count != 1:
                continue
            segments.append((
                (float(uv_flat[i * 2]), float(uv_flat[i * 2 + 1])),
                (float(uv_flat[nxt * 2]), float(uv_flat[nxt * 2 + 1])),
            ))

        return segments

    # Hard cap on segment-pair tests per island pair. The grid below makes
    # this almost unreachable; it exists so a pathological layout degrades to
    # "unverified" instead of freezing Blender.
    _MAX_SEGMENT_TESTS_PER_PAIR = 2_000_000

    @classmethod
    def build_segment_index(cls, segments):
        """
        Hashes segments into a uniform grid over their own bounding box.

        Returned rather than built inside the comparison because an island in
        a packed layout takes part in many candidate pairs, and rebuilding its
        index for each one dominated everything else: profiling a 315-island
        layout showed 3.3 million dictionary inserts and five of the eight
        seconds spent here. Built once per island, those inserts happen once.

        Returns (grid, cell) or None when there is nothing to index.
        """
        if not segments:
            return None

        min_x = min(min(p[0], q[0]) for p, q in segments)
        max_x = max(max(p[0], q[0]) for p, q in segments)
        min_y = min(min(p[1], q[1]) for p, q in segments)
        max_y = max(max(p[1], q[1]) for p, q in segments)

        extent = max(max_x - min_x, max_y - min_y)
        cell = max(extent / 32.0, 1e-9)

        grid = {}
        for p, q in segments:
            x0, x1 = (p[0], q[0]) if p[0] <= q[0] else (q[0], p[0])
            y0, y1 = (p[1], q[1]) if p[1] <= q[1] else (q[1], p[1])
            for gx in range(int(x0 // cell), int(x1 // cell) + 1):
                for gy in range(int(y0 // cell), int(y1 // cell) + 1):
                    key = (gx, gy)
                    bucket = grid.get(key)
                    if bucket is None:
                        grid[key] = [(p, q)]
                    else:
                        bucket.append((p, q))

        return grid, cell

    @classmethod
    def _segment_sets_cross(cls, seg_a, seg_b, index_b=None):
        """
        True when any segment of A properly crosses any segment of B.

        `index_b` is B's prebuilt grid. It is optional so the function still
        works standalone, but the caller should pass one: see
        build_segment_index for why.
        """
        if not seg_a or not seg_b:
            return False

        if index_b is None:
            index_b = cls.build_segment_index(seg_b)
            if index_b is None:
                return False

        grid, cell = index_b

        tested = 0

        for p, q in seg_a:
            x0, x1 = (p[0], q[0]) if p[0] <= q[0] else (q[0], p[0])
            y0, y1 = (p[1], q[1]) if p[1] <= q[1] else (q[1], p[1])

            for gx in range(int(x0 // cell), int(x1 // cell) + 1):
                for gy in range(int(y0 // cell), int(y1 // cell) + 1):
                    for r, s in grid.get((gx, gy), ()):
                        # Cheap bbox reject before the exact test.
                        if max(r[0], s[0]) < x0 or min(r[0], s[0]) > x1:
                            continue
                        if max(r[1], s[1]) < y0 or min(r[1], s[1]) > y1:
                            continue

                        tested += 1
                        if cls._segments_intersect(p, q, r, s):
                            return True

            if tested > cls._MAX_SEGMENT_TESTS_PER_PAIR:
                return False

        return False

    @staticmethod
    def _point_in_boundary(point, segments):
        """
        Even-odd ray casting against a set of boundary segments.

        Edge crossing alone misses one containment case: an island lying
        entirely inside another's outline without the borders touching.
        """
        x, y = point
        crossings = 0

        for p, q in segments:
            if (p[1] > y) == (q[1] > y):
                continue
            x_hit = p[0] + (y - p[1]) * (q[0] - p[0]) / (q[1] - p[1])
            if x_hit > x:
                crossings += 1

        return (crossings % 2) == 1

    @classmethod
    def find_real_overlaps(cls, mesh, uv_layer, island_analysis, max_pairs=40000):
        """
        Island pairs whose UV geometry actually crosses.

        The bounding-box check is only a filter: two islands can have
        intersecting boxes and never touch, which is the normal case for any
        non-rectangular shell. Reporting those as overlaps buries the real ones
        — a run reported 433 intersecting boxes, of which most were harmless.

        Boxes are still used first, because they are cheap and reject almost
        every pair; only the survivors get a segment intersection test, run on
        the island OUTLINES (interior edges cannot cross another island) with
        a uniform grid broad phase. A containment check covers the case of one
        island sitting entirely inside another's outline.

        Returns (overlapping_pairs, checked_pairs, gave_up).
        """
        candidates = cls.find_overlaps(island_analysis)
        if not candidates:
            return [], 0, False

        # A pathological layout can produce a huge candidate set; degrade to the
        # box result rather than freezing Blender.
        if len(candidates) > max_pairs:
            return candidates, 0, True

        islands = {r["id"]: r for r in (island_analysis.islands or [])}
        loop_count = len(getattr(mesh, "loops", []))
        face_count = len(getattr(mesh, "polygons", []))

        uv_flat = read_all_uvs(uv_layer, loop_count)
        ranges = bulk_loop_ranges(mesh, face_count)
        loop_edge = bulk_loop_attribute(mesh, "edge_index", loop_count)
        use_bulk = (
            uv_flat is not None and ranges is not None and loop_edge is not None
        )

        cache = {}

        def segments_for(island_id):
            if island_id not in cache:
                record = islands.get(island_id)
                faces = record.get("faces", []) if record else []
                if not record:
                    cache[island_id] = []
                elif use_bulk:
                    cache[island_id] = cls._island_boundary_segments_bulk(
                        faces, ranges, loop_edge, uv_flat, loop_count
                    )
                else:
                    cache[island_id] = cls._island_outline_segments(
                        mesh, uv_layer, faces, loop_count
                    )
            return cache[island_id]

        # The grid is cached beside the segments: an island that appears in
        # twenty candidate pairs is indexed once instead of twenty times.
        index_cache = {}

        def index_for(island_id):
            if island_id not in index_cache:
                index_cache[island_id] = cls.build_segment_index(
                    segments_for(island_id)
                )
            return index_cache[island_id]

        real = []
        for id_a, id_b in candidates:
            rec_a = islands.get(id_a)
            rec_b = islands.get(id_b)

            seg_a = segments_for(id_a)
            seg_b = segments_for(id_b)

            # Two outlines can only cross inside the rectangle their bounding
            # boxes share. On a packed layout that strip is a sliver, so most
            # of A's segments are discarded by four comparisons each — cheaper
            # than the grid lookups they would otherwise cost.
            if rec_a is not None and rec_b is not None:
                overlap_min_u = max(rec_a["bbox_min_u"], rec_b["bbox_min_u"])
                overlap_max_u = min(rec_a["bbox_max_u"], rec_b["bbox_max_u"])
                overlap_min_v = max(rec_a["bbox_min_v"], rec_b["bbox_min_v"])
                overlap_max_v = min(rec_a["bbox_max_v"], rec_b["bbox_max_v"])

                trimmed = [
                    (p, q) for p, q in seg_a
                    if not (
                        (p[0] if p[0] < q[0] else q[0]) > overlap_max_u
                        or (q[0] if p[0] < q[0] else p[0]) < overlap_min_u
                        or (p[1] if p[1] < q[1] else q[1]) > overlap_max_v
                        or (q[1] if p[1] < q[1] else p[1]) < overlap_min_v
                    )
                ]

                # Only the cross test may use the trimmed list. Containment,
                # below, asks whether a point of A lies inside B, and a trimmed
                # A could have lost exactly the point it needs.
                trimmed_a = trimmed
            else:
                trimmed_a = seg_a

            if trimmed_a and cls._segment_sets_cross(
                trimmed_a, seg_b, index_for(id_b)
            ):
                real.append((id_a, id_b))
                continue

            # No crossing border: one island may still sit entirely inside the
            # other's outline, which only the bbox filter brought here.
            if not rec_a or not rec_b or not seg_a or not seg_b:
                continue

            a_inside_b_box = (
                rec_b["bbox_min_u"] <= rec_a["bbox_min_u"]
                and rec_a["bbox_max_u"] <= rec_b["bbox_max_u"]
                and rec_b["bbox_min_v"] <= rec_a["bbox_min_v"]
                and rec_a["bbox_max_v"] <= rec_b["bbox_max_v"]
            )
            b_inside_a_box = (
                rec_a["bbox_min_u"] <= rec_b["bbox_min_u"]
                and rec_b["bbox_max_u"] <= rec_a["bbox_max_u"]
                and rec_a["bbox_min_v"] <= rec_b["bbox_min_v"]
                and rec_b["bbox_max_v"] <= rec_a["bbox_max_v"]
            )

            if a_inside_b_box and cls._point_in_boundary(seg_a[0][0], seg_b):
                real.append((id_a, id_b))
            elif b_inside_a_box and cls._point_in_boundary(seg_b[0][0], seg_a):
                real.append((id_a, id_b))

        return real, len(candidates), False

    @staticmethod
    def find_overlaps(island_analysis, tolerance=1e-6):
        """
        Counts island bounding-box overlaps.

        A bounding-box test cannot prove two islands overlap (their boxes may
        intersect while the shells do not), so this is reported as a suspicion,
        not a verdict. It is fast and catches the failures that matter: a packer
        that silently gave up and stacked shells on top of each other.
        """
        islands = getattr(island_analysis, "islands", []) or []
        pairs = []

        boxes = [
            (
                r["id"],
                r["bbox_min_u"], r["bbox_max_u"],
                r["bbox_min_v"], r["bbox_max_v"],
            )
            for r in islands
            if r.get("uv_area", 0.0) > 1e-9
        ]

        for i in range(len(boxes)):
            id_a, min_ua, max_ua, min_va, max_va = boxes[i]
            for j in range(i + 1, len(boxes)):
                id_b, min_ub, max_ub, min_vb, max_vb = boxes[j]

                if (min_ua < max_ub - tolerance and min_ub < max_ua - tolerance
                        and min_va < max_vb - tolerance and min_vb < max_va - tolerance):
                    pairs.append((id_a, id_b))

        return pairs
