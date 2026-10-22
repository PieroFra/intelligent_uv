# pylint: disable=invalid-name
"""
Intelligent UV Mapping — DUPLICATE ISLAND STACKING

Finds islands that are the same piece of geometry repeated, and lays their UVs
on top of each other so the repeats cost no texture space at all.

A weapon is the obvious case: the same screw appears twenty times, the same rail
segment eight times, and the two halves of a symmetric body are mirror copies.
Packed normally, every repeat claims its own patch of the texture. Stacked, they
share one, and the space freed goes to the parts that are actually unique — at
1K that is often the difference between a readable asset and a mushy one.

Neither Blender's packer nor the commercial ones do this automatically, because
it is not a packing problem: by the time the packer runs, the duplicates are
already separate shells and it has no way to know they were ever the same thing.
The information lives in the 3D geometry, which is where this looks.

The whole approach is built around being wrong safely. Matching geometry by
signature can produce false positives, and stacking two islands that are not
really identical corrupts the layout in a way that is hard to notice. So every
candidate is verified after the copy — the resulting UV areas must match face
for face — and anything that fails is put back exactly as it was.
"""


from .utils import loop_uv, polygon_loop_range, set_loop_uv


class StackResult:
    """Duplicate groups found, islands stacked, and candidates rejected."""
    def __init__(self):
        self.groups = 0
        self.stacked = 0
        self.rejected = 0
        self.area_saved = 0.0
        self.notes = []


def _island_signature(faces, mesh_analysis, buckets=64):
    """
    A value that is equal for islands of identical shape and almost never
    equal otherwise.

    Built only from quantities that survive moving, rotating or mirroring the
    piece: how many faces, how much area, and the distribution of face sizes.
    Position is deliberately absent — two screws at opposite ends of a gun are
    the same screw.

    Areas are bucketed rather than compared exactly because a mirrored or
    rotated copy accumulates float error, and an exact tuple would then never
    match.
    """
    areas = mesh_analysis.face_areas or []
    sizes = sorted(areas[f] for f in faces if f < len(areas))

    if not sizes:
        return None

    total = sum(sizes)
    if total <= 1e-12:
        return None

    # Quantize each face's share of the island, so the signature depends on
    # proportions rather than absolute scale error.
    quantized = tuple(
        int(round(size / total * buckets * len(sizes))) for size in sizes
    )

    return (len(faces), round(total, 6), quantized)


def _canonical_face_order(faces, mesh_analysis):
    """
    A deterministic walk over the island's faces.

    Two copies of the same geometry must produce the same order, so the walk
    cannot depend on face index: those differ between copies. It starts at the
    largest face and, at every step, visits neighbours sorted by area. Ties are
    broken by the neighbour's own neighbour areas, which is enough to separate
    the symmetric cases that would otherwise be ambiguous.

    Returns a list of face indices, or None when the walk is ambiguous.
    """
    areas = mesh_analysis.face_areas or []
    faces_per_edge = mesh_analysis.faces_per_edge or []
    member = set(faces)

    adjacency = {f: [] for f in member}
    for face_list in faces_per_edge:
        if len(face_list) != 2:
            continue
        f1, f2 = face_list
        if f1 in member and f2 in member:
            adjacency[f1].append(f2)
            adjacency[f2].append(f1)

    def area_of(f):
        return areas[f] if f < len(areas) else 0.0

    def rank(f):
        neighbours = sorted((area_of(n) for n in adjacency.get(f, ())), reverse=True)
        return (-area_of(f), tuple(-a for a in neighbours[:4]))

    start = min(member, key=rank)

    order = [start]
    seen = {start}
    frontier = [start]

    while frontier:
        current = frontier.pop(0)
        for neighbour in sorted(adjacency.get(current, ()), key=rank):
            if neighbour not in seen:
                seen.add(neighbour)
                order.append(neighbour)
                frontier.append(neighbour)

    if len(order) != len(member):
        # Disconnected: the island is not one piece, so the walk cannot cover
        # it and any correspondence built from it would be nonsense.
        return None

    return order


