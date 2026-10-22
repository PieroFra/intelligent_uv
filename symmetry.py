# pylint: disable=invalid-name
"""
Intelligent UV Mapping — SYMMETRY

Detects that a model is mirrored and makes the seams mirror with it.

Almost every hard surface asset is symmetric about one plane, and a clustering
algorithm has no idea. It runs over the whole mesh at once, so the left side and
the right side are grown independently and end up cut in subtly different
places: a border that sits on a crease on the left drifts a face off it on the
right, because the running average happened to reach that face from a different
direction. Nothing about it is wrong, and it looks wrong immediately — an artist
reads asymmetry on a symmetric object as a mistake.

There is a practical consequence too. Mirrored halves cut identically produce
mirrored islands, which the stacking pass can then lay on top of each other; cut
differently they are merely similar, and stacking rejects them. Symmetry and
stacking pay for each other.

The plane is found rather than assumed. Testing the three local axes and taking
the one that actually pairs up faces means a model built off-centre, or
symmetric about Y rather than X, is handled without the user having to say so.
"""

from .utils import angle_between_degrees


class SymmetryResult:
    """The detected mirror plane and what mirroring changed."""
    def __init__(self):
        self.found = False
        self.axis = -1
        self.axis_name = ""
        self.coverage = 0.0
        self.mirrored_faces = 0
        self.seams_added = 0
        self.seams_removed = 0


AXIS_NAMES = ("X", "Y", "Z")


def _quantize(value, tolerance):
    return int(round(value / tolerance))


def detect_symmetry(mesh_analysis, tolerance=None, min_coverage=0.8):
    """
    Finds the local axis the mesh is mirrored about.

    Face centres are hashed into a grid and each one is looked up at its
    mirrored position, which is O(F) per axis rather than comparing every pair.
    A model counts as symmetric when most of its faces find a partner: a few
    that do not is normal, since a real asset usually carries some asymmetric
    detail such as a charging handle or an ejection port.

    Returns (axis_index, coverage, face_mirror) with axis -1 when none holds.
    """
    centers = getattr(mesh_analysis, "face_centers", None) or []
    normals = getattr(mesh_analysis, "face_normals", None) or []
    areas = getattr(mesh_analysis, "face_areas", None) or []
    face_count = getattr(mesh_analysis, "face_count", 0)

    if face_count < 8 or len(centers) != face_count:
        return -1, 0.0, {}

    if tolerance is None:
        # Scale the tolerance to the model: an absolute epsilon is far too
        # tight on a large asset and far too loose on a small one.
        extent = 0.0
        for c in centers:
            extent = max(extent, abs(c[0]), abs(c[1]), abs(c[2]))
        tolerance = max(1e-5, extent * 1e-4)

    best_axis = -1
    best_coverage = 0.0
    best_map = {}

    for axis in range(3):
        grid = {}
        for fidx, c in enumerate(centers):
            key = (
                _quantize(c[0], tolerance),
                _quantize(c[1], tolerance),
                _quantize(c[2], tolerance),
            )
            grid.setdefault(key, []).append(fidx)

        pairs = {}
        matched = 0

        for fidx, c in enumerate(centers):
            target = list(c)
            target[axis] = -target[axis]

            key = (
                _quantize(target[0], tolerance),
                _quantize(target[1], tolerance),
                _quantize(target[2], tolerance),
            )

            candidates = []
            # The mirrored point can land either side of a bucket boundary.
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for dz in (-1, 0, 1):
                        candidates.extend(
                            grid.get((key[0] + dx, key[1] + dy, key[2] + dz), ())
                        )

            best = -1
            best_error = tolerance * 2.0

            for other in candidates:
                oc = centers[other]
                error = max(
                    abs(oc[0] - target[0]),
                    abs(oc[1] - target[1]),
                    abs(oc[2] - target[2]),
                )
                if error > best_error:
                    continue

                # Area guards against a coincidental position match between two
                # genuinely different faces.
                if (fidx < len(areas) and other < len(areas)
                        and areas[fidx] > 1e-12):
                    if abs(areas[other] - areas[fidx]) > 0.05 * areas[fidx]:
                        continue

                # The partner's normal must be the mirror of this one, or the
                # two faces sit in mirrored places while facing elsewhere.
                if fidx < len(normals) and other < len(normals):
                    mirrored_normal = list(normals[fidx])
                    mirrored_normal[axis] = -mirrored_normal[axis]
                    if angle_between_degrees(mirrored_normal, normals[other]) > 15.0:
                        continue

                best = other
                best_error = error

            if best >= 0:
                pairs[fidx] = best
                matched += 1

        coverage = matched / float(face_count)

        if coverage > best_coverage:
            best_coverage = coverage
            best_axis = axis
            best_map = pairs

    if best_coverage < min_coverage:
        return -1, best_coverage, {}

    return best_axis, best_coverage, best_map


