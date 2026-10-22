# pylint: disable=invalid-name
"""
Intelligent UV Mapping — FAILED ISLAND RECOVERY

Finds the islands the solver gave up on and cuts them until it can flatten
them.

Blender says this out loud — "Unwrap failed to solve 16 of 183 islands, edge
seams may need to be added" — and then carries on. The faces in those islands
come back with no UV area at all, which is why the quality report showed
thousands of collapsed faces while the rest of the layout looked fine. The
message even names the remedy; nothing acted on it.

The approach is deliberately narrow. A failed island is re-cut on its own, with
a tolerance tightened only for that island, and the whole mesh is unwrapped
again. Everything that already worked keeps the seams it had, because widening
the cut globally to rescue a handful of islands is how a layout goes from "16
bad islands" to "everything is fragmented".

Recovery is iterative because one round is not always enough: a tube cut once
becomes a sheet that may still be too curved, and the second round sees a
smaller problem than the first.
"""

from .utils import angle_between_degrees, loop_uv, polygon_loop_range


class RecoveryResult:
    """How many failed islands were found, re-cut and fixed."""
    def __init__(self):
        self.rounds = 0
        self.islands_found = 0
        self.islands_recovered = 0
        self.seams_added = 0
        self.notes = []


def find_failed_islands(mesh, uv_layer, island_analysis, mesh_analysis,
                        area_ratio=1e-5):
    """
    Islands whose faces carry essentially no UV area.

    The test is UV area against 3D area, not UV area alone: a genuinely tiny
    face has a tiny UV footprint and is fine. A collapsed face has 3D area and
    no UV area, which only happens when the solver could not place it.

    Returns a list of (island_id, faces, collapsed_count).
    """
    islands = getattr(island_analysis, "islands", None) or []
    if not islands or uv_layer is None:
        return []

    polygons = getattr(mesh, "polygons", [])
    loop_count = len(getattr(mesh, "loops", []))
    face_areas = getattr(mesh_analysis, "face_areas", None) or []

    failed = []

    for record in islands:
        faces = record.get("faces", [])
        if not faces:
            continue

        collapsed = 0

        for fidx in faces:
            if not (0 <= fidx < len(polygons)):
                continue

            mesh_area = face_areas[fidx] if fidx < len(face_areas) else 0.0
            if mesh_area <= 1e-12:
                continue

            start, end = polygon_loop_range(polygons[fidx])
            uvs = []
            for i in range(start, min(end, loop_count)):
                uv = loop_uv(uv_layer, i)
                if uv is not None:
                    uvs.append(uv)

            if len(uvs) < 3:
                continue

            # Shoelace area of the UV polygon.
            uv_area = 0.0
            for k in range(len(uvs)):
                x1, y1 = uvs[k]
                x2, y2 = uvs[(k + 1) % len(uvs)]
                uv_area += x1 * y2 - x2 * y1
            uv_area = abs(uv_area) * 0.5

            if uv_area / mesh_area < area_ratio:
                collapsed += 1

        # A couple of bad faces is a modelling artefact; most of the island
        # being flat is the solver having given up on all of it.
        if collapsed and collapsed >= 0.5 * len(faces):
            failed.append((record.get("id", -1), faces, collapsed))

    return failed


