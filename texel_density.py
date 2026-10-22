# pylint: disable=invalid-name
"""
Intelligent UV Mapping — TEXEL DENSITY NORMALIZER

Texel density normalization across islands.
"""

import math

from .uv_executor import MinimalUVExecutor
from .utils import (
    bulk_loop_ranges,
    loop_uv,
    polygon_loop_range,
    read_all_uvs,
    set_loop_uv,
    write_all_uvs,
)


# =============================================================================
# 11. TEXEL DENSITY NORMALIZER — Step 7
# =============================================================================

class TexelDensityNormalizer:
    """
    Normalizes texel density across UV islands using:
    - IslandExtractor data (UV area per island)
    - MeshAnalyzer face areas (real 3D area per face)

    Applied before the final packing, so the packer only repositions islands.
    """

    @staticmethod
    def _island_mesh_area(island_record, mesh_analysis):
        face_areas = getattr(mesh_analysis, "face_areas", None)
        if not face_areas:
            return 0.0

        total = 0.0
        for fidx in island_record.get("faces", []):
            try:
                fidx = int(fidx)
                if 0 <= fidx < len(face_areas):
                    total += float(face_areas[fidx])
            except Exception:
                continue

        return max(0.0, total)

    @classmethod
    def normalize(cls, obj, island_analysis, mesh_analysis, settings=None):
        """
        Scales each island so texel density is uniform. Must run in Object Mode.

        Returns a dict: {"ok", "message", "normalized_islands"}.
        """
        if not obj or obj.type != 'MESH':
            return {"ok": False, "message": "Invalid object.", "normalized_islands": 0}

        if not island_analysis or not getattr(island_analysis, "ok", False):
            return {
                "ok": False,
                "message": "Island analysis unavailable or invalid.",
                "normalized_islands": 0,
            }

        mesh = obj.data
        uv_name = str(getattr(settings, "uv_layer_name", "SmartUV") or "SmartUV") if settings else "SmartUV"
        uv_layer = MinimalUVExecutor.get_uv_layer(mesh, uv_name)

        if not uv_layer:
            return {
                "ok": False,
                "message": f"No UV layer found for normalization ('{uv_name}').",
                "normalized_islands": 0,
            }

        islands = island_analysis.islands or []
        if not islands:
            return {"ok": True, "message": "No islands to normalize.", "normalized_islands": 0}

        total_uv_area = 0.0
        total_mesh_area = 0.0
        island_areas = []

        for record in islands:
            try:
                uv_area = max(0.0, float(record.get("uv_area", 0.0) or 0.0))
            except Exception:
                uv_area = 0.0

            mesh_area = cls._island_mesh_area(record, mesh_analysis)

            total_uv_area += uv_area
            total_mesh_area += mesh_area
            island_areas.append((record, uv_area, mesh_area))

        if total_uv_area <= 1e-8 or total_mesh_area <= 1e-8:
            return {
                "ok": True,
                "message": "Texel density normalization skipped (zero UV or mesh area).",
                "normalized_islands": 0,
            }

        # Uniform target density, in UV units^2 per world unit^2.
        target_density = total_uv_area / total_mesh_area

        polygons = mesh.polygons
        loop_count = len(mesh.loops)
        normalized_count = 0

        # Bulk read: the whole layer is loaded once, scaled in memory and
        # written back once, instead of two RNA calls per loop.
        uv_flat = read_all_uvs(uv_layer, loop_count)
        ranges = bulk_loop_ranges(mesh, len(polygons))
        use_bulk = uv_flat is not None and ranges is not None

        for record, uv_area, mesh_area in island_areas:
            if uv_area <= 1e-8 or mesh_area <= 1e-8:
                continue

            desired_uv_area = target_density * mesh_area
            scale = math.sqrt(desired_uv_area / uv_area)

            # Clamp to avoid destructive scaling on degenerate islands.
            scale = max(0.05, min(20.0, scale))

            if abs(scale - 1.0) < 1e-4:
                continue

            centroid_u = float(record.get("centroid_u", 0.0) or 0.0)
            centroid_v = float(record.get("centroid_v", 0.0) or 0.0)

            try:
                for fidx in record.get("faces", []):
                    fidx = int(fidx)
                    if not (0 <= fidx < len(polygons)):
                        continue

                    if use_bulk:
                        start = ranges[0][fidx]
                        end = min(start + ranges[1][fidx], loop_count)
                        for i in range(start, end):
                            u = float(uv_flat[i * 2])
                            v = float(uv_flat[i * 2 + 1])
                            uv_flat[i * 2] = centroid_u + (u - centroid_u) * scale
                            uv_flat[i * 2 + 1] = centroid_v + (v - centroid_v) * scale
                    else:
                        start, end = polygon_loop_range(polygons[fidx])
                        for i in range(start, min(end, loop_count)):
                            uv = loop_uv(uv_layer, i)
                            if uv is None:
                                continue

                            u, v = uv
                            set_loop_uv(
                                uv_layer, i,
                                centroid_u + (u - centroid_u) * scale,
                                centroid_v + (v - centroid_v) * scale,
                            )

                normalized_count += 1
            except Exception as exc:
                return {
                    "ok": False,
                    "message": (
                        f"Normalization failed on island {record.get('id', '?')}: {exc}"
                    ),
                    "normalized_islands": normalized_count,
                }

        if use_bulk and normalized_count:
            if not write_all_uvs(uv_layer, uv_flat):
                return {
                    "ok": False,
                    "message": "Normalization failed: bulk UV write refused.",
                    "normalized_islands": 0,
                }

        if hasattr(mesh, "update"):
            try:
                mesh.update()
            except Exception:
                # A: mesh.update() is not required on every Blender version and
                # refuses in Edit Mode, where the edit mesh is authoritative anyway.
                pass

        return {
            "ok": True,
            "message": f"Texel density normalized on {normalized_count} islands.",
            "normalized_islands": normalized_count,
        }
