"""Analyze face regions on a virtually cut surface without modifying the mesh."""

from dataclasses import dataclass
import heapq
import math
import operator


@dataclass(frozen=True)
class RegionTopology:
    """Topological invariants of one edge-connected face region."""

    face_indices: tuple
    boundary_count: int
    euler_characteristic: int
    genus: object
    is_disk: bool
    supported: bool


class _DisjointSet:
    def __init__(self, size):
        self.parent = list(range(size))
        self.rank = [0] * size

    def find(self, item):
        while self.parent[item] != item:
            self.parent[item] = self.parent[self.parent[item]]
            item = self.parent[item]
        return item

    def union(self, left, right):
        left, right = self.find(left), self.find(right)
        if left == right:
            return
        if self.rank[left] < self.rank[right]:
            left, right = right, left
        self.parent[right] = left
        if self.rank[left] == self.rank[right]:
            self.rank[left] += 1


def analyze_regions(mesh, seam_mask):
    """Return region invariants using corner sectors and virtual edge copies.

    The mask is indexed by mesh edge index, independently of actual seam flags.
    Non-manifold input and non-orientable regions are marked unsupported; their
    genus is unknown. Loose edges and vertices do not belong to face regions.
    Storage is linear in mesh edges, faces and corners. Union/find operations
    have amortized inverse-Ackermann complexity.
    """
    mask = tuple(bool(value) for value in seam_mask)
    if len(mask) != len(mesh.edges):
        raise ValueError("The seam mask must contain one value per mesh edge")

    faces = list(mesh.polygons)
    incidence = [[] for _ in mesh.edges]
    corners = []
    face_corners = []
    bad_faces = set()
    for face_index, face in enumerate(faces):
        loops = list(face.loop_indices)
        ids = list(range(len(corners), len(corners) + len(loops)))
        face_corners.append(ids)
        vertices = [mesh.loops[index].vertex_index for index in loops]
        if len(vertices) < 3 or len(set(vertices)) != len(vertices):
            bad_faces.add(face_index)
        corners.extend(vertices)
        for offset, loop_index in enumerate(loops):
            start = ids[offset]
            end = ids[(offset + 1) % len(ids)]
            edge_index = mesh.loops[loop_index].edge_index
            incidence[edge_index].append((face_index, start, end))
            if (corners[start] == corners[end] or
                    set(mesh.edges[edge_index].vertices) !=
                    {corners[start], corners[end]}):
                bad_faces.add(face_index)

    regions = _DisjointSet(len(faces))
    sectors = _DisjointSet(len(corners))
    original_sectors = _DisjointSet(len(corners))
    adjacency = [[] for _ in faces]
    boundary = []
    glued_edges = []
    for edge_index, sides in enumerate(incidence):
        if not sides:
            continue
        if not mask[edge_index]:
            for side in sides[1:]:
                regions.union(sides[0][0], side[0])
        if len(sides) > 2:
            bad_faces.update(side[0] for side in sides)
        if len(sides) == 2:
            (first, a, b), (second, c, d) = sides
            if first == second:
                bad_faces.add(first)
            same_direction = corners[a] == corners[c]
            pairs = ((a, c), (b, d)) if same_direction else ((a, d), (b, c))
            for left, right in pairs:
                original_sectors.union(left, right)
            if not mask[edge_index]:
                for left, right in pairs:
                    sectors.union(left, right)
                adjacency[first].append((second, int(same_direction)))
                adjacency[second].append((first, int(same_direction)))
                glued_edges.append(first)
                continue
        boundary.extend(sides)

    # Detect disconnected original vertex fans, even when cuts separate faces.
    vertex_fans = {}
    for corner, vertex in enumerate(corners):
        vertex_fans.setdefault(vertex, set()).add(original_sectors.find(corner))
    singular_vertices = {vertex for vertex, fans in vertex_fans.items()
                         if len(fans) != 1}
    for face_index, ids in enumerate(face_corners):
        if any(corners[corner] in singular_vertices for corner in ids):
            bad_faces.add(face_index)

    groups = {}
    for face_index in range(len(faces)):
        groups.setdefault(regions.find(face_index), []).append(face_index)
    vertices_by_region = {root: set() for root in groups}
    edges_by_region = {root: 0 for root in groups}
    boundary_by_region = {root: [] for root in groups}
    for face_index, ids in enumerate(face_corners):
        root = regions.find(face_index)
        vertices_by_region[root].update(sectors.find(corner) for corner in ids)
    for face_index in glued_edges:
        edges_by_region[regions.find(face_index)] += 1
    for face_index, start, end in boundary:
        root = regions.find(face_index)
        edges_by_region[root] += 1
        boundary_by_region[root].append((sectors.find(start), sectors.find(end)))

    result = []
    for root, indices in groups.items():
        supported = not any(index in bad_faces for index in indices)
        # Face winding may be inconsistent; solve orientation parity instead
        # of rejecting a surface solely because input normals disagree.
        orientation = {}
        for seed in indices:
            if seed in orientation:
                continue
            orientation[seed] = 0
            stack = [seed]
            while stack:
                face_index = stack.pop()
                for neighbor, parity in adjacency[face_index]:
                    expected = orientation[face_index] ^ parity
                    if neighbor in orientation:
                        if orientation[neighbor] != expected:
                            supported = False
                    else:
                        orientation[neighbor] = expected
                        stack.append(neighbor)

        boundary_graph = {}
        for start, end in boundary_by_region[root]:
            boundary_graph.setdefault(start, []).append(end)
            boundary_graph.setdefault(end, []).append(start)
        if any(len(neighbors) != 2 for neighbors in boundary_graph.values()):
            supported = False
        visited = set()
        boundary_count = 0
        for seed in boundary_graph:
            if seed in visited:
                continue
            boundary_count += 1
            visited.add(seed)
            stack = [seed]
            while stack:
                for neighbor in boundary_graph[stack.pop()]:
                    if neighbor not in visited:
                        visited.add(neighbor)
                        stack.append(neighbor)
        chi = len(vertices_by_region[root]) - edges_by_region[root] + len(indices)
        twice_genus = 2 - boundary_count - chi
        if twice_genus < 0 or twice_genus % 2:
            supported = False
        genus = twice_genus // 2 if supported else None
        result.append(RegionTopology(
            tuple(faces[index].index for index in indices), boundary_count,
            chi, genus, supported and boundary_count == 1 and genus == 0,
            supported))
    return result


