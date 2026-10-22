# pylint: disable=invalid-name
"""
Intelligent UV Mapping — ISLAND ORIENTATION

Turns each island to the angle at which it occupies the least rectangle, before
the packer sees it.

The packer arranges islands; it does not reshape them. A shell that comes out of
the unwrap at forty degrees to the axes carries a bounding rectangle far larger
than the shell itself, and whatever the packer does with it, that waste is
already baked in. Rotating the shell first is the one improvement that costs the
packer nothing and gives it strictly more room to work with.

The angle is found with rotating calipers over the convex hull, which is exact
rather than approximate: the minimum-area rectangle around a convex polygon
always has one side flush with a hull edge, so testing every hull edge finds the
true optimum. Principal component analysis is the usual shortcut here and is
wrong often enough to matter — it minimises variance, not enclosing area, and an
L-shaped or crescent island sends it off by tens of degrees.

Rotation happens around the island's own centroid, so nothing moves out of the
region it occupied; the packer decides placement afterwards as it always did.
"""

import math

from .utils import loop_uv, polygon_loop_range, set_loop_uv


class OrientResult:
    """Bounding area before and after orienting, and how many islands moved."""
    def __init__(self):
        self.islands = 0
        self.rotated = 0
        self.area_before = 0.0
        self.area_after = 0.0

    @property
    def improvement(self):
        if self.area_before <= 1e-12:
            return 0.0
        return 1.0 - (self.area_after / self.area_before)


def convex_hull(points):
    """
    Andrew's monotone chain hull, counter-clockwise.

    The hull is what makes the calipers exact, and it also shrinks the work:
    an island with four thousand loops usually has a hull of a few dozen
    points, and only those are tested.
    """
    unique = sorted(set(points))
    if len(unique) < 3:
        return unique

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower = []
    for p in unique:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)

    upper = []
    for p in reversed(unique):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)

    return lower[:-1] + upper[:-1]


def min_area_angle(points):
    """
    The rotation that makes the enclosing rectangle smallest.

    Returns (angle_radians, area_before, area_after). The angle is what to
    rotate the points BY, so applying it leaves the minimal rectangle
    axis-aligned.
    """
    hull = convex_hull(points)

    if len(hull) < 3:
        return 0.0, 0.0, 0.0

    def bbox_area(pts):
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        return (max(xs) - min(xs)) * (max(ys) - min(ys))

    original = bbox_area(hull)

    best_angle = 0.0
    best_area = original

    for i in range(len(hull)):
        x1, y1 = hull[i]
        x2, y2 = hull[(i + 1) % len(hull)]

        dx, dy = x2 - x1, y2 - y1
        length = math.hypot(dx, dy)
        if length <= 1e-12:
            continue

        # Rotate so this hull edge lies along the x axis, then measure.
        cos_a, sin_a = dx / length, -dy / length

        min_x = min_y = float("inf")
        max_x = max_y = -float("inf")

        for px, py in hull:
            rx = px * cos_a - py * sin_a
            ry = px * sin_a + py * cos_a
            min_x = min(min_x, rx)
            max_x = max(max_x, rx)
            min_y = min(min_y, ry)
            max_y = max(max_y, ry)

        area = (max_x - min_x) * (max_y - min_y)

        if area < best_area - 1e-12:
            best_area = area
            best_angle = math.atan2(-dy, dx)

    return best_angle, original, best_area


def orient_islands(mesh, uv_layer, island_analysis, min_gain=0.02,
                   report=None):
    """
    Rotates every island to its minimum-area angle.

    `min_gain` is the fraction of bounding area that must be saved before an
    island is touched. Rotating for a one percent gain costs the same float
    error as rotating for a fifty percent one, and on an island already close
    to aligned it is pure noise.

    Returns an OrientResult.
    """
    result = OrientResult()
    islands = getattr(island_analysis, "islands", None) or []

    if not islands or uv_layer is None:
        return result

    polygons = mesh.polygons
    loop_count = len(mesh.loops)

    for record in islands:
        faces = record.get("faces", [])
        if not faces:
            continue

        loops = []
        points = []

        for fidx in faces:
            if not (0 <= fidx < len(polygons)):
                continue
            start, end = polygon_loop_range(polygons[fidx])
            for i in range(start, min(end, loop_count)):
                uv = loop_uv(uv_layer, i)
                if uv is not None:
                    loops.append(i)
                    points.append(uv)

        if len(points) < 3:
            continue

        result.islands += 1

        angle, before, after = min_area_angle(points)
        result.area_before += before

        if before <= 1e-12 or angle == 0.0 or (before - after) < min_gain * before:
            result.area_after += before
            continue

        cx = sum(p[0] for p in points) / len(points)
        cy = sum(p[1] for p in points) / len(points)

        cos_a, sin_a = math.cos(angle), math.sin(angle)

        for loop_index, (px, py) in zip(loops, points):
            ox, oy = px - cx, py - cy
            set_loop_uv(
                uv_layer,
                loop_index,
                cx + ox * cos_a - oy * sin_a,
                cy + ox * sin_a + oy * cos_a,
            )

        result.area_after += after
        result.rotated += 1

    if report and result.rotated:
        report(
            "INFO",
            f"Oriented {result.rotated} of {result.islands} islands, "
            f"shrinking their combined bounding area by "
            f"{result.improvement * 100.0:.1f}%."
        )

    return result
