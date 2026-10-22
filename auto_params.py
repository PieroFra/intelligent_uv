# pylint: disable=invalid-name
"""
Intelligent UV Mapping — AUTOMATIC PARAMETERS

Derives the clustering settings from what the mesh and the texture actually
are, instead of asking the user to guess them.

Every one of these numbers has a defensible source, and where one does not,
this module says so rather than inventing a formula. The tolerance comes from
the model's own angle distribution. The minimum cluster size comes from the
texture resolution, because an island smaller than its own padding is waste
whatever the geometry looks like. The crease weight comes from whether the
model has creases to hide a seam in.

The island count is the exception. How many islands an asset should have is a
judgement about what it is for — a hero prop and a background crate with the
same geometry want different answers — so nothing here sets it. What is
computable is the point past which islands cost more in padding than they save
in distortion, and that is offered as a ceiling, not a target.
"""

import math

from .curvature import CurvatureEstimator
from .utils import angle_between_degrees


class AutoParams:
    """The derived values, with the reasoning attached to each."""

    def __init__(self):
        self.tolerance = 25.0
        self.crease_weight = 1.0
        self.min_cluster_faces = 3
        self.iterations = 6
        self.smooth_passes = 3
        self.island_ceiling = 0
        self.notes = []

    def describe(self):
        return " | ".join(self.notes)


# What counts as a fold a seam can disappear into. This has to be an absolute
# angle, not a share of the model's own distribution: Otsu splits whatever it
# is given, so on a smooth organic mesh it happily labels 5 degree edges as the
# sharp half, and a relative measure then reports creases that do not exist.
CREASE_ANGLE = 30.0

# The fraction of genuinely creased edges at which the pull reaches full
# strength. A tenth of the model being folded is plenty to hide a border in.
CREASE_PRESENCE_FULL = 0.10

# An island whose UV footprint is smaller than this multiple of the margin is
# mostly padding. Four is two margins on each side plus a little content.
MIN_ISLAND_MARGINS = 4.0

# Padding is allowed to eat this much of the texture before the island count is
# considered too high.
PADDING_BUDGET = 0.20


def _dihedral_angles(mesh_analysis):
    """Every manifold edge's dihedral angle, in degrees."""
    faces_per_edge = mesh_analysis.faces_per_edge or []
    normals = mesh_analysis.face_normals or []
    angles = []

    for face_list in faces_per_edge:
        if len(face_list) != 2:
            continue
        f1, f2 = face_list
        if 0 <= f1 < len(normals) and 0 <= f2 < len(normals):
            angles.append(angle_between_degrees(normals[f1], normals[f2]))

    return angles


