# pylint: disable=invalid-name
"""
Intelligent UV Mapping — MATERIAL ANALYZER

Material grouping and material-boundary edge detection.
"""

import array

# =============================================================================
# 5. MATERIAL ANALYZER — Material Distribution Analysis
# =============================================================================

class MaterialAnalysisResult:
    """Result of the material analysis."""

    def __init__(self):
        self.ok = False
        self.errors = []
        self.warnings = []

        self.face_material_group = {}   # face_index -> group_id
        self.material_groups = {}       # group_id -> info
        self.material_boundary_edges = set()
        self.group_count = 0


class MaterialAnalyzer:
    """Analyzes the distribution of materials on the mesh."""

    @staticmethod
    def _slot_key(obj, slot_index):
        try:
            slots = obj.material_slots
            if 0 <= slot_index < len(slots):
                mat = slots[slot_index].material
                return "__EMPTY__" if mat is None else f"MATERIAL:{mat.name}"
        except Exception:
            # A: material slots can be empty or detached mid-edit; the caller
            # treats an unreadable slot as its own group.
            pass

        return "UNKNOWN"

    @classmethod
    def analyze(cls, obj, mesh_analysis=None):
        result = MaterialAnalysisResult()

        if not obj or obj.type != 'MESH':
            result.errors.append("Object is invalid for material analysis.")
            return result

        mesh_data = getattr(obj, "data", None)
        polygons = getattr(mesh_data, "polygons", []) if mesh_data else []

        face_count = len(polygons) if hasattr(polygons, "__len__") else 0
        if face_count == 0:
            result.errors.append("No faces to analyze.")
            return result

        slots = getattr(obj, "material_slots", []) or []
        slot_count = len(slots) if hasattr(slots, "__len__") else 0

        group_to_info = {}
        face_group = {}
        out_of_range = 0

        # Bulk read: one RNA call for every face's material index.
        material_indices = None
        if hasattr(polygons, "foreach_get"):
            try:
                material_indices = array.array('i', [0] * face_count)
                polygons.foreach_get("material_index", material_indices)
            except Exception:
                material_indices = None

        for fidx, poly in enumerate(polygons):
            if material_indices is not None:
                mat_index = int(material_indices[fidx])
            else:
                try:
                    mat_index = int(getattr(poly, "material_index", 0))
                except Exception:
                    mat_index = 0

            if mat_index < 0 or (slot_count > 0 and mat_index >= slot_count):
                out_of_range += 1
                mat_index = 0

            key = cls._slot_key(obj, mat_index)

            if key not in group_to_info:
                group_to_info[key] = {
                    "id": len(group_to_info),
                    "key": key,
                    "slot_index": mat_index,
                    "face_count": 0,
                    "faces": set(),
                }

            info = group_to_info[key]
            face_group[fidx] = info["id"]
            info["face_count"] += 1
            info["faces"].add(fidx)

        if out_of_range:
            result.warnings.append(
                f"{out_of_range} faces had an out-of-range material_index, forced to 0."
            )

        result.face_material_group = face_group
        result.group_count = len(group_to_info)

        for info in group_to_info.values():
            info["face_list"] = sorted(info.pop("faces"))
            result.material_groups[info["id"]] = info

        if slot_count == 0:
            result.warnings.append(
                "No material slots present: using a single synthetic group."
            )

        faces_per_edge = getattr(mesh_analysis, "faces_per_edge", None)

        if not faces_per_edge:
            result.warnings.append(
                "Edge-face connectivity unavailable: material boundaries not calculated."
            )
        else:
            for eidx, face_list in enumerate(faces_per_edge):
                if len(face_list) < 2:
                    continue

                seen_groups = {face_group.get(fidx, -1) for fidx in face_list}
                if len(seen_groups) > 1:
                    result.material_boundary_edges.add(eidx)

        if not result.errors:
            result.ok = True

        return result
