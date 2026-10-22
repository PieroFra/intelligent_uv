# pylint: disable=invalid-name
"""
Intelligent UV Mapping — MESH API HELPERS

Version-tolerant mesh API helpers and shared geometry maths.
"""

import array
import math
from contextlib import contextmanager

import bpy

try:
    import numpy as np
except Exception:  # pragma: no cover - numpy ships with Blender
    np = None


# =============================================================================
# 0. MESH API HELPERS — Version-tolerant attribute access
# =============================================================================

def loop_edge_index(loop):
    """
    Returns the edge index of a mesh loop.

    Blender exposes this as `MeshLoop.edge_index`. Older/alternative builds may
    expose `.edge`. Returns -1 when unavailable.
    """
    idx = getattr(loop, "edge_index", None)
    if idx is None:
        idx = getattr(loop, "edge", None)

    try:
        return int(idx)
    except Exception:
        return -1


def polygon_loop_range(poly):
    """Returns (start, end) loop indices for a polygon, end exclusive."""
    try:
        start = int(getattr(poly, "loop_start", 0) or 0)
    except Exception:
        start = 0

    total = getattr(poly, "loop_total", None)
    if total is None:
        try:
            total = len(poly.vertices)
        except Exception:
            total = 0

    try:
        total = int(total)
    except Exception:
        total = 0

    return start, start + max(0, total)


def loop_uv(uv_layer, loop_index):
    """
    Reads the UV of a loop.

    UV data is stored per loop: `uv_layer.data` is indexed by the LOOP INDEX.
    There is no `MeshLoop.uv_index` attribute.
    """
    try:
        data = uv_layer.data
        if 0 <= loop_index < len(data):
            uv = data[loop_index].uv
            return float(uv[0]), float(uv[1])
    except Exception:
        # A: UV data access differs across versions and layers can be
        # detached mid-operation. The caller treats None as 'no UV here'.
        pass

    return None


def set_loop_uv(uv_layer, loop_index, u, v):
    """Writes the UV of a loop. Returns True on success."""
    try:
        data = uv_layer.data
        if 0 <= loop_index < len(data):
            data[loop_index].uv = (float(u), float(v))
            return True
    except Exception:
        # A: UV data access differs across versions and layers can be
        # detached mid-operation. The caller treats None as 'no UV here'.
        pass

    return False


# =============================================================================
# Bulk mesh reads
#
# One `foreach_get` call replaces one RNA call per element. On a 500k-loop
# mesh the per-element form (uv_layer.data[i].uv, loops[i].vertex_index, ...)
# is the difference between seconds and milliseconds, and several pipeline
# steps walk every loop.
# =============================================================================

def read_all_uvs(uv_layer, loop_count):
    """
    Every loop UV as a flat [u0, v0, u1, v1, ...] buffer, in one RNA call.

    Returns a numpy float32 array when numpy is available, an array.array
    otherwise, or None when the bulk read is not possible.
    """
    if uv_layer is None or loop_count <= 0:
        return None

    data = getattr(uv_layer, "data", None)
    if data is None or not hasattr(data, "foreach_get"):
        return None

    if np is not None:
        try:
            buf = np.empty(loop_count * 2, dtype=np.float32)
            data.foreach_get("uv", buf)
            return buf
        except Exception:
            # A: foreach_get is not exposed for every property on every build;
            # the caller falls back to reading element by element.
            pass

    try:
        buf = array.array('f', [0.0] * (loop_count * 2))
        data.foreach_get("uv", buf)
        return buf
    except Exception:
        return None


def write_all_uvs(uv_layer, flat):
    """
    Writes a flat [u0, v0, ...] buffer back to the layer in one RNA call.

    The buffer length must be exactly 2 * len(uv_layer.data): foreach_set
    refuses anything else, which is what makes this safe against overflows.
    """
    if uv_layer is None or flat is None:
        return False

    data = getattr(uv_layer, "data", None)
    if data is None or not hasattr(data, "foreach_set"):
        return False

    try:
        data.foreach_set("uv", flat)
        return True
    except Exception:
        return False


