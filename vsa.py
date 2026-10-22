# pylint: disable=invalid-name
"""
Intelligent UV Mapping — VSA CLUSTERING AND TOPOLOGY RESOLUTION

Replaces per-edge thresholding with two stages that decide seams from the
shape of the surface rather than from one number applied everywhere.

Why the threshold approach ran out of road:
an edge threshold asks "does the surface bend sharply here?" and nothing else.
It cannot see that a smooth cylinder must be cut even though no edge on it
bends, and it cannot see that a gentle bevel chain belongs to the flat panel
beside it. On a real asset both mistakes appear at once: lowering the threshold
to open the cylinder shatters the panels first, and raising it to keep the
panels whole leaves the cylinder closed and unsolvable.

Stage 1 — clustering (VSA-style region growing)
Faces are grown into clusters whose normals stay within a tolerance of the
cluster's running average, so a cluster is a patch that is genuinely close to
flat. The boundaries between clusters are the seams. This is a decision about
regions, not about individual edges.

Stage 2 — topology
Clustering alone cannot guarantee a cluster is unwrappable. A band around a
cylinder has uniform normals along its length and will happily grow into a
closed ring, which no unwrap can flatten. The Euler characteristic detects this
without any geometric guesswork: a patch homeomorphic to a disc has X = 1, and
anything with X <= 0 is a ring or has holes. Those clusters get cut along a
shortest path between their boundary loops, found with Dijkstra over the
cluster's own edges.

Connectivity comes from the edge -> face map the analyser already built from
bmesh, so nothing here is quadratic in the face count.
"""

import heapq
import math

from .utils import angle_between_degrees, normalize_vector


class VSAResult:
    """Outcome of clustering plus topology resolution."""

    def __init__(self):
        self.ok = False
        self.errors = []
        self.warnings = []
        self.info = []

        # face index -> cluster id
        self.face_cluster = []
        self.cluster_count = 0

        # Edge mask, same shape the rest of the pipeline expects.
        self.is_seam = []
        self.seam_edges = set()

        self.boundary_seam_count = 0
        self.topology_seam_count = 0
        self.rings_resolved = 0
        self.discs = 0
        self.non_discs = 0
        self.lloyd_iterations = 0
        self.absorbed_clusters = 0
        self.boundary_moves = 0