@dataclass(frozen=True)
class BoundaryCutResult:
    """Completed virtual seam mask and regions that remain non-disks."""

    seam_mask: tuple
    added_edges: tuple
    unresolved_regions: tuple


@dataclass(frozen=True)
class _AnalysisPosition:
    coordinates: tuple

    def __sub__(self, other):
        return _AnalysisPosition(tuple(a - b for a, b in
                                       zip(self.coordinates, other.coordinates)))

    @property
    def length(self):
        return math.hypot(*self.coordinates)


@dataclass(frozen=True)
class _AnalysisVertex:
    co: _AnalysisPosition


@dataclass(frozen=True)
class _AnalysisEdge:
    vertices: tuple


@dataclass(frozen=True)
class _AnalysisLoop:
    vertex_index: int
    edge_index: int


@dataclass(frozen=True)
class _AnalysisFace:
    index: int
    loop_indices: tuple


@dataclass(frozen=True)
class _AnalysisMesh:
    vertices: tuple
    edges: tuple
    loops: tuple
    polygons: tuple


def _analysis_mesh_view(analysis):
    """Copy validated analysis arrays into an immutable mesh protocol view."""
    counts = tuple(operator.index(getattr(analysis, name)) for name in
                   ('vertex_count', 'edge_count', 'face_count'))
    if any(count < 0 for count in counts):
        raise ValueError("Negative analysis counts")
    vertex_count, edge_count, face_count = counts

    def indices(values, bound):
        result = tuple(operator.index(value) for value in values)
        if any(value < 0 or value >= bound for value in result):
            raise ValueError("Analysis index out of range")
        return result

    positions = tuple(tuple(float(value) for value in position)
                      for position in analysis.vertex_positions)
    edges = tuple(indices(pair, vertex_count) for pair in analysis.edge_vertices)
    faces = tuple(indices(face, vertex_count) for face in analysis.face_vertices)
    face_edges = tuple(indices(items, edge_count) for items in analysis.edges_per_face)
    edge_faces = tuple(indices(items, face_count) for items in analysis.faces_per_edge)
    if (len(positions) != vertex_count or len(edges) != edge_count or
            len(faces) != face_count or len(face_edges) != face_count or
            len(edge_faces) != edge_count):
        raise ValueError("Inconsistent analysis array sizes")
    if any(len(position) != 3 or not all(map(math.isfinite, position))
           for position in positions):
        raise ValueError("Unsupported vertex positions")
    if any(len(pair) != 2 or pair[0] == pair[1] for pair in edges):
        raise ValueError("Unsupported edge endpoints")
    incidence = [[] for _ in edges]
    loops = []
    polygons = []
    for face_index, (vertices, members) in enumerate(zip(faces, face_edges)):
        if (len(vertices) < 3 or len(set(vertices)) != len(vertices) or
                len(members) != len(vertices) or len(set(members)) != len(members)):
            raise ValueError("Unsupported face corners")
        by_pair = {}
        for edge in members:
            pair = frozenset(edges[edge])
            if pair in by_pair:
                raise ValueError("Ambiguous face edge")
            by_pair[pair] = edge
        start = len(loops)
        for offset, vertex in enumerate(vertices):
            pair = frozenset((vertex, vertices[(offset + 1) % len(vertices)]))
            if pair not in by_pair:
                raise ValueError("Face corners and edges disagree")
            edge = by_pair[pair]
            loops.append(_AnalysisLoop(vertex, edge))
            incidence[edge].append(face_index)
        polygons.append(_AnalysisFace(face_index, tuple(range(start, len(loops)))))
    if any(sorted(actual) != sorted(expected)
           for actual, expected in zip(incidence, edge_faces)):
        raise ValueError("Face and edge incidence disagree")
    return _AnalysisMesh(
        tuple(_AnalysisVertex(_AnalysisPosition(position)) for position in positions),
        tuple(_AnalysisEdge(pair) for pair in edges), tuple(loops), tuple(polygons))