def add_relief_seams(mesh_analysis, is_seam, faces, tolerance):
    """
    Cuts inside one island, and only inside it.

    The island is re-clustered on its own with a tight tolerance, and the
    borders between the resulting sub-clusters become new seams. Restricting
    the adjacency to the island's own faces is what keeps the cut local: an
    edge leaving the island is never considered, so no neighbouring island is
    disturbed.

    Returns the number of seams added.
    """
    faces_per_edge = getattr(mesh_analysis, "faces_per_edge", None) or []
    face_normals = getattr(mesh_analysis, "face_normals", None) or []
    face_areas = getattr(mesh_analysis, "face_areas", None) or []

    member = set(faces)
    if len(member) < 4:
        return 0

    # Adjacency limited to the island.
    adjacency = {fidx: [] for fidx in member}
    interior = []

    for eidx, face_list in enumerate(faces_per_edge):
        if len(face_list) != 2:
            continue
        f1, f2 = face_list
        if f1 in member and f2 in member:
            adjacency[f1].append((f2, eidx))
            adjacency[f2].append((f1, eidx))
            interior.append((eidx, f1, f2))

    if not interior:
        return 0

    # Region growing across the island alone, with the tightened tolerance.
    assigned = {}
    cluster_id = 0

    ordered = sorted(
        member,
        key=lambda f: face_areas[f] if f < len(face_areas) else 0.0,
        reverse=True,
    )

    for seed in ordered:
        if seed in assigned:
            continue

        assigned[seed] = cluster_id
        stack = [seed]
        acc = list(face_normals[seed])

        while stack:
            fidx = stack.pop()
            for neighbour, _eidx in adjacency.get(fidx, ()):
                if neighbour in assigned:
                    continue
                if angle_between_degrees(acc, face_normals[neighbour]) > tolerance:
                    continue

                assigned[neighbour] = cluster_id
                acc[0] += face_normals[neighbour][0]
                acc[1] += face_normals[neighbour][1]
                acc[2] += face_normals[neighbour][2]
                stack.append(neighbour)

        cluster_id += 1

    if cluster_id <= 1:
        # The island is uniform enough that tightening did nothing. Cut its
        # most creased interior edges instead, so the solver at least has an
        # opening to work from.
        scored = sorted(
            (
                (angle_between_degrees(face_normals[f1], face_normals[f2]), eidx)
                for eidx, f1, f2 in interior
            ),
            reverse=True,
        )
        added = 0
        for _angle, eidx in scored[: max(1, len(scored) // 10)]:
            if not is_seam[eidx]:
                is_seam[eidx] = True
                added += 1
        return added

    added = 0
    for eidx, f1, f2 in interior:
        if assigned.get(f1) != assigned.get(f2) and not is_seam[eidx]:
            is_seam[eidx] = True
            added += 1

    return added


def recover(mesh, uv_layer_getter, island_analyzer, mesh_analysis, is_seam,
            unwrap, mark_seams, start_tolerance=15.0, max_rounds=2,
            report=None):
    """
    Detect, cut, unwrap, repeat.

    The callables are passed in rather than imported so this module stays
    independent of the operator and can be tested without Blender: it needs to
    unwrap and to re-read the result, and it does not care how.

    Returns a RecoveryResult.
    """
    result = RecoveryResult()
    tolerance = max(3.0, float(start_tolerance))

    def say(level, message):
        if report:
            report(level, message)

    for round_index in range(max(0, int(max_rounds))):
        uv_layer = uv_layer_getter()
        island_analysis = island_analyzer()

        if uv_layer is None or island_analysis is None or not island_analysis.ok:
            break

        failed = find_failed_islands(
            mesh, uv_layer, island_analysis, mesh_analysis
        )

        if not failed:
            if round_index:
                say("INFO", "Recovery: every island now solves.")
            break

        if round_index == 0:
            result.islands_found = len(failed)
            say(
                "WARNING",
                f"{len(failed)} islands did not solve and came back flat. "
                "Cutting them open and retrying."
            )

        added_this_round = 0
        for _island_id, faces, _collapsed in failed:
            added_this_round += add_relief_seams(
                mesh_analysis, is_seam, faces, tolerance
            )

        if not added_this_round:
            say(
                "WARNING",
                "Recovery: no further cut is possible inside the failed "
                "islands; they may be degenerate geometry rather than hard "
                "shapes."
            )
            break

        result.seams_added += added_this_round
        result.rounds += 1

        ok, message = mark_seams(is_seam)
        if not ok:
            say("WARNING", f"Recovery: {message}")
            break

        unwrap()

        # Each round cuts harder than the last: what survived the first pass
        # is by definition the more stubborn geometry.
        tolerance = max(3.0, tolerance * 0.6)

    # Final tally against the state we ended with.
    uv_layer = uv_layer_getter()
    island_analysis = island_analyzer()

    if uv_layer is not None and island_analysis is not None and island_analysis.ok:
        still_failed = find_failed_islands(
            mesh, uv_layer, island_analysis, mesh_analysis
        )
        result.islands_recovered = max(
            0, result.islands_found - len(still_failed)
        )

        if result.islands_found:
            say(
                "INFO" if not still_failed else "WARNING",
                f"Recovery: {result.islands_recovered} of "
                f"{result.islands_found} islands fixed with "
                f"{result.seams_added} extra seams over {result.rounds} "
                f"round(s)."
                + ("" if not still_failed else
                   f" {len(still_failed)} still will not solve.")
            )

    return result