def build_edge_mirror(mesh_analysis, face_mirror):
    """
    Edge to mirrored edge, derived from the face pairing.

    Going through faces rather than matching edge midpoints directly avoids a
    second spatial search, and it inherits the checks the face matching already
    made.
    """
    faces_per_edge = getattr(mesh_analysis, "faces_per_edge", None) or []
    edges_per_face = getattr(mesh_analysis, "edges_per_face", None) or []
    edge_lengths = getattr(mesh_analysis, "edge_lengths", None) or []

    edge_mirror = {}

    for eidx, face_list in enumerate(faces_per_edge):
        if not face_list:
            continue

        src_face = face_list[0]
        dst_face = face_mirror.get(src_face)
        if dst_face is None or dst_face >= len(edges_per_face):
            continue

        length = edge_lengths[eidx] if eidx < len(edge_lengths) else 0.0

        # Among the mirrored face's edges, the partner is the one of matching
        # length that is not already claimed.
        best = -1
        best_error = float("inf")

        for candidate in edges_per_face[dst_face]:
            if candidate in edge_mirror.values():
                continue
            other = edge_lengths[candidate] if candidate < len(edge_lengths) else 0.0
            error = abs(other - length)
            if error < best_error:
                best_error = error
                best = candidate

        if best >= 0 and (length <= 1e-12 or best_error <= 0.02 * length):
            edge_mirror[eidx] = best

    return edge_mirror


def symmetrize_seams(mesh_analysis, is_seam, axis, edge_mirror,
                     protected=(), report=None):
    """
    Makes one side's seams the authority and copies them across.

    Copying rather than unioning is deliberate. A union of both halves keeps
    every cut either side produced, so the result is symmetric but has roughly
    twice the seams the algorithm thought were needed. Taking one half as
    authoritative gives exactly the layout the clusterer decided, applied
    consistently to both sides.

    Edges the user placed by hand are never removed, on either side.

    Returns (added, removed).
    """
    centers = getattr(mesh_analysis, "face_centers", None) or []
    faces_per_edge = getattr(mesh_analysis, "faces_per_edge", None) or []
    protected = set(protected or ())

    added = 0
    removed = 0

    for eidx, mirror in edge_mirror.items():
        if eidx == mirror or mirror in protected:
            continue

        face_list = faces_per_edge[eidx] if eidx < len(faces_per_edge) else ()
        if not face_list:
            continue

        centre = centers[face_list[0]] if face_list[0] < len(centers) else None
        if centre is None:
            continue

        # Only the positive half drives; the negative half receives. Edges
        # sitting on the plane itself are their own mirror and are skipped.
        if centre[axis] <= 0.0:
            continue

        if is_seam[eidx] and not is_seam[mirror]:
            is_seam[mirror] = True
            added += 1
        elif not is_seam[eidx] and is_seam[mirror]:
            is_seam[mirror] = False
            removed += 1

    if report and (added or removed):
        report(
            "INFO",
            f"Symmetry: mirrored the {AXIS_NAMES[axis]} axis seams "
            f"({added} added, {removed} removed on the opposite half)."
        )

    return added, removed


def apply(mesh_analysis, is_seam, settings, report=None):
    """
    Detect and symmetrize in one call.

    Returns a SymmetryResult.
    """
    result = SymmetryResult()

    try:
        min_coverage = float(
            getattr(settings, "symmetry_min_coverage", 0.8) or 0.8
        )
    except (TypeError, ValueError):
        min_coverage = 0.8

    axis, coverage, face_mirror = detect_symmetry(
        mesh_analysis, min_coverage=min_coverage
    )

    result.coverage = coverage

    if axis < 0:
        if report:
            report(
                "INFO",
                f"Symmetry: none found (best axis pairs {coverage * 100.0:.0f}% "
                "of faces). Seams left as planned."
            )
        return result

    result.found = True
    result.axis = axis
    result.axis_name = AXIS_NAMES[axis]
    result.mirrored_faces = len(face_mirror)

    edge_mirror = build_edge_mirror(mesh_analysis, face_mirror)

    if not edge_mirror:
        if report:
            report(
                "WARNING",
                f"Symmetry: {AXIS_NAMES[axis]} axis detected but no edge "
                "pairing could be built; seams left as planned."
            )
        return result

    if report:
        report(
            "INFO",
            f"Symmetry: {AXIS_NAMES[axis]} axis, {coverage * 100.0:.0f}% of "
            f"faces paired, {len(edge_mirror)} edges matched."
        )

    result.seams_added, result.seams_removed = symmetrize_seams(
        mesh_analysis, is_seam, axis, edge_mirror,
        protected=getattr(mesh_analysis, "existing_seams", ()) or (),
        report=report,
    )

    return result