def complete_analysis_boundary_cuts(mesh_analysis, seam_mask):
    """Complete cuts from analysis arrays without changing analysis or seams.

    Invalid or unavailable geometry leaves the mask unchanged and reports all
    faces as one unsupported unresolved region. Mask size errors raise ValueError.
    Valid topology uses the same completion algorithm as a Blender mesh.
    """
    mask = tuple(bool(value) for value in seam_mask)
    if len(mask) != mesh_analysis.edge_count:
        raise ValueError("The seam mask must contain one value per analysis edge")
    try:
        mesh = _analysis_mesh_view(mesh_analysis)
    except (AttributeError, TypeError, ValueError, OverflowError):
        region = RegionTopology(tuple(range(mesh_analysis.face_count)),
                                0, 0, None, False, False)
        return BoundaryCutResult(mask, (), (region,))
    return complete_boundary_cuts(mesh, mask)


def _boundary_path(mesh, mask, region):
    """Find a shortest boundary bridge in the region's cut-corner graph."""
    wanted = set(region.face_indices)
    corners = []
    incidence = {}
    for face in mesh.polygons:
        if face.index not in wanted:
            continue
        loops = list(face.loop_indices)
        ids = list(range(len(corners), len(corners) + len(loops)))
        corners.extend(mesh.loops[index].vertex_index for index in loops)
        for offset, loop in enumerate(loops):
            edge = mesh.loops[loop].edge_index
            incidence.setdefault(edge, []).append(
                (ids[offset], ids[(offset + 1) % len(ids)]))
    sectors = _DisjointSet(len(corners))
    for edge, sides in incidence.items():
        if not mask[edge] and len(sides) == 2:
            (a, b), (c, d) = sides
            pairs = ((a, c), (b, d)) if corners[a] == corners[c] else ((a, d), (b, c))
            for left, right in pairs:
                sectors.union(left, right)

    boundary = {}
    graph = {}
    for edge, sides in sorted(incidence.items()):
        if mask[edge] or len(sides) != 2:
            for a, b in sides:
                a, b = sectors.find(a), sectors.find(b)
                boundary.setdefault(a, []).append(b)
                boundary.setdefault(b, []).append(a)
            continue
        a, b = (sectors.find(corner) for corner in sides[0])
        left, right = mesh.edges[edge].vertices
        length = float((mesh.vertices[left].co - mesh.vertices[right].co).length)
        if not math.isfinite(length):
            continue
        weight = max(length, 1e-12)
        graph.setdefault(a, []).append((b, edge, weight))
        graph.setdefault(b, []).append((a, edge, weight))

    components = []
    visited = set()
    for seed in sorted(boundary):
        if seed in visited:
            continue
        component = {seed}
        visited.add(seed)
        stack = [seed]
        while stack:
            for neighbor in boundary[stack.pop()]:
                if neighbor not in visited:
                    visited.add(neighbor)
                    component.add(neighbor)
                    stack.append(neighbor)
        components.append(component)
    if len(components) < 2:
        return ()
    targets = set().union(*components[1:])
    distances = {node: 0.0 for node in components[0]}
    queue = [(0.0, node) for node in sorted(components[0])]
    heapq.heapify(queue)
    previous = {}
    while queue:
        distance, node = heapq.heappop(queue)
        if distance != distances[node]:
            continue
        if node in targets:
            path = []
            while node in previous:
                node, edge = previous[node]
                path.append(edge)
            return tuple(reversed(path))
        for neighbor, edge, weight in sorted(graph.get(node, ())):
            candidate = distance + weight
            if candidate < distances.get(neighbor, math.inf):
                distances[neighbor] = candidate
                previous[neighbor] = (node, edge)
                heapq.heappush(queue, (candidate, neighbor))
    return ()