class VSAClusterer:
    """
    Grows faces into near-planar clusters.

    A priority queue orders the frontier by how well each candidate face fits
    the cluster it would join, so the flattest continuation is always taken
    first and a cluster stops at the point where the surface genuinely turns
    away. Seeding from the largest unassigned face keeps big panels whole
    instead of letting them be nibbled at from a corner.
    """

    @staticmethod
    def build_face_adjacency(faces_per_edge, face_count):
        """
        face index -> [(neighbour face, connecting edge), ...]

        Built from the edge -> face map, which is O(E). Walking every pair of
        faces to find neighbours would be O(F^2) and is never necessary.
        """
        adjacency = [[] for _ in range(face_count)]

        for eidx, face_list in enumerate(faces_per_edge):
            if len(face_list) != 2:
                continue

            f1, f2 = face_list[0], face_list[1]
            if 0 <= f1 < face_count and 0 <= f2 < face_count:
                adjacency[f1].append((f2, eidx))
                adjacency[f2].append((f1, eidx))

        return adjacency

    @classmethod
    def cluster(cls, mesh_analysis, max_angle_deviation=25.0,
                area_weighted=True, blocked_edges=None):
        """
        Assigns every face to a cluster.

        `blocked_edges` are edges clustering may not cross — material
        boundaries and hand-placed seams — so the user's intent survives.

        Returns (face_cluster, cluster_count).
        """
        face_normals = mesh_analysis.face_normals or []
        face_areas = mesh_analysis.face_areas or []
        face_count = mesh_analysis.face_count

        if face_count == 0 or not face_normals:
            return [], 0

        blocked = set(blocked_edges or ())
        tolerance = max(1.0, min(179.0, float(max_angle_deviation)))

        adjacency = cls.build_face_adjacency(
            mesh_analysis.faces_per_edge or [], face_count
        )

        assigned = [-1] * face_count

        # Largest faces first: a big flat panel should seed its own cluster
        # rather than being absorbed into a neighbour that happened to start.
        seed_order = sorted(
            range(face_count),
            key=lambda f: face_areas[f] if f < len(face_areas) else 0.0,
            reverse=True,
        )

        cluster_id = 0

        for seed in seed_order:
            if assigned[seed] != -1:
                continue

            assigned[seed] = cluster_id

            # Running area-weighted sum of the cluster's normals. Normalizing
            # only when comparing keeps the accumulation exact.
            weight = (
                face_areas[seed] if area_weighted and seed < len(face_areas) else 1.0
            )
            weight = max(weight, 1e-12)
            acc = [
                face_normals[seed][0] * weight,
                face_normals[seed][1] * weight,
                face_normals[seed][2] * weight,
            ]

            frontier = []
            for neighbour, eidx in adjacency[seed]:
                if assigned[neighbour] == -1 and eidx not in blocked:
                    deviation = angle_between_degrees(
                        face_normals[seed], face_normals[neighbour]
                    )
                    heapq.heappush(frontier, (deviation, neighbour))

            while frontier:
                _deviation, fidx = heapq.heappop(frontier)

                if assigned[fidx] != -1:
                    continue

                mean = normalize_vector(acc)
                if mean is None:
                    break

                # Re-measure against the cluster as it stands now: the value
                # stored in the queue was correct when pushed, and the cluster
                # has moved since.
                current = angle_between_degrees(mean, face_normals[fidx])
                if current > tolerance:
                    continue

                assigned[fidx] = cluster_id

                weight = (
                    face_areas[fidx]
                    if area_weighted and fidx < len(face_areas)
                    else 1.0
                )
                weight = max(weight, 1e-12)
                acc[0] += face_normals[fidx][0] * weight
                acc[1] += face_normals[fidx][1] * weight
                acc[2] += face_normals[fidx][2] * weight

                for neighbour, eidx in adjacency[fidx]:
                    if assigned[neighbour] == -1 and eidx not in blocked:
                        heapq.heappush(
                            frontier,
                            (
                                angle_between_degrees(
                                    mean, face_normals[neighbour]
                                ),
                                neighbour,
                            ),
                        )

            cluster_id += 1

        return assigned, cluster_id


    @classmethod
    def partition(cls, adjacency, proxies, seeds, face_normals, face_areas,
                  face_count, blocked_edges, area_weighted):
        """
        Assigns every face to the proxy it fits best, growing from all seeds at
        once.

        This is the partition half of a Lloyd iteration. A single global
        priority queue holds candidates from every proxy, so the face with the
        smallest error anywhere is always claimed next. That is what stops an
        early cluster from swallowing faces that a later one would have fitted
        better, which is the weakness of growing clusters one after another.

        Unlike the adaptive pass there is no tolerance cut-off: every face is
        assigned to some proxy, because the proxies are fixed and their number
        is what controls granularity.
        """
        assigned = [-1] * face_count
        queue = []

        for cid, seed in enumerate(seeds):
            if 0 <= seed < face_count:
                heapq.heappush(queue, (0.0, seed, cid))

        while queue:
            error, fidx, cid = heapq.heappop(queue)

            if assigned[fidx] != -1:
                continue

            assigned[fidx] = cid

            for neighbour, eidx in adjacency[fidx]:
                if assigned[neighbour] != -1 or eidx in blocked_edges:
                    continue

                deviation = angle_between_degrees(
                    proxies[cid], face_normals[neighbour]
                )

                # Area weighting makes a large misfit face cost more than a
                # sliver, so clusters are shaped by what actually covers the
                # surface rather than by face count.
                weight = (
                    face_areas[neighbour]
                    if area_weighted and neighbour < len(face_areas)
                    else 1.0
                )
                heapq.heappush(
                    queue, (deviation * max(weight, 1e-12), neighbour, cid)
                )

        return assigned

    @staticmethod
    def fit(assigned, cluster_count, face_normals, face_areas, area_weighted):
        """
        Recomputes each proxy as the area-weighted average normal of the faces
        currently assigned to it, and picks the face closest to that average as
        the next seed.

        This is the fit half of a Lloyd iteration: the proxy moves to the
        centre of what it captured, so the next partition is measured against
        where the surface actually is rather than where the first seed happened
        to sit.
        """
        sums = [[0.0, 0.0, 0.0] for _ in range(cluster_count)]

        for fidx, cid in enumerate(assigned):
            if cid < 0:
                continue
            weight = (
                face_areas[fidx]
                if area_weighted and fidx < len(face_areas)
                else 1.0
            )
            weight = max(weight, 1e-12)
            normal = face_normals[fidx]
            sums[cid][0] += normal[0] * weight
            sums[cid][1] += normal[1] * weight
            sums[cid][2] += normal[2] * weight

        proxies = []
        for cid in range(cluster_count):
            mean = normalize_vector(sums[cid])
            proxies.append(mean if mean is not None else (0.0, 0.0, 1.0))

        # Seed = the face that best represents its proxy.
        best = [(float("inf"), -1)] * cluster_count
        for fidx, cid in enumerate(assigned):
            if cid < 0:
                continue
            deviation = angle_between_degrees(proxies[cid], face_normals[fidx])
            if deviation < best[cid][0]:
                best[cid] = (deviation, fidx)

        seeds = [fidx for _deviation, fidx in best]
        return proxies, seeds

    @classmethod
    def refine(cls, mesh_analysis, assigned, cluster_count, iterations=6,
               area_weighted=True, blocked_edges=None):
        """
        Lloyd relaxation over an existing assignment.

        Region growing in one pass is order-dependent: a face joins the first
        cluster that reaches it and never leaves, so the result depends on
        which seed happened to start. Alternating fit and partition lets faces
        change hands until the partition stops moving, which straightens
        cluster borders and stops a cluster from trailing into a neighbour.

        Returns (assigned, iterations_used).
        """
        face_normals = mesh_analysis.face_normals or []
        face_areas = mesh_analysis.face_areas or []
        face_count = mesh_analysis.face_count
        blocked = set(blocked_edges or ())

        if cluster_count <= 0 or face_count == 0:
            return assigned, 0

        adjacency = cls.build_face_adjacency(
            mesh_analysis.faces_per_edge or [], face_count
        )

        used = 0
        for _step in range(max(0, int(iterations))):
            proxies, seeds = cls.fit(
                assigned, cluster_count, face_normals, face_areas, area_weighted
            )

            nxt = cls.partition(
                adjacency, proxies, seeds, face_normals, face_areas,
                face_count, blocked, area_weighted,
            )

            used += 1

            # Converged: another round would return the same partition.
            if nxt == assigned:
                assigned = nxt
                break

            assigned = nxt

        return assigned, used

    @classmethod
    def absorb_micro_clusters(cls, mesh_analysis, assigned, cluster_count,
                              min_faces=3, max_deviation=60.0):
        """
        Folds clusters below `min_faces` into the adjacent cluster whose proxy
        is closest, but only when that proxy is actually a reasonable fit.

        The deviation guard matters: without it a small cluster is absorbed
        into whatever happens to touch it, so a cube face folds into a
        perpendicular neighbour and the flat partition is destroyed. A sliver
        with no plausible home is better left alone than merged into a surface
        it does not belong to.

        Region growing leaves slivers behind: a bevel strip or a lone corner
        face that no proxy fitted well enough to claim early. Each one becomes
        its own UV island, which wastes packing space and produces the
        one-face islands with wild texel density seen in real runs.

        Returns (assigned, cluster_count, absorbed).
        """
        face_normals = mesh_analysis.face_normals or []
        face_areas = mesh_analysis.face_areas or []
        face_count = mesh_analysis.face_count

        if cluster_count <= 1 or min_faces <= 1:
            return assigned, cluster_count, 0

        adjacency = cls.build_face_adjacency(
            mesh_analysis.faces_per_edge or [], face_count
        )

        members = {}
        for fidx, cid in enumerate(assigned):
            if cid >= 0:
                members.setdefault(cid, []).append(fidx)

        proxies, _seeds = cls.fit(
            assigned, cluster_count, face_normals, face_areas, True
        )

        absorbed = 0

        # Smallest first: absorbing one can push a neighbour over the line.
        for cid in sorted(members, key=lambda c: len(members[c])):
            faces = members.get(cid, [])
            if not faces or len(faces) >= min_faces:
                continue

            # Neighbouring clusters, scored by how close their proxy is.
            best_cid = -1
            best_deviation = float("inf")

            for fidx in faces:
                for neighbour, _eidx in adjacency[fidx]:
                    other = assigned[neighbour]
                    if other == cid or other < 0:
                        continue

                    deviation = angle_between_degrees(
                        proxies[other], face_normals[fidx]
                    )
                    if deviation < best_deviation:
                        best_deviation = deviation
                        best_cid = other

            if best_cid < 0 or best_deviation > max_deviation:
                # No neighbour is a plausible home: keeping a small island is
                # better than folding it into a surface facing elsewhere.
                continue

            for fidx in faces:
                assigned[fidx] = best_cid

            members.setdefault(best_cid, []).extend(faces)
            members[cid] = []
            absorbed += 1

        # Renumber so cluster ids stay contiguous.
        remap = {}
        for fidx, cid in enumerate(assigned):
            if cid < 0:
                continue
            if cid not in remap:
                remap[cid] = len(remap)
            assigned[fidx] = remap[cid]

        return assigned, len(remap), absorbed


    @classmethod
    def seed_k(cls, mesh_analysis, k, blocked_edges=None):
        """
        Picks `k` starting proxies spread across the surface.

        Farthest-point seeding: start from the largest face, then repeatedly
        take the face whose normal is furthest from every proxy chosen so far.
        Random or index-order seeds would cluster together on a mesh whose
        faces are stored in build order, and Lloyd cannot recover from proxies
        that all start on the same panel.

        Returns (proxies, seeds).
        """
        face_normals = mesh_analysis.face_normals or []
        face_areas = mesh_analysis.face_areas or []
        face_count = mesh_analysis.face_count

        if face_count == 0 or k <= 0:
            return [], []

        k = min(k, face_count)

        first = max(
            range(face_count),
            key=lambda f: face_areas[f] if f < len(face_areas) else 0.0,
        )
        seeds = [first]
        proxies = [face_normals[first]]

        # Distance of every face to its nearest proxy, updated incrementally so
        # seeding stays O(k * F) rather than O(k * F * k).
        nearest = [
            angle_between_degrees(face_normals[first], face_normals[f])
            for f in range(face_count)
        ]

        while len(seeds) < k:
            candidate = max(range(face_count), key=lambda f: nearest[f])

            if nearest[candidate] <= 1e-6:
                # Every remaining face already matches a proxy exactly; more
                # proxies would be duplicates.
                break

            seeds.append(candidate)
            proxies.append(face_normals[candidate])

            new_normal = face_normals[candidate]
            for f in range(face_count):
                deviation = angle_between_degrees(new_normal, face_normals[f])
                if deviation < nearest[f]:
                    nearest[f] = deviation

        return proxies, seeds

    @classmethod
    def cluster_to_target(cls, mesh_analysis, target, iterations=6,
                          area_weighted=True, blocked_edges=None):
        """
        Produces approximately `target` clusters.

        An artist thinks in island counts, not in degrees of normal deviation,
        and the relationship between the two changes with every mesh. Fixing
        the proxy count and letting Lloyd place them inverts the control: the
        number is what you ask for, and the tolerance becomes a consequence.

        Returns (assigned, cluster_count).
        """
        face_count = mesh_analysis.face_count
        if face_count == 0 or target <= 0:
            return [], 0

        blocked = set(blocked_edges or ())
        proxies, seeds = cls.seed_k(mesh_analysis, target, blocked)

        if not seeds:
            return [], 0

        adjacency = cls.build_face_adjacency(
            mesh_analysis.faces_per_edge or [], face_count
        )

        assigned = cls.partition(
            adjacency, proxies, seeds,
            mesh_analysis.face_normals or [],
            mesh_analysis.face_areas or [],
            face_count, blocked, area_weighted,
        )

        assigned, _used = cls.refine(
            mesh_analysis, assigned, len(seeds),
            iterations=iterations, area_weighted=area_weighted,
            blocked_edges=blocked,
        )

        return assigned, len(seeds)


    @classmethod
    def smooth_boundaries(cls, mesh_analysis, assigned, cluster_count,
                          passes=3, crease_weight=1.0, min_faces=2):
        """
        Straightens cluster borders and pulls them onto creases.

        Region growing decides each face on how well it fits a proxy and
        nothing else, so a border wanders: a face surrounded on three sides by
        another cluster stays where it is because its normal happened to match
        first. The result is a ragged outline that packs badly and puts the
        visible cut in an arbitrary place.

        Each pass reconsiders only the faces that sit on a border, scoring the
        move by two things a proxy distance cannot express:

        - how many of the face's neighbours already belong to the candidate
          cluster, which is what straightens the outline
        - how creased the edges that would BECOME the border are, which is what
          moves the cut into a fold where it hides

        A face only moves when the candidate is a strictly better home, so a
        pass can never oscillate, and the loop stops as soon as nothing moves.

        Returns (assigned, faces_moved).
        """
        face_normals = mesh_analysis.face_normals or []
        face_areas = mesh_analysis.face_areas or []
        face_count = mesh_analysis.face_count

        if cluster_count <= 1 or face_count == 0:
            return assigned, 0

        adjacency = cls.build_face_adjacency(
            mesh_analysis.faces_per_edge or [], face_count
        )

        # Dihedral angle per edge, normalized to 0..1. Computed once.
        faces_per_edge = mesh_analysis.faces_per_edge or []
        crease = {}
        for eidx, face_list in enumerate(faces_per_edge):
            if len(face_list) != 2:
                continue
            f1, f2 = face_list
            if 0 <= f1 < len(face_normals) and 0 <= f2 < len(face_normals):
                crease[eidx] = min(
                    1.0,
                    angle_between_degrees(face_normals[f1], face_normals[f2]) / 90.0,
                )

        moved_total = 0

        for _step in range(max(0, int(passes))):
            proxies, _seeds = cls.fit(
                assigned, cluster_count, face_normals, face_areas, True
            )

            sizes = {}
            for cid in assigned:
                if cid >= 0:
                    sizes[cid] = sizes.get(cid, 0) + 1

            moved = 0

            for fidx in range(face_count):
                current = assigned[fidx]
                if current < 0:
                    continue

                # Never dissolve a cluster by moving its last faces away.
                if sizes.get(current, 0) <= min_faces:
                    continue

                neighbours = adjacency[fidx]
                if not neighbours:
                    continue

                # Candidate clusters, with how many neighbours each holds.
                tally = {}
                for other, eidx in neighbours:
                    cid = assigned[other]
                    if cid >= 0:
                        entry = tally.setdefault(cid, [0, 0.0])
                        entry[0] += 1
                        entry[1] += crease.get(eidx, 0.0)

                if len(tally) <= 1:
                    continue  # interior face, not on a border

                def score(cid):
                    count, crease_sum = tally.get(cid, (0, 0.0))
                    # Lower is better: proxy misfit, minus the reward for
                    # agreeing with neighbours, minus the reward for leaving
                    # the new border sitting in creases.
                    deviation = angle_between_degrees(
                        proxies[cid], face_normals[fidx]
                    )
                    agreement = 10.0 * count
                    hidden = crease_weight * 10.0 * (
                        sum(v[1] for k, v in tally.items() if k != cid)
                    )
                    return deviation - agreement - hidden

                best = min(tally, key=score)

                if best != current and score(best) < score(current) - 1e-6:
                    assigned[fidx] = best
                    sizes[current] -= 1
                    sizes[best] = sizes.get(best, 0) + 1
                    moved += 1

            moved_total += moved
            if moved == 0:
                break

        return assigned, moved_total


