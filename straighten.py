# pylint: disable=invalid-name
"""
Intelligent UV Mapping — QUAD GRID STRAIGHTENER

Re-lays all-quad islands onto a planar integer grid in UV space.

For every island that is a detectable quad grid (BFS assignment of integer
cell coordinates with consistent corner orientation across shared interior
edges), the island's loops are rewritten to planar grid UVs. The cell aspect
ratio comes from the mean 3D edge lengths along each grid axis, so the layout
keeps the real-world proportions of the mesh instead of squashing to square
cells. The result is then uniformly scaled so the island's total UV area (and
therefore its texel density) matches the original layout, and translated back
onto the original island bounding box.

Islands that are not clean quad grids (non-quad faces, coordinate conflicts,
twisted topology, non-manifold shared edges) are left untouched.
"""

import math

try:
    import numpy as np
except Exception:  # pragma: no cover - numpy ships with Blender
    np = None

from .utils import (
    loop_edge_index,
    loop_uv,
    polygon_loop_range,
    set_loop_uv,
)


# =============================================================================
# RESULT
# =============================================================================

class StraightenResult:
    """Outcome of a straighten pass over an island analysis."""

    def __init__(self):
        self.ok = False
        self.straightened_count = 0
        self.skipped_count = 0
        self.warnings = []
        self.info = []


# =============================================================================
# GRID ORIENTATION HELPERS
#
# A quad's four loops (slots 0..3, in winding order) map to the corners of its
# grid cell. The mapping is fixed by an origin slot and a flip flag; the two
# tables below are the corner offsets read starting from the origin slot.
# =============================================================================

_CORNER_OFFSETS = ((0, 0), (1, 0), (1, 1), (0, 1))
_CORNER_OFFSETS_FLIPPED = ((0, 0), (0, 1), (1, 1), (1, 0))


def _slot_offsets(origin, flip):
    """Per-slot cell-corner offsets for a quad with the given orientation."""
    base = _CORNER_OFFSETS_FLIPPED if flip else _CORNER_OFFSETS
    return tuple(base[(slot - origin) % 4] for slot in range(4))


# =============================================================================
# PER-ISLAND GRID DETECTION
# =============================================================================

def _build_quad_records(mesh, faces):
    """
    Slot/vertex tables for the island's quads, or None when any face is not a
    clean quad (wrong corner count or repeated vertices).
    """
    polygons = mesh.polygons
    records = {}

    for fidx in faces:
        if not (0 <= fidx < len(polygons)):
            return None

        poly = polygons[fidx]
        verts = tuple(int(v) for v in poly.vertices)
        if len(verts) != 4 or len(set(verts)) != 4:
            return None

        start, end = polygon_loop_range(poly)
        if end - start != 4:
            return None

        records[fidx] = {
            "verts": verts,
            "slot_of": {v: s for s, v in enumerate(verts)},
            "loop_start": start,
        }

    return records


def _build_interior_adjacency(records):
    """
    Interior edge adjacency for the island.

    Returns (interior, ok). `interior` maps face -> list of
    (neighbor_face, own_slot, neighbor_slot); the shared edge runs
    (own_slot -> own_slot+1) on this face and (neighbor_slot -> neighbor_slot+1)
    on the neighbor, hence in opposite vertex directions. ok is False when an
    edge is shared by more than two island faces (non-manifold) or a quad
    carries more than four interior edges.
    """
    edge_occurrences = {}
    for fidx, rec in records.items():
        verts = rec["verts"]
        for slot in range(4):
            v0 = verts[slot]
            v1 = verts[(slot + 1) % 4]
            key = (v0, v1) if v0 < v1 else (v1, v0)
            edge_occurrences.setdefault(key, []).append((fidx, slot))

    interior = {fidx: [] for fidx in records}
    for occurrences in edge_occurrences.values():
        if len(occurrences) > 2:
            return None, False
        if len(occurrences) != 2:
            continue

        (fa, sa), (fb, sb) = occurrences
        interior[fa].append((fb, sa, sb))
        interior[fb].append((fa, sb, sa))

    for links in interior.values():
        if len(links) > 4:
            return None, False

    return interior, True


