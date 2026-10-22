# pylint: disable=invalid-name
"""
Intelligent UV Mapping — ISLAND EXTRACTOR

Extracts and measures the final UV islands.
"""

from .utils import (
    bulk_loop_attribute,
    bulk_loop_ranges,
    loop_edge_index,
    loop_uv,
    polygon_loop_range,
    read_all_uvs,
)
from .uv_executor import MinimalUVExecutor


# =============================================================================
# 10. ISLAND EXTRACTOR — UV Island Extraction / Analysis
# =============================================================================

class IslandAnalysisResult:
    """Result of the UV island analysis."""

    def __init__(self):
        self.ok = False
        self.errors = []
        self.warnings = []
        self.info = []

        self.islands = []          # list of per-island dictionaries
        self.face_island_id = {}   # face index -> island id
        self.island_count = 0
        self.total_uv_area = 0.0


class IslandExtractor:
    """
    Extracts and analyzes the final UV islands.

    Faces are grouped by the region ids produced by the seam planner when they
    are available (they match the unwrap, since the native engine now honours
    the marked seams); otherwise topological connected components are used.

    Per-island output:
    {
        "id", "faces", "face_count", "uv_area",
        "centroid_u", "centroid_v",
        "bbox_min_u", "bbox_max_u", "bbox_min_v", "bbox_max_v",
        "material_group_id", "primary_material_group_id",
    }
    """

    @staticmethod
    def _face_neighbors_from_mesh(mesh):
        """Builds face -> faces adjacency from loops/edges."""
        polygons = mesh.polygons
        loops = mesh.loops
        face_count = len(polygons)
        loop_count = len(loops)
        neighbors = [set() for _ in range(face_count)]
        faces_per_edge = {}

        # Bulk read: one RNA call for every loop's edge index.
        loop_edge = bulk_loop_attribute(mesh, "edge_index", loop_count)
        ranges = bulk_loop_ranges(mesh, face_count)

        if loop_edge is not None and ranges is not None:
            starts, totals = ranges
            for fidx in range(face_count):
                start = starts[fidx]
                end = min(start + totals[fidx], loop_count)
                for i in range(start, end):
                    eidx = int(loop_edge[i])
                    if eidx >= 0:
                        faces_per_edge.setdefault(eidx, []).append(fidx)
        else:
            for poly in polygons:
                start, end = polygon_loop_range(poly)
                for i in range(start, min(end, loop_count)):
                    eidx = loop_edge_index(loops[i])
                    if eidx >= 0:
                        faces_per_edge.setdefault(eidx, []).append(poly.index)

        for face_list in faces_per_edge.values():
            uniq = list(dict.fromkeys(face_list))
            n = len(uniq)
            if n < 2:
                continue

            for i in range(n):
                for j in range(i + 1, n):
                    neighbors[uniq[i]].add(uniq[j])
                    neighbors[uniq[j]].add(uniq[i])

        return neighbors

    @staticmethod
    def _uv_area_and_stats(mesh, uv_layer, face_indices, uv_flat=None, ranges=None):
        """Computes UV area (shoelace), centroid and bounding box."""
        total_area = 0.0
        sum_u = sum_v = 0.0
        count = 0

        min_u = min_v = float("inf")
        max_u = max_v = -float("inf")

        polygons = mesh.polygons
        loop_count = len(mesh.loops)

        for fidx in face_indices:
            if not (0 <= fidx < len(polygons)):
                continue

            if uv_flat is not None and ranges is not None:
                start = ranges[0][fidx]
                end = min(start + ranges[1][fidx], loop_count)
                coords = [
                    (float(uv_flat[i * 2]), float(uv_flat[i * 2 + 1]))
                    for i in range(start, end)
                ]
            else:
                start, end = polygon_loop_range(polygons[fidx])
                coords = []

                for i in range(start, min(end, loop_count)):
                    uv = loop_uv(uv_layer, i)
                    if uv is not None:
                        coords.append(uv)

            n = len(coords)
            if n >= 3:
                # Shoelace, absolute value for inconsistent winding.
                area2 = 0.0
                for i in range(n):
                    u1, v1 = coords[i]
                    u2, v2 = coords[(i + 1) % n]
                    area2 += (u1 * v2 - u2 * v1)
                total_area += abs(area2) * 0.5

            for u, v in coords:
                sum_u += u
                sum_v += v
                count += 1

                min_u = min(min_u, u)
                max_u = max(max_u, u)
                min_v = min(min_v, v)
                max_v = max(max_v, v)

        if count == 0:
            return {
                "uv_area": 0.0,
                "centroid_u": 0.0, "centroid_v": 0.0,
                "bbox_min_u": 0.0, "bbox_max_u": 0.0,
                "bbox_min_v": 0.0, "bbox_max_v": 0.0,
            }

        return {
            "uv_area": total_area,
            "centroid_u": sum_u / float(count),
            "centroid_v": sum_v / float(count),
            "bbox_min_u": min_u, "bbox_max_u": max_u,
            "bbox_min_v": min_v, "bbox_max_v": max_v,
        }

    @classmethod
    def analyze(cls, obj, settings=None, material_analysis=None, region_ids=None):
        result = IslandAnalysisResult()

        if not obj or obj.type != 'MESH':
            result.errors.append("Object is invalid for UV island analysis.")
            return result

        mesh = obj.data
        polygons = getattr(mesh, "polygons", [])
        face_count = len(polygons) if hasattr(polygons, "__len__") else 0

        if face_count == 0:
            result.errors.append("The mesh has no faces.")
            return result

        uv_name = str(getattr(settings, "uv_layer_name", "SmartUV") or "SmartUV") if settings else "SmartUV"
        uv_layer = MinimalUVExecutor.get_uv_layer(mesh, uv_name)

        if not uv_layer:
            result.errors.append(
                f"No UV layer found (looking for '{uv_name}'). Run an unwrap first."
            )
            return result

        # Region ids from the planner, or recomputed connected components.
        if region_ids is None or len(region_ids) != face_count:
            neighbors = cls._face_neighbors_from_mesh(mesh)
            component_ids = [-1] * face_count
            next_id = 0

            for start in range(face_count):
                if component_ids[start] != -1:
                    continue

                cid = next_id
                next_id += 1

                stack = [start]
                component_ids[start] = cid

                while stack:
                    fidx = stack.pop()
                    for nb in neighbors[fidx]:
                        if component_ids[nb] == -1:
                            component_ids[nb] = cid
                            stack.append(nb)

            region_ids = component_ids

        faces_by_region = {}
        for fidx, rid in enumerate(region_ids):
            rid = -1 if rid is None or rid < 0 else rid
            faces_by_region.setdefault(rid, []).append(fidx)

        # Bulk reads shared by every island: one RNA call for the whole layer
        # instead of one per loop per island.
        loop_count = len(getattr(mesh, "loops", []))
        uv_flat = read_all_uvs(uv_layer, loop_count)
        ranges = bulk_loop_ranges(mesh, face_count)

        # Sort regions by UV area so island 0 is never a tiny fragment.
        region_stats = {}
        for rid, faces in faces_by_region.items():
            region_stats[rid] = cls._uv_area_and_stats(
                mesh, uv_layer, faces, uv_flat=uv_flat, ranges=ranges
            )

        sorted_regions = sorted(
            faces_by_region.keys(),
            key=lambda rid: -region_stats[rid]["uv_area"],
        )

        face_island_id = {}
        island_records = []

        for new_id, rid in enumerate(sorted_regions):
            faces = faces_by_region.get(rid, [])
            if not faces:
                continue

            stats = region_stats[rid]

            material_group_id = -1
            primary_material_group_id = -1

            face_material_group = getattr(material_analysis, "face_material_group", None)
            if face_material_group:
                group_counts = {}
                for fidx in faces:
                    gid = int(face_material_group.get(fidx, -1))
                    if gid >= 0:
                        group_counts[gid] = group_counts.get(gid, 0) + 1

                if group_counts:
                    primary_material_group_id, dominant_count = max(
                        group_counts.items(), key=lambda kv: (kv[1], -kv[0])
                    )
                    if dominant_count >= max(1, int(len(faces) * 0.75)):
                        material_group_id = primary_material_group_id

            island_records.append({
                "id": new_id,
                "faces": sorted(faces),
                "face_count": len(faces),
                "uv_area": stats["uv_area"],
                "centroid_u": stats["centroid_u"],
                "centroid_v": stats["centroid_v"],
                "bbox_min_u": stats["bbox_min_u"],
                "bbox_max_u": stats["bbox_max_u"],
                "bbox_min_v": stats["bbox_min_v"],
                "bbox_max_v": stats["bbox_max_v"],
                "material_group_id": material_group_id,
                "primary_material_group_id": primary_material_group_id,
            })

            for fidx in faces:
                face_island_id[fidx] = new_id

        result.islands = island_records
        result.face_island_id = face_island_id
        result.island_count = len(island_records)
        result.total_uv_area = sum(r["uv_area"] for r in island_records)

        if result.island_count == 0:
            result.warnings.append("No valid UV islands detected.")
        else:
            result.info.append(
                f"UV islands: {result.island_count}, "
                f"total UV area {result.total_uv_area:.6f}."
            )

        zero_area = [r for r in island_records if r["uv_area"] <= 1e-8]
        if zero_area:
            result.warnings.append(
                f"Detected {len(zero_area)} islands with near-zero UV area."
            )

        if not result.errors:
            result.ok = True

        return result