class TopologyResolver:
    """
    Finds clusters that cannot be flattened and cuts them open.

    The test is the Euler characteristic X = V - E + F over the cluster's own
    faces, edges and vertices. A patch homeomorphic to a disc gives X = 1.
    A ring around a cylinder gives X = 0, and a patch with several holes gives
    less. No amount of angular tolerance detects that, because a cylinder band
    is locally flat everywhere along its length.

    A ring is opened by cutting a shortest path between two of its boundary
    loops. Dijkstra runs over the cluster's interior edges with a cost that
    prefers short edges and, among equals, edges that already sit in a crease,
    so the cut lands where it is least visible.
    """

    # How strongly a flat edge is penalized relative to a creased one. At 1.0
    # a perfectly flat edge costs twice a sharply creased edge of equal length.
    CREASE_PREFERENCE = 1.0

    @staticmethod
    def euler_characteristic(faces, face_vertices, edges_per_face):
        """
        X = V - E + F over the cluster.

        Vertices and edges are counted once each, however many cluster faces
        touch them, which is what makes the number a topological invariant
        rather than a face tally.
        """
        verts = set()
        edges = set()

        for fidx in faces:
            if fidx < len(face_vertices):
                verts.update(face_vertices[fidx])
            if fidx < len(edges_per_face):
                edges.update(edges_per_face[fidx])

        return len(verts) - len(edges) + len(faces), verts, edges

    @staticmethod
    def boundary_loops(cluster_edges, cluster_faces, faces_per_edge,
                       edge_vertices):
        """
        The cluster's boundary, split into disjoint loops.

        A boundary edge is one with fewer than two of its faces inside the
        cluster. Grouping those edges by shared vertices separates the outer
        rim from the hole rims, which is what the path has to connect.
        """
        member = set(cluster_faces)
        boundary = [
            eidx for eidx in cluster_edges
            if sum(1 for f in faces_per_edge[eidx] if f in member) < 2
        ]

        if not boundary:
            return []

        # Vertex -> boundary edges, so loops can be walked without scanning.
        by_vertex = {}
        for eidx in boundary:
            for vi in edge_vertices[eidx]:
                by_vertex.setdefault(vi, []).append(eidx)

        seen = set()
        loops = []

        for start in boundary:
            if start in seen:
                continue

            loop = set()
            stack = [start]
            seen.add(start)

            while stack:
                eidx = stack.pop()
                loop.add(eidx)

                for vi in edge_vertices[eidx]:
                    for other in by_vertex.get(vi, ()):
                        if other not in seen:
                            seen.add(other)
                            stack.append(other)

            loops.append(loop)

        return loops

    @classmethod
    def shortest_path_between(cls, sources, targets, cluster_edges,
                              edge_vertices, vertex_positions, edge_angles):
        """
        Dijkstra from one boundary loop to another, over cluster edges only.

        Seeding the queue with every source vertex at once is a multi-source
        search: it finds the shortest connection between the two loops rather
        than between two arbitrary points on them.

        Returns the set of edge indices on the path, or an empty set.
        """
        if not sources or not targets:
            return set()

        # Adjacency restricted to the cluster, so the path cannot escape it.
        graph = {}
        for eidx in cluster_edges:
            pair = edge_vertices[eidx]
            if len(pair) != 2:
                continue

            a, b = pair
            pa = vertex_positions[a] if a < len(vertex_positions) else (0.0, 0.0, 0.0)
            pb = vertex_positions[b] if b < len(vertex_positions) else (0.0, 0.0, 0.0)

            length = math.sqrt(
                (pa[0] - pb[0]) ** 2 + (pa[1] - pb[1]) ** 2 + (pa[2] - pb[2]) ** 2
            )

            # A flat edge costs more than a creased one of the same length, so
            # the cut drifts into whatever crease is available instead of
            # running straight across a smooth surface where it would show.
            angle = edge_angles.get(eidx, 0.0)
            flatness = 1.0 - min(1.0, angle / 90.0)
            cost = max(1e-9, length) * (1.0 + cls.CREASE_PREFERENCE * flatness)

            graph.setdefault(a, []).append((b, cost, eidx))
            graph.setdefault(b, []).append((a, cost, eidx))

        target_set = set(targets)
        dist = {}
        came_from = {}
        queue = []

        for vi in sources:
            dist[vi] = 0.0
            heapq.heappush(queue, (0.0, vi))

        reached = None

        while queue:
            d, vi = heapq.heappop(queue)

            if d > dist.get(vi, float("inf")):
                continue

            if vi in target_set:
                reached = vi
                break

            for nb, cost, eidx in graph.get(vi, ()):
                nd = d + cost
                if nd < dist.get(nb, float("inf")):
                    dist[nb] = nd
                    came_from[nb] = (vi, eidx)
                    heapq.heappush(queue, (nd, nb))

        if reached is None:
            return set()

        path = set()
        node = reached
        while node in came_from:
            prev, eidx = came_from[node]
            path.add(eidx)
            node = prev

        return path