def _assign_grid(records, interior):
    """
    BFS assignment of integer cell coordinates from a seed quad.

    Returns {face: (i, j, origin, flip)} or None on any conflict (orientation
    mismatch, duplicate cell, or faces unreachable through interior edges).
    """
    assigned = {}
    cells = {}

    seed = next(iter(records))
    assigned[seed] = (0, 0, 0, 0)
    cells[(0, 0)] = seed
    queue = [seed]

    while queue:
        fa = queue.pop()
        ia, ja, origin_a, flip_a = assigned[fa]
        off_a = _slot_offsets(origin_a, flip_a)

        for fb, slot_a, slot_b in interior[fa]:
            # Corner of A at slot_a / slot_a+1, in absolute grid coordinates.
            ga0 = (ia + off_a[slot_a][0], ja + off_a[slot_a][1])
            ga1 = (
                ia + off_a[(slot_a + 1) % 4][0],
                ja + off_a[(slot_a + 1) % 4][1],
            )
            # The shared edge is traversed in the opposite direction on B.
            gb0 = ga1
            gb1 = ga0

            if fb in assigned:
                ib, jb, origin_b, flip_b = assigned[fb]
                off_b = _slot_offsets(origin_b, flip_b)
                got0 = (ib + off_b[slot_b][0], jb + off_b[slot_b][1])
                got1 = (
                    ib + off_b[(slot_b + 1) % 4][0],
                    jb + off_b[(slot_b + 1) % 4][1],
                )
                if got0 != gb0 or got1 != gb1:
                    return None
                continue

            # Find the single orientation of B matching both pinned corners.
            matches = []
            for origin in range(4):
                for flip in (0, 1):
                    off = _slot_offsets(origin, flip)
                    cell = (gb0[0] - off[slot_b][0], gb0[1] - off[slot_b][1])
                    if (cell[0] + off[(slot_b + 1) % 4][0],
                            cell[1] + off[(slot_b + 1) % 4][1]) == gb1:
                        matches.append((cell, origin, flip))

            # Two orientations can satisfy the pinned corners: the true one
            # and its mirror across the shared edge, which lands on the
            # referrer's own cell. The unoccupied cell disambiguates.
            free = [m for m in matches if m[0] not in cells]
            if len(free) != 1:
                return None

            cell, origin, flip = free[0]
            cells[cell] = fb

            assigned[fb] = (cell[0], cell[1], origin, flip)
            cells[cell] = fb
            queue.append(fb)

    if len(assigned) != len(records):
        return None

    return assigned


def _mean_axis_edge_lengths(mesh, records, assigned):
    """
    Mean 3D edge length along each grid axis, from the quad sides themselves.

    Returns (mean_u, mean_v) or None when an axis has no measurable edge or a
    degenerate (near-zero) mean.
    """
    vertices = mesh.vertices
    u_lengths = []
    v_lengths = []

    for fidx, (i, j, origin, flip) in assigned.items():
        verts = records[fidx]["verts"]
        off = _slot_offsets(origin, flip)

        for slot in range(4):
            d_i = off[(slot + 1) % 4][0] - off[slot][0]
            d_j = off[(slot + 1) % 4][1] - off[slot][1]
            if d_i == 0 and d_j == 0:
                continue

            va = vertices[verts[slot]].co
            vb = vertices[verts[(slot + 1) % 4]].co
            length = (va - vb).length

            if d_j == 0:
                u_lengths.append(length)
            else:
                v_lengths.append(length)

    if not u_lengths or not v_lengths:
        return None

    if np is not None:
        mean_u = float(np.mean(u_lengths))
        mean_v = float(np.mean(v_lengths))
    else:
        mean_u = sum(u_lengths) / len(u_lengths)
        mean_v = sum(v_lengths) / len(v_lengths)

    if mean_u <= 1e-12 or mean_v <= 1e-12:
        return None

    return mean_u, mean_v


def _original_uv_frame(mesh, uv_layer, records):
    """
    Current UV area and bounding-box minimum of the island.

    Returns (uv_area, min_u, min_v) or None when any loop UV is unreadable.
    """
    polygons = mesh.polygons
    area = 0.0
    min_u = min_v = float("inf")

    for fidx, rec in records.items():
        start = rec["loop_start"]
        poly_uvs = []
        for slot in range(4):
            uv = loop_uv(uv_layer, start + slot)
            if uv is None:
                return None
            poly_uvs.append(uv)
            min_u = min(min_u, uv[0])
            min_v = min(min_v, uv[1])

        shoelace = 0.0
        for k in range(4):
            u0, v0 = poly_uvs[k]
            u1, v1 = poly_uvs[(k + 1) % 4]
            shoelace += u0 * v1 - u1 * v0
        area += abs(shoelace) * 0.5

    return area, min_u, min_v