def complete_boundary_cuts(mesh, seam_mask):
    """Join boundary loops of supported genus-zero regions without mutation.

    Each accepted bridge must preserve the face region and reduce its boundary
    count on reanalysis. At least one new seam is required per iteration, so
    the edge count bounds completion. Closed and unsupported regions are left
    unchanged and reported alongside any other remaining non-disks.
    """
    original = tuple(bool(value) for value in seam_mask)
    mask = original
    regions = analyze_regions(mesh, mask)
    for _ in range(len(mesh.edges)):
        accepted = False
        for region in regions:
            if not region.supported or region.genus != 0 or region.boundary_count <= 1:
                continue
            path = _boundary_path(mesh, mask, region)
            if not path or not any(not mask[edge] for edge in path):
                continue
            candidate = list(mask)
            for edge in path:
                candidate[edge] = True
            candidate = tuple(candidate)
            analyzed = analyze_regions(mesh, candidate)
            affected = [item for item in analyzed
                        if set(item.face_indices) & set(region.face_indices)]
            if (len(affected) == 1 and
                    affected[0].face_indices == region.face_indices and
                    affected[0].supported and affected[0].genus == 0 and
                    affected[0].boundary_count < region.boundary_count):
                mask, regions = candidate, analyzed
                accepted = True
                break
        if not accepted:
            break
    return BoundaryCutResult(
        mask, tuple(edge for edge, value in enumerate(mask)
                    if value and not original[edge]),
        tuple(region for region in regions if not region.is_disk))