def plan_seams(mesh_analysis, material_analysis, settings):
    """
    Full VSA pipeline: cluster, take cluster borders as seams, then open any
    cluster that is topologically not a disc.

    Returns a VSAResult.
    """
    result = VSAResult()

    face_count = getattr(mesh_analysis, "face_count", 0)
    edge_count = getattr(mesh_analysis, "edge_count", 0)
    faces_per_edge = getattr(mesh_analysis, "faces_per_edge", None) or []
    face_normals = getattr(mesh_analysis, "face_normals", None) or []

    if face_count == 0 or not faces_per_edge or not face_normals:
        result.errors.append("VSA needs face normals and edge connectivity.")
        return result

    face_vertices = getattr(mesh_analysis, "face_vertices", None) or []
    edges_per_face = getattr(mesh_analysis, "edges_per_face", None) or []
    edge_vertices = getattr(mesh_analysis, "edge_vertices", None) or []
    vertex_positions = getattr(mesh_analysis, "vertex_positions", None) or []

    try:
        tolerance = float(getattr(settings, "vsa_max_angle_deviation", 25.0) or 25.0)
    except (TypeError, ValueError):
        tolerance = 25.0

    area_weighted = bool(getattr(settings, "vsa_area_weighted", True))

    # Clustering must not cross what the user already decided.
    blocked = set()
    if bool(getattr(settings, "separate_by_material", True)):
        blocked.update(
            getattr(material_analysis, "material_boundary_edges", set()) or set()
        )
    if bool(getattr(settings, "preserve_existing_seams", True)):
        blocked.update(getattr(mesh_analysis, "existing_seams", set()) or set())

    try:
        target = int(getattr(settings, "vsa_target_clusters", 0) or 0)
    except (TypeError, ValueError):
        target = 0

    try:
        iterations = int(getattr(settings, "vsa_iterations", 6) or 0)
    except (TypeError, ValueError):
        iterations = 6
    iterations = max(0, min(50, iterations))

    if target > 0:
        # The island count is the control; the tolerance becomes whatever the
        # partition settles on.
        face_cluster, cluster_count = VSAClusterer.cluster_to_target(
            mesh_analysis, target,
            iterations=iterations,
            area_weighted=area_weighted,
            blocked_edges=blocked,
        )
        result.info.append(f"Seeded {cluster_count} clusters for a target of {target}.")
    else:
        face_cluster, cluster_count = VSAClusterer.cluster(
            mesh_analysis,
            max_angle_deviation=tolerance,
            area_weighted=area_weighted,
            blocked_edges=blocked,
        )

        # One growing pass is order-dependent: a face joins whichever cluster
        # reached it first. Lloyd lets faces change hands until the partition
        # stops moving.
        if iterations and cluster_count > 1:
            face_cluster, used = VSAClusterer.refine(
                mesh_analysis, face_cluster, cluster_count,
                iterations=iterations,
                area_weighted=area_weighted,
                blocked_edges=blocked,
            )
            result.lloyd_iterations = used

    try:
        smooth_passes = int(getattr(settings, "vsa_smooth_passes", 3) or 0)
    except (TypeError, ValueError):
        smooth_passes = 3

    if smooth_passes > 0 and cluster_count > 1:
        face_cluster, moved = VSAClusterer.smooth_boundaries(
            mesh_analysis, face_cluster, cluster_count,
            passes=smooth_passes,
            crease_weight=float(getattr(settings, "vsa_crease_weight", 1.0) or 0.0),
        )
        result.boundary_moves = moved

    try:
        min_cluster = int(getattr(settings, "vsa_min_cluster_faces", 3) or 0)
    except (TypeError, ValueError):
        min_cluster = 3

    if min_cluster > 1 and cluster_count > 1:
        face_cluster, cluster_count, absorbed = (
            VSAClusterer.absorb_micro_clusters(
                mesh_analysis, face_cluster, cluster_count,
                min_faces=min_cluster,
                # A sliver may only join a neighbour it genuinely resembles.
                max_deviation=max(15.0, tolerance * 1.5),
            )
        )
        result.absorbed_clusters = absorbed

    result.face_cluster = face_cluster
    result.cluster_count = cluster_count

    is_seam = [False] * edge_count

    # Stage 1 seams: every edge between two different clusters.
    for eidx, face_list in enumerate(faces_per_edge):
        if eidx >= edge_count:
            break

        if len(face_list) == 2:
            f1, f2 = face_list
            if (0 <= f1 < face_count and 0 <= f2 < face_count
                    and face_cluster[f1] != face_cluster[f2]):
                is_seam[eidx] = True

    for eidx in blocked:
        if 0 <= eidx < edge_count:
            is_seam[eidx] = True

    result.boundary_seam_count = sum(1 for f in is_seam if f)

    # Stage 2: open clusters that are not discs.
    if bool(getattr(settings, "vsa_resolve_topology", True)):
        if not (face_vertices and edges_per_face and edge_vertices
                and vertex_positions):
            result.warnings.append(
                "Topology resolution skipped: per-face vertex or edge data is "
                "unavailable on this mesh."
            )
        else:
            # Dihedral angle per edge, computed once for the path costs.
            edge_angles = {}
            for eidx, face_list in enumerate(faces_per_edge):
                if len(face_list) == 2:
                    f1, f2 = face_list
                    if 0 <= f1 < len(face_normals) and 0 <= f2 < len(face_normals):
                        edge_angles[eidx] = angle_between_degrees(
                            face_normals[f1], face_normals[f2]
                        )

            clusters = {}
            for fidx, cid in enumerate(face_cluster):
                if cid >= 0:
                    clusters.setdefault(cid, []).append(fidx)

            for cid, faces in clusters.items():
                if len(faces) < 4:
                    # Too small to be a ring; a triangle cannot enclose a hole.
                    result.discs += 1
                    continue

                chi, _verts, edges = TopologyResolver.euler_characteristic(
                    faces, face_vertices, edges_per_face
                )

                if chi >= 1:
                    result.discs += 1
                    continue

                result.non_discs += 1

                loops = TopologyResolver.boundary_loops(
                    edges, faces, faces_per_edge, edge_vertices
                )

                if len(loops) < 2:
                    result.warnings.append(
                        f"Cluster {cid} has Euler characteristic {chi} but "
                        f"{len(loops)} boundary loop(s); it may be closed, and "
                        "no path can be cut between loops."
                    )
                    continue

                # Two largest loops: on a cylinder band these are the two rims.
                loops.sort(key=len, reverse=True)

                def verts_of(loop):
                    out = set()
                    for eidx in loop:
                        out.update(edge_vertices[eidx])
                    return out

                sources = verts_of(loops[0])
                targets = verts_of(loops[1])

                interior = [
                    eidx for eidx in edges
                    if eidx not in loops[0] and eidx not in loops[1]
                ]

                path = TopologyResolver.shortest_path_between(
                    sources, targets, interior, edge_vertices,
                    vertex_positions, edge_angles,
                )

                if not path:
                    result.warnings.append(
                        f"Cluster {cid} is a ring but no path was found between "
                        "its boundary loops."
                    )
                    continue

                for eidx in path:
                    if not is_seam[eidx]:
                        is_seam[eidx] = True
                        result.topology_seam_count += 1

                result.rings_resolved += 1

    result.is_seam = is_seam
    result.seam_edges = {i for i, flag in enumerate(is_seam) if flag}

    detail = []
    if result.lloyd_iterations:
        detail.append(f"{result.lloyd_iterations} refinement passes")
    if result.boundary_moves:
        detail.append(f"{result.boundary_moves} border faces re-assigned")
    if result.absorbed_clusters:
        detail.append(f"{result.absorbed_clusters} slivers absorbed")

    result.info.append(
        f"VSA: {cluster_count} clusters, {result.boundary_seam_count} border seams"
        + (" (" + ", ".join(detail) + ")" if detail else "")
        + "."
    )

    if result.non_discs:
        result.info.append(
            f"Topology: {result.discs} discs, {result.non_discs} non-discs, "
            f"{result.rings_resolved} rings opened with "
            f"{result.topology_seam_count} path seams."
        )

    result.ok = True
    return result