def bulk_loop_ranges(mesh, face_count):
    """
    (loop_starts, loop_totals) for every polygon, in two RNA calls.

    Returns None when the bulk read is unavailable; callers then fall back to
    polygon_loop_range() per face.
    """
    polygons = getattr(mesh, "polygons", None)
    if polygons is None or face_count <= 0 or not hasattr(polygons, "foreach_get"):
        return None

    try:
        starts = array.array('i', [0] * face_count)
        totals = array.array('i', [0] * face_count)
        polygons.foreach_get("loop_start", starts)
        polygons.foreach_get("loop_total", totals)
        return starts, totals
    except Exception:
        return None


def bulk_loop_attribute(mesh, attr, loop_count):
    """
    An int loop attribute (e.g. "vertex_index", "edge_index") for every loop,
    in one RNA call. Returns None when unavailable.
    """
    loops = getattr(mesh, "loops", None)
    if loops is None or loop_count <= 0 or not hasattr(loops, "foreach_get"):
        return None

    try:
        buf = array.array('i', [0] * loop_count)
        loops.foreach_get(attr, buf)
        return buf
    except Exception:
        return None


def bulk_vertex_coords(mesh, vertex_count):
    """
    Every vertex coordinate as a flat [x0, y0, z0, ...] buffer, in one RNA
    call. numpy float32 when available, array.array otherwise, None on failure.
    """
    vertices = getattr(mesh, "vertices", None)
    if vertices is None or vertex_count <= 0 or not hasattr(vertices, "foreach_get"):
        return None

    if np is not None:
        try:
            buf = np.empty(vertex_count * 3, dtype=np.float32)
            vertices.foreach_get("co", buf)
            return buf
        except Exception:
            # A: foreach_get is not exposed for every property on every build;
            # the caller falls back to reading element by element.
            pass

    try:
        buf = array.array('f', [0.0] * (vertex_count * 3))
        vertices.foreach_get("co", buf)
        return buf
    except Exception:
        return None


def normalize_vector(vec):
    """Unit vector, or None when the input is degenerate."""
    if not vec:
        return None

    x, y, z = float(vec[0]), float(vec[1]), float(vec[2])
    length = math.sqrt(x * x + y * y + z * z)

    if length <= 1e-12:
        return None

    return (x / length, y / length, z / length)


def angle_between_degrees(n1, n2):
    """
    Angle between two vectors, in degrees.

    Shared by the seam planner, the curvature estimator and the region merger,
    so it lives here rather than on any one of them.
    """
    a1 = normalize_vector(n1) or (0.0, 1.0, 0.0)
    a2 = normalize_vector(n2) or (0.0, 1.0, 0.0)

    dot = a1[0] * a2[0] + a1[1] * a2[1] + a1[2] * a2[2]
    return math.degrees(math.acos(max(-1.0, min(1.0, dot))))


@contextmanager
def uv_editor_override():
    """
    Yields True inside a context override pointing at a UV/Image editor.

    Operators like `uv.pack_islands` poll for a UV editor context, so calling
    them from the Text Editor or the 3D View fails without this override.
    Yields False when no suitable editor exists.
    """
    window = None
    area = None
    region = None

    try:
        for win in bpy.context.window_manager.windows:
            screen = getattr(win, "screen", None)
            if not screen:
                continue

            for candidate_area in screen.areas:
                if candidate_area.type != 'IMAGE_EDITOR':
                    continue

                for candidate_region in candidate_area.regions:
                    if candidate_region.type == 'WINDOW':
                        window = win
                        area = candidate_area
                        region = candidate_region
                        break

                if region is not None:
                    break

            if region is not None:
                break
    except Exception:
        window = area = region = None

    if area is not None:
        try:
            with bpy.context.temp_override(window=window, area=area, region=region):
                yield True
            return
        except Exception:
            # A: the context override can fail when no suitable area exists.
            # The caller already knows it may not have a UV editor.
            pass

    yield False