def _straighten_island(mesh, uv_layer, faces):
    """
    Straightens one island. Returns an error string, or None on success (UVs
    already written).
    """
    records = _build_quad_records(mesh, faces)
    if records is None:
        return "island is not all-quads"

    interior, ok = _build_interior_adjacency(records)
    if not ok:
        return "non-manifold or over-connected interior edges"

    assigned = _assign_grid(records, interior)
    if assigned is None:
        return "quad grid detection failed (orientation conflict or not edge-connected)"

    axis_lengths = _mean_axis_edge_lengths(mesh, records, assigned)
    if axis_lengths is None:
        return "degenerate grid axes"

    mean_u, mean_v = axis_lengths

    frame = _original_uv_frame(mesh, uv_layer, records)
    if frame is None:
        return "unreadable original UVs"

    old_area, old_min_u, old_min_v = frame
    if old_area <= 1e-12:
        return "zero-area original UV layout"

    i_vals = [cell[0] for cell in assigned.values()]
    j_vals = [cell[1] for cell in assigned.values()]
    grid_w = (max(i_vals) - min(i_vals) + 1) * mean_u
    grid_h = (max(j_vals) - min(j_vals) + 1) * mean_v
    if grid_w <= 1e-12 or grid_h <= 1e-12:
        return "degenerate grid extent"

    # Uniform scale: the straightened island keeps the original UV area, so
    # the average texel density is preserved (no squash: aspect is carried by
    # mean_u / mean_v, the scale stays uniform).
    scale = math.sqrt(old_area / (grid_w * grid_h))
    cell_u = mean_u * scale
    cell_v = mean_v * scale
    if not (math.isfinite(cell_u) and math.isfinite(cell_v)):
        return "non-finite grid scale"

    i_min = min(i_vals)
    j_min = min(j_vals)

    for fidx, (i, j, origin, flip) in assigned.items():
        rec = records[fidx]
        off = _slot_offsets(origin, flip)
        start = rec["loop_start"]
        for slot in range(4):
            u = old_min_u + (i - i_min + off[slot][0]) * cell_u
            v = old_min_v + (j - j_min + off[slot][1]) * cell_v
            if not set_loop_uv(uv_layer, start + slot, u, v):
                return "failed to write UVs"

    return None


# =============================================================================
# ENTRY POINT
# =============================================================================

def straighten_islands(mesh, uv_layer, island_analysis, report=None):
    """
    Re-lays every detectable quad-grid island of `island_analysis` onto a
    planar UV grid.

    Islands with fewer than 6 faces, any non-quad face, or a topology that
    fails grid detection are skipped untouched. Per island the mean 3D edge
    lengths along each grid axis set the cell aspect ratio, and the result is
    uniformly scaled to the original island UV area (scale preservation) and
    anchored to the original island bounding box. Overlap is impossible by
    construction: every quad owns a distinct grid cell.

    `report`, when callable, receives one message string per info/warning line.

    Returns a StraightenResult.
    """
    result = StraightenResult()

    if mesh is None or uv_layer is None or island_analysis is None:
        result.warnings.append(
            "Straighten skipped: mesh, UV layer or island analysis missing."
        )
        if callable(report):
            report(result.warnings[-1])
        return result

    islands = getattr(island_analysis, "islands", None) or []

    for island in islands:
        if not isinstance(island, dict):
            continue

        island_id = island.get("id", "?")
        faces = island.get("faces") or []

        if len(faces) < 6:
            result.skipped_count += 1
            result.warnings.append(
                f"Island {island_id}: skipped ({len(faces)} faces, minimum is 6)."
            )
            continue

        try:
            error = _straighten_island(mesh, uv_layer, faces)
        except Exception as exc:  # defensive: never abort the whole pass
            error = f"unexpected error: {exc}"

        if error is None:
            result.straightened_count += 1
            result.info.append(f"Island {island_id}: straightened to planar grid.")
        else:
            result.skipped_count += 1
            result.warnings.append(f"Island {island_id}: skipped ({error}).")

    result.info.append(
        f"Straighten done: {result.straightened_count} straightened, "
        f"{result.skipped_count} skipped of {len(islands)} islands."
    )

    if callable(report):
        for message in result.info + result.warnings:
            report(message)

    result.ok = True
    return result
