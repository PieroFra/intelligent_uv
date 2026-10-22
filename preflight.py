# pylint: disable=invalid-name
"""
Intelligent UV Mapping — PRE-FLIGHT CHECKS

Finds the things that make unwrapping fail, before it fails.

Every problem here was observed on a real asset. A 47k-face weapon came in with
214 non-manifold edges, faces folded flat enough to read 180 degrees of dihedral
angle, and 46 disconnected pieces. The add-on reported those as three warnings
among a dozen others and carried on, and Blender's unwrap then said it could not
solve 16 of 183 islands. The information was all there and none of it was
actionable.

Each check answers three questions in order: what is wrong, why it breaks UVs,
and what to do about it. A count on its own is not a diagnosis — "2600 boundary
edges" is alarming on a closed mesh and completely normal on a sheet, and only
the second sentence tells the two apart.

Severity is about consequence, not about tidiness:
    BLOCKER  unwrapping will produce garbage; fix before running
    WARNING  the result will be worse than it should be
    NOTE     worth knowing, not worth stopping for
"""

import math

BLOCKER = "BLOCKER"
WARNING = "WARNING"
NOTE = "NOTE"


class Finding:
    """One diagnosed problem."""

    def __init__(self, severity, title, detail, fix, count=0):
        self.severity = severity
        self.title = title
        self.detail = detail
        self.fix = fix
        self.count = count

    def format(self):
        head = f"[{self.severity}] {self.title}"
        if self.count:
            head += f" ({self.count})"
        return f"{head}: {self.detail} Fix: {self.fix}"


class PreflightResult:
    """Everything the checks found, ordered as they were run."""
    def __init__(self):
        self.findings = []
        self.ok = True

    def add(self, severity, title, detail, fix, count=0):
        self.findings.append(Finding(severity, title, detail, fix, count))
        if severity == BLOCKER:
            self.ok = False

    @property
    def blockers(self):
        return [f for f in self.findings if f.severity == BLOCKER]

    @property
    def warnings(self):
        return [f for f in self.findings if f.severity == WARNING]

    def summary(self):
        if not self.findings:
            return "Mesh is clean: nothing found that would spoil the unwrap."

        blockers = len(self.blockers)
        warnings = len(self.warnings)
        notes = len(self.findings) - blockers - warnings

        parts = []
        if blockers:
            parts.append(f"{blockers} blocking")
        if warnings:
            parts.append(f"{warnings} warning")
        if notes:
            parts.append(f"{notes} note")

        return "Pre-flight: " + ", ".join(parts) + "."


