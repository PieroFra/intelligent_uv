# pylint: disable=invalid-name
"""
Intelligent UV Mapping — SEAM MARKER

Writes real UV seams, plus optional bevel-weight debug marking.
"""

import array

# =============================================================================
# 8. SEAM MARKER — Real UV Seams + Optional Bevel Debug
# =============================================================================

class SeamMarker:
    """
    Marks real UV seams on the mesh (`edge.use_seam`) and, optionally, bevel
    weights as a quick visual debug aid.
    """

    BEVEL_ATTR_NAME = "bevel_weight_edge"

    @classmethod
    def _get_bevel_weight_data(cls, mesh, edge_count):
        """
        Returns an object supporting `data[i].value`, or None.

        Blender 4.x stores edge bevel weight as a generic EDGE attribute.
        """
        try:
            attributes = getattr(mesh, "attributes", None)
            if attributes is not None:
                attr = attributes.get(cls.BEVEL_ATTR_NAME)
                if attr is None:
                    attr = attributes.new(cls.BEVEL_ATTR_NAME, 'FLOAT', 'EDGE')

                if attr is not None and len(attr.data) == edge_count:
                    return attr.data
        except Exception:
            # A: this attribute layout differs between versions; the caller
            # rebuilds the data the slow way when it is absent.
            pass

        return None

    @classmethod
    def mark_real_seams(cls, mesh, is_seam):
        """
        Writes real UV seams. Returns (success: bool, message: str).

        Must be called in Object Mode: edits to `mesh.edges` are not visible
        while the mesh is in Edit Mode.
        """
        if not mesh:
            return False, "Mesh unavailable."

        edges = getattr(mesh, "edges", [])
        count = min(len(is_seam), len(edges))

        try:
            # Bulk write: one RNA call for the whole mesh instead of one per
            # edge, which is the difference between seconds and milliseconds
            # on dense meshes. foreach_set validates the buffer length itself,
            # so a mismatch raises here rather than corrupting memory.
            written_flags = None
            if hasattr(edges, "foreach_set"):
                try:
                    flags = array.array('b', [1 if is_seam[i] else 0 for i in range(count)])
                    edges.foreach_set("use_seam", flags)
                    written_flags = True
                except Exception:
                    written_flags = None

            if written_flags is None:
                for i in range(count):
                    edges[i].use_seam = bool(is_seam[i])

            if hasattr(mesh, "update"):
                mesh.update()

            expected = sum(1 for s in is_seam[:count] if s)

            # Read back: a silent write failure would otherwise look like success.
            readback = None
            if hasattr(edges, "foreach_get"):
                try:
                    readback = array.array('b', [0] * count)
                    edges.foreach_get("use_seam", readback)
                except Exception:
                    readback = None

            if readback is not None:
                written = sum(1 for flag in readback if flag)
            else:
                written = sum(1 for i in range(count) if edges[i].use_seam)

            if expected > 0 and written == 0:
                return False, (
                    f"Seam write failed: {expected} seams were requested but the "
                    "mesh reports none. The edge.use_seam API did not apply."
                )

            if written != expected:
                return True, (
                    f"UV seams marked: {written} edges "
                    f"({expected} requested; pre-existing seams may differ)."
                )

            return True, f"Real UV seams marked on {written} edges."
        except Exception as exc:
            return False, f"Error during real seam marking: {exc}"

    @classmethod
    def mark_bevel_debug(cls, mesh, is_seam):
        """Writes bevel weights from the seam mask. Returns (success, message)."""
        if not mesh:
            return False, "Mesh unavailable."

        edge_count = len(is_seam)
        data = cls._get_bevel_weight_data(mesh, edge_count)

        if data is None:
            return False, (
                "Unable to access the edge bevel weight attribute. "
                "Visual debug marking is disabled."
            )

        try:
            for i in range(edge_count):
                data[i].value = 1.0 if is_seam[i] else 0.0

            if hasattr(mesh, "update"):
                mesh.update()

            marked = sum(1 for s in is_seam if s)
            return True, f"Bevel-weight debug marking applied to {marked} edges."
        except Exception as exc:
            return False, f"Error during bevel debug marking: {exc}"