def derive(mesh_analysis, margin_result=None, settings=None):
    """
    Works out the clustering parameters for this mesh.

    Returns an AutoParams. Every field falls back to its default when the
    measurement it needs is unavailable, and says so in the notes.
    """
    params = AutoParams()

    angles = _dihedral_angles(mesh_analysis)
    face_count = getattr(mesh_analysis, "face_count", 0) or 0

    # --- Tolerance -------------------------------------------------------
    # Otsu splits the angle distribution where the model itself stops being
    # one surface and starts being two. A cluster should grow across the
    # smooth side and stop at the sharp side, so that break IS the tolerance.
    break_angle = None
    if angles:
        try:
            break_angle = CurvatureEstimator._otsu_threshold(angles)
        except Exception:
            # B: a degenerate distribution leaves Otsu undefined; the default
            # tolerance is still usable and the note records the miss.
            break_angle = None

    if break_angle:
        params.tolerance = max(12.0, min(50.0, float(break_angle)))
        params.notes.append(
            f"tolerance {params.tolerance:.0f} deg from the angle distribution"
        )
    else:
        params.notes.append("tolerance left at default: no usable angle spread")

    # --- Crease weight ---------------------------------------------------
    # Pulling borders into creases only helps if there are creases. On a model
    # that is smooth nearly everywhere the pull drags the border somewhere
    # arbitrary instead, which is worse than leaving it straight.
    if angles:
        creased = sum(1 for a in angles if a >= CREASE_ANGLE)
        presence = creased / float(len(angles))
        params.crease_weight = round(
            2.0 * min(1.0, presence / CREASE_PRESENCE_FULL), 2
        )
        params.notes.append(
            f"crease pull {params.crease_weight:.2f} "
            f"({presence * 100.0:.0f}% of edges fold past {CREASE_ANGLE:.0f} deg)"
        )

    # --- Minimum cluster size --------------------------------------------
    # An island has to be bigger than the padding around it to be worth having.
    # That is a texture question, not a geometry one, so it comes from the
    # margin rather than from a face count someone picked.
    margin_uv = getattr(margin_result, "margin_uv", None) if margin_result else None
    coverage = 0.95
    if settings is not None:
        try:
            coverage = float(getattr(settings, "target_coverage", 0.95) or 0.95)
        except (TypeError, ValueError):
            coverage = 0.95

    if margin_uv and face_count > 0:
        # Average UV area a single face will occupy once the whole mesh is
        # packed into `coverage` of the square.
        uv_per_face = (coverage * coverage) / float(face_count)
        min_island_area = (MIN_ISLAND_MARGINS * float(margin_uv)) ** 2

        if uv_per_face > 0.0:
            needed = int(math.ceil(min_island_area / uv_per_face))
            params.min_cluster_faces = max(2, min(12, needed))
            params.notes.append(
                f"min cluster {params.min_cluster_faces} faces "
                f"(below that an island is mostly padding at "
                f"{margin_uv:.4f} UV margin)"
            )
    else:
        params.notes.append("min cluster left at default: no margin available")

    # --- Iteration counts ------------------------------------------------
    # Both loops stop when nothing moves, so these are ceilings rather than
    # targets. The ceiling drops on heavy meshes because each pass is a full
    # traversal and the last passes change very little.
    if face_count > 200000:
        params.iterations, params.smooth_passes = 4, 2
    elif face_count > 50000:
        params.iterations, params.smooth_passes = 6, 3
    else:
        params.iterations, params.smooth_passes = 10, 5

    params.notes.append(
        f"up to {params.iterations} refine and {params.smooth_passes} smooth "
        f"passes for {face_count} faces"
    )

    # --- Island ceiling --------------------------------------------------
    # How many islands an asset SHOULD have is a judgement about what it is
    # for. What is computable is where padding starts costing more than the
    # islands are worth: each island carries roughly its perimeter times the
    # margin in wasted texture, and a square island of area A has perimeter
    # 4*sqrt(A).
    if margin_uv and face_count > 0:
        total_area = coverage * coverage
        # Solving islands * 4 * sqrt(total_area / islands) * margin < budget
        # gives islands < (budget / (4 * margin))^2 / total_area.
        try:
            ceiling = int(
                ((PADDING_BUDGET / (4.0 * float(margin_uv))) ** 2) / total_area
            )
            params.island_ceiling = max(4, min(4000, ceiling))
            params.notes.append(
                f"beyond ~{params.island_ceiling} islands, padding passes "
                f"{PADDING_BUDGET * 100.0:.0f}% of the texture"
            )
        except (ZeroDivisionError, ValueError, OverflowError):
            # A: a zero or absurd margin makes the ceiling meaningless; the
            # caller simply gets no ceiling.
            params.island_ceiling = 0

    return params


def apply_to(settings, params, report=None):
    """
    Writes the derived values onto the settings.

    The island target is deliberately not written: the ceiling is advice, and
    silently capping someone's island count would be a decision made behind
    their back.
    """
    written = []

    for attribute, value in (
        ("vsa_max_angle_deviation", params.tolerance),
        ("vsa_crease_weight", params.crease_weight),
        ("vsa_min_cluster_faces", params.min_cluster_faces),
        ("vsa_iterations", params.iterations),
        ("vsa_smooth_passes", params.smooth_passes),
    ):
        try:
            setattr(settings, attribute, value)
            written.append(attribute)
        except (AttributeError, TypeError, ValueError) as exc:
            # B: one unwritable setting must not stop the rest being applied.
            print(f"[IUV_AUTO] Could not set {attribute}: {exc}")

    if report:
        report("INFO", f"Auto parameters — {params.describe()}.")

    return written