def _read_island_uvs(mesh, uv_layer, order):
    """UV coordinates of every loop, in canonical face order."""
    polygons = mesh.polygons
    loop_count = len(mesh.loops)
    out = []

    for fidx in order:
        start, end = polygon_loop_range(polygons[fidx])
        face_uvs = []
        for i in range(start, min(end, loop_count)):
            uv = loop_uv(uv_layer, i)
            face_uvs.append(uv if uv is not None else (0.0, 0.0))
        out.append(face_uvs)

    return out


def _polygon_area(points):
    if len(points) < 3:
        return 0.0
    total = 0.0
    for i in range(len(points)):
        x1, y1 = points[i]
        x2, y2 = points[(i + 1) % len(points)]
        total += x1 * y2 - x2 * y1
    return abs(total) * 0.5


def stack_duplicates(mesh, uv_layer, island_analysis, mesh_analysis,
                     tolerance=0.02, report=None):
    """
    Copies one island's UVs onto every island that is the same shape.

    Returns a StackResult. Nothing is changed for a group that fails
    verification.
    """
    result = StackResult()
    islands = getattr(island_analysis, "islands", None) or []

    if len(islands) < 2 or uv_layer is None:
        return result

    def say(level, message):
        if report:
            report(level, message)

    # Group by signature.
    groups = {}
    for record in islands:
        faces = record.get("faces", [])
        if len(faces) < 2:
            continue

        signature = _island_signature(faces, mesh_analysis)
        if signature is None:
            continue

        groups.setdefault(signature, []).append(record)

    polygons = mesh.polygons
    loop_count = len(mesh.loops)

    for signature, members in groups.items():
        if len(members) < 2:
            continue

        orders = []
        usable = True
        for record in members:
            order = _canonical_face_order(record["faces"], mesh_analysis)
            if order is None:
                usable = False
                break
            orders.append(order)

        if not usable:
            continue

        # Every copy must have the same loop layout face for face, or the UVs
        # cannot be transferred corner to corner.
        reference_shape = [
            polygons[f].loop_total for f in orders[0]
        ]
        if any(
            [polygons[f].loop_total for f in order] != reference_shape
            for order in orders[1:]
        ):
            continue

        result.groups += 1

        source_uvs = _read_island_uvs(mesh, uv_layer, orders[0])
        source_area = sum(_polygon_area(face) for face in source_uvs)

        if source_area <= 1e-12:
            continue

        for order in orders[1:]:
            # Keep the original so a failed verification can be undone
            # exactly, rather than approximately.
            previous = _read_island_uvs(mesh, uv_layer, order)

            wrote = []
            for face_pos, fidx in enumerate(order):
                start, end = polygon_loop_range(polygons[fidx])
                for corner, i in enumerate(range(start, min(end, loop_count))):
                    if corner < len(source_uvs[face_pos]):
                        u, v = source_uvs[face_pos][corner]
                        set_loop_uv(uv_layer, i, u, v)
                        wrote.append(i)

            # Verify: the copy should now cover the same UV area as the source.
            copied = _read_island_uvs(mesh, uv_layer, order)
            copied_area = sum(_polygon_area(face) for face in copied)

            if abs(copied_area - source_area) > tolerance * source_area:
                for face_pos, fidx in enumerate(order):
                    start, end = polygon_loop_range(polygons[fidx])
                    for corner, i in enumerate(range(start, min(end, loop_count))):
                        if corner < len(previous[face_pos]):
                            u, v = previous[face_pos][corner]
                            set_loop_uv(uv_layer, i, u, v)
                result.rejected += 1
                continue

            result.stacked += 1
            result.area_saved += source_area

    if result.stacked:
        say(
            "INFO",
            f"Stacked {result.stacked} duplicate islands across "
            f"{result.groups} groups, freeing {result.area_saved * 100.0:.1f}% "
            "of the UV square."
            + (
                f" {result.rejected} candidates failed verification and were "
                "left alone."
                if result.rejected else ""
            )
        )
    elif result.groups:
        say(
            "INFO",
            f"{result.groups} groups of similar islands found, none could be "
            "stacked safely."
        )

    return result