class Preflight:
    """Runs every check and returns a diagnosed result."""

    # A face this small relative to the mesh average contributes nothing and
    # tends to be a modelling accident rather than intent.
    DEGENERATE_AREA_RATIO = 1e-6

    # Dihedral angles this close to a half turn mean the two faces lie back to
    # back: the surface folds onto itself and cannot be flattened there.
    FOLDED_ANGLE = 179.0

    @classmethod
    def run(cls, obj, mesh_analysis):
        result = PreflightResult()

        cls._check_object(obj, result)
        cls._check_degenerate(mesh_analysis, result)
        cls._check_manifold(mesh_analysis, result)
        cls._check_components(mesh_analysis, result)
        cls._check_folded(mesh_analysis, result)
        cls._check_ngons(mesh_analysis, result)

        return result

    # ------------------------------------------------------------------

    @staticmethod
    def _check_object(obj, result):
        """Object-level problems that survive into the UVs."""
        scale = getattr(obj, "scale", None)
        if scale is None:
            return

        try:
            sx, sy, sz = float(scale[0]), float(scale[1]), float(scale[2])
        except (TypeError, IndexError, ValueError):
            return

        # Negative scale mirrors the mesh. The unwrap still works, but every
        # island comes out wound backwards, and baked normal maps will be wrong
        # in a way that is hard to trace later.
        if sx * sy * sz < 0.0:
            result.add(
                BLOCKER,
                "Object scale is mirrored",
                "One axis has negative scale, so faces are wound inside out. "
                "UVs will be flipped and any normal map baked from them will be "
                "wrong.",
                "Object menu, Apply, Scale. Then recalculate normals outside "
                "with Shift+N in Edit Mode.",
            )
            return

        spread = max(abs(sx), abs(sy), abs(sz)) - min(abs(sx), abs(sy), abs(sz))
        if spread > 1e-4:
            result.add(
                BLOCKER,
                "Object scale is not uniform",
                f"Scale is ({sx:.3f}, {sy:.3f}, {sz:.3f}). Texel density is "
                "measured on the mesh data, which does not include object "
                "scale, so the density on screen will not match what is "
                "reported.",
                "Object menu, Apply, Scale.",
            )
        elif abs(abs(sx) - 1.0) > 1e-4:
            result.add(
                WARNING,
                "Object scale is not applied",
                f"Uniform scale of {sx:.3f}. Island margins are computed from "
                "mesh-space size, so the padding in the final texture will be "
                "off by this factor.",
                "Object menu, Apply, Scale.",
            )

        modifiers = getattr(obj, "modifiers", None)
        if modifiers is not None and len(modifiers) > 0:
            generative = [
                m.name for m in modifiers
                if getattr(m, "type", "") in {
                    'SUBSURF', 'MIRROR', 'ARRAY', 'SOLIDIFY', 'BEVEL',
                    'SCREW', 'REMESH', 'DECIMATE',
                }
            ]
            if generative:
                result.add(
                    WARNING,
                    "Generative modifiers are active",
                    f"{', '.join(generative[:4])} change the geometry, but UVs "
                    "are written to the base mesh. The seams you get will not "
                    "match what you see in the viewport.",
                    "Apply the modifiers, or accept that the UVs describe the "
                    "base cage only.",
                    count=len(generative),
                )

    @classmethod
    def _check_degenerate(cls, ma, result):
        """Zero-area faces and zero-length edges."""
        areas = getattr(ma, "face_areas", None) or []
        if areas:
            positive = [a for a in areas if a > 0.0]
            mean = sum(positive) / len(positive) if positive else 0.0
            threshold = mean * cls.DEGENERATE_AREA_RATIO

            zero = sum(1 for a in areas if a <= threshold)
            if zero:
                result.add(
                    BLOCKER,
                    "Degenerate faces",
                    "These faces have effectively no area. The unwrap solver "
                    "divides by face area, so they poison the islands they "
                    "belong to and produce the zero-area UV islands seen in "
                    "the quality report.",
                    "Edit Mode, Select menu, Select All by Trait, Faces by "
                    "Sides or use Mesh, Clean Up, Degenerate Dissolve.",
                    count=zero,
                )

        lengths = getattr(ma, "edge_lengths", None) or []
        if lengths:
            positive = [length for length in lengths if length > 0.0]
            mean = sum(positive) / len(positive) if positive else 0.0
            zero_edges = sum(1 for length in lengths if length <= mean * 1e-6)
            if zero_edges:
                result.add(
                    BLOCKER,
                    "Zero-length edges",
                    "Two vertices sit on top of each other. Seam paths cannot "
                    "cross them and the solver cannot orient the faces around "
                    "them.",
                    "Edit Mode, select all, Mesh, Merge, By Distance.",
                    count=zero_edges,
                )

    @staticmethod
    def _check_manifold(ma, result):
        """Non-manifold and boundary edges, judged in context."""
        non_manifold = len(getattr(ma, "non_manifold_edges", set()) or set())
        boundary = len(getattr(ma, "boundary_edges", set()) or set())
        edge_count = max(1, getattr(ma, "edge_count", 1))

        if non_manifold:
            result.add(
                BLOCKER,
                "Non-manifold edges",
                "More than two faces share an edge. There is no consistent way "
                "to flatten that, so the solver gives up on the whole island "
                "containing it.",
                "Edit Mode, Select menu, All by Trait, Non Manifold, then "
                "separate or delete the offending faces.",
                count=non_manifold,
            )

        # A boundary edge is normal on a sheet and suspicious on a solid, so
        # the count alone says nothing. The proportion does.
        if boundary:
            ratio = boundary / float(edge_count)
            if ratio > 0.25:
                result.add(
                    NOTE,
                    "Open mesh",
                    f"{ratio * 100.0:.0f}% of edges are on a border. That is "
                    "normal for a sheet or a cut-away, and means the mesh is "
                    "already open where it matters.",
                    "Nothing, unless this model was meant to be closed.",
                    count=boundary,
                )
            else:
                result.add(
                    WARNING,
                    "Holes in a mostly closed mesh",
                    f"{boundary} border edges on an otherwise solid mesh "
                    "usually means missing faces rather than intentional "
                    "openings. Islands will end at these holes.",
                    "Edit Mode, Select menu, All by Trait, Non Manifold with "
                    "only Boundaries ticked, to see where they are.",
                    count=boundary,
                )

    @staticmethod
    def _check_components(ma, result):
        """Disconnected pieces."""
        components = getattr(ma, "component_count", 1) or 1
        faces = max(1, getattr(ma, "face_count", 1))

        if components > 1:
            severity = NOTE if components < 0.01 * faces else WARNING
            result.add(
                severity,
                "Mesh is in several pieces",
                f"{components} disconnected components. Each becomes at least "
                "one island, so a high count sets a floor on how few islands "
                "you can end up with.",
                "Nothing if intentional. If pieces should be joined, Edit "
                "Mode, select all, Mesh, Merge, By Distance.",
                count=components,
            )

    @classmethod
    def _check_folded(cls, ma, result):
        """Faces folded back onto their neighbour."""
        faces_per_edge = getattr(ma, "faces_per_edge", None) or []
        normals = getattr(ma, "face_normals", None) or []

        if not faces_per_edge or not normals:
            return

        folded = 0
        for face_list in faces_per_edge:
            if len(face_list) != 2:
                continue
            f1, f2 = face_list
            if not (0 <= f1 < len(normals) and 0 <= f2 < len(normals)):
                continue

            n1, n2 = normals[f1], normals[f2]
            dot = n1[0] * n2[0] + n1[1] * n2[1] + n1[2] * n2[2]
            angle = math.degrees(math.acos(max(-1.0, min(1.0, dot))))
            if angle >= cls.FOLDED_ANGLE:
                folded += 1

        if folded:
            result.add(
                WARNING,
                "Faces folded back on themselves",
                "Neighbouring faces point in opposite directions, so the "
                "surface doubles back. Either the normals are inconsistent or "
                "the geometry genuinely overlaps; both make the flattened "
                "result overlap too.",
                "Edit Mode, select all, Shift+N to recalculate normals. If "
                "they persist, the geometry itself is folded.",
                count=folded,
            )

    @staticmethod
    def _check_ngons(ma, result):
        """Faces with many sides."""
        face_vertices = getattr(ma, "face_vertices", None) or []
        if not face_vertices:
            return

        ngons = sum(1 for verts in face_vertices if len(verts) > 4)
        if ngons:
            faces = max(1, len(face_vertices))
            result.add(
                NOTE,
                "N-gons",
                f"{ngons} faces have more than four sides "
                f"({ngons * 100.0 / faces:.1f}% of the mesh). They unwrap "
                "fine, but a large concave n-gon can flatten with a twist.",
                "Nothing needed. Triangulate only if the result looks wrong "
                "around them.",
                count=ngons,
            )
