# pylint: disable=invalid-name
"""
Intelligent UV Mapping — MESH ANALYZER

Topology and geometry analysis, with a bmesh-first strategy.
"""

try:
    import bmesh
except Exception:  # pragma: no cover - bmesh ships with Blender
    bmesh = None

try:
    import numpy as np
except Exception:  # pragma: no cover - numpy is normally present in Blender
    np = None

import array

from .utils import loop_edge_index, polygon_loop_range


# =============================================================================
# 4. MESH ANALYZER — Basic Geometric Analysis
# =============================================================================

class MeshAnalysisResult:
    """Result of the mesh geometric analysis."""

    def __init__(self):
        self.ok = False
        self.errors = []
        self.warnings = []

        self.vertex_count = 0
        self.edge_count = 0
        self.face_count = 0
        self.total_area = 0.0

        # Per-face arrays
        self.face_areas = []
        self.face_normals = []
        # Face centres, needed to tell a convex edge from a concave one:
        # the normals alone give an unsigned angle.
        self.face_centers = []
        self.component_ids = []

        # Optional numpy Nx3 float64 copy of face_normals, kept so the
        # curvature estimator and the seam planner can vectorize the dihedral
        # angle maths instead of running it per edge in Python. None when
        # numpy is unavailable; consumers must handle both.
        self.face_normals_np = None

        # Per-edge arrays
        self.edge_lengths = []
        # Vertex pair per edge, needed to walk the seam network.
        self.edge_vertices = []
        # Seams already on the mesh when the run started: user-authored cuts
        # that must survive the planner instead of being overwritten.
        self.existing_seams = set()

        # Needed by the VSA clusterer and the topology resolver: the Euler
        # characteristic needs vertex and edge sets per cluster, and Dijkstra
        # needs real positions to weigh a path by length.
        self.face_vertices = []
        self.vertex_positions = []
        self.edges_per_face = []
        self.faces_per_edge = []
        self.boundary_edges = set()
        self.non_manifold_edges = set()

        self.component_count = 0

        # Which API path produced the topology, and how many edges link 2 faces
        self.topology_source = "unknown"
        self.manifold_edge_count = 0


class MeshAnalyzer:
    """Analyzes the topology and basic geometric metrics of the mesh."""

    @staticmethod
    def _vectorized_float_array(size, default=0.0):
        """Creates a float buffer compatible with Blender `foreach_get`."""
        if np is not None:
            return np.empty(size, dtype=np.float32)

        return array.array('f', [float(default)] * size)

    @staticmethod
    def _vectorized_int_array(size, default=0):
        """Creates an int buffer compatible with Blender `foreach_get`."""
        if np is not None:
            return np.empty(size, dtype=np.int32)

        return array.array('i', [int(default)] * size)

    @staticmethod
    def _vectorized_to_float_list(values, size=None):
        """Converts a `foreach_get` buffer to a plain Python float list."""
        if size is None:
            size = len(values)

        if np is not None and isinstance(values, np.ndarray):
            return [float(x) for x in values[:size].astype(np.float64)]

        return [float(values[i]) for i in range(size)]

    @staticmethod
    def _vectorized_normals_to_tuples(values, face_count):
        """
        Converts a flat normal buffer to the list-of-tuples shape expected by
        the rest of the pipeline.

        This conversion is deliberate: seam planning, curvature and region
        merging consume `face_normals` as tuples.
        """
        normals = []

        if np is not None and isinstance(values, np.ndarray):
            # reshape + tolist + tuple() is several times faster than
            # converting element by element through float().
            flat = values[:face_count * 3].astype(np.float64).reshape(face_count, 3)
            return [tuple(row) for row in flat.tolist()]

        for i in range(face_count):
            normals.append((
                float(values[i * 3]),
                float(values[i * 3 + 1]),
                float(values[i * 3 + 2]),
            ))

        return normals

    @staticmethod
    def _fill_geometry_vectorized(mesh, result):
        """
        Reads face areas, face normals and edge lengths with `foreach_get`.

        This path is intentionally limited to geometry. Edge-to-face
        connectivity is still read through bmesh because there is no practical
        `foreach_get` equivalent for `edge.link_faces`.
        """
        polygons = getattr(mesh, "polygons", None)
        vertices = getattr(mesh, "vertices", None)
        edges = getattr(mesh, "edges", None)

        if polygons is None or vertices is None or edges is None:
            return False

        if not hasattr(polygons, "foreach_get"):
            return False
        if not hasattr(vertices, "foreach_get"):
            return False
        if not hasattr(edges, "foreach_get"):
            return False

        try:
            face_count = len(polygons)
            edge_count = len(edges)
            vertex_count = len(vertices)
        except Exception:
            return False

        if face_count == 0 or edge_count == 0:
            return False

        try:
            areas = MeshAnalyzer._vectorized_float_array(face_count)
            normals = MeshAnalyzer._vectorized_float_array(face_count * 3)
            vertex_coords = MeshAnalyzer._vectorized_float_array(vertex_count * 3)
            edge_vertices = MeshAnalyzer._vectorized_int_array(edge_count * 2)

            polygons.foreach_get("area", areas)
            polygons.foreach_get("normal", normals)
            vertices.foreach_get("co", vertex_coords)
            edges.foreach_get("vertices", edge_vertices)

            face_areas = MeshAnalyzer._vectorized_to_float_list(areas, face_count)
            face_normals = MeshAnalyzer._vectorized_normals_to_tuples(normals, face_count)

            # Keep the numpy copy around: the curvature estimator and the seam
            # planner vectorize their angle maths on it.
            if np is not None and isinstance(normals, np.ndarray):
                result.face_normals_np = (
                    normals[:face_count * 3].astype(np.float64).reshape(face_count, 3)
                )

            # Face centres are deliberately NOT read through foreach_get.
            # `area` and `normal` are cross-checked against bmesh and agree, but
            # `center` is a computed property with no such confirmation: if RNA
            # reports a different element count than the buffer allocated here,
            # Blender writes past the end and corrupts the heap, which crashes
            # the process instead of raising. analyze() fills them in from
            # `poly.center` afterwards, which costs a loop and cannot overflow.
            face_centers = []

            if np is not None and isinstance(vertex_coords, np.ndarray):
                coords = vertex_coords[:vertex_count * 3].astype(np.float64).reshape(
                    vertex_count,
                    3,
                )
                edge_idx = edge_vertices[:edge_count * 2].astype(np.int64)
                v0 = edge_idx[0::2]
                v1 = edge_idx[1::2]

                p0 = coords[v0]
                p1 = coords[v1]
                diff = p0 - p1
                edge_lengths = np.sqrt(np.sum(diff * diff, axis=1))
                edge_lengths = [float(x) for x in edge_lengths.astype(np.float64)]
            else:
                edge_lengths = [0.0] * edge_count

                for eidx in range(edge_count):
                    try:
                        v0 = int(edge_vertices[eidx * 2])
                        v1 = int(edge_vertices[eidx * 2 + 1])

                        x0 = float(vertex_coords[v0 * 3])
                        y0 = float(vertex_coords[v0 * 3 + 1])
                        z0 = float(vertex_coords[v0 * 3 + 2])

                        x1 = float(vertex_coords[v1 * 3])
                        y1 = float(vertex_coords[v1 * 3 + 1])
                        z1 = float(vertex_coords[v1 * 3 + 2])

                        dx = x0 - x1
                        dy = y0 - y1
                        dz = z0 - z1
                        edge_lengths[eidx] = float((dx * dx + dy * dy + dz * dz) ** 0.5)
                    except Exception:
                        edge_lengths[eidx] = 0.0

            total_area = 0.0
            for area in face_areas:
                total_area += float(area)

            result.vertex_count = vertex_count
            result.edge_count = edge_count
            result.face_count = face_count
            result.face_areas = face_areas
            result.face_normals = face_normals
            result.face_centers = face_centers
            result.total_area = float(total_area)
            result.edge_lengths = edge_lengths

            return True

        except Exception as exc:
            result.warnings.append(f"Vectorized geometry read failed: {exc}")
            return False

    @staticmethod
    def _build_faces_per_edge_bmesh(mesh, edge_count, result):
        """
        Builds edge -> face connectivity from bmesh.

        Returns `(faces_per_edge, linked_pairs)` on success, or `(None, 0)`
        when bmesh cannot be used.
        """
        bm = None

        if bmesh is None:
            return None, 0

        try:
            bm = bmesh.new()
            bm.from_mesh(mesh)

            bm.faces.ensure_lookup_table()
            bm.edges.ensure_lookup_table()
            bm.faces.index_update()
            bm.edges.index_update()

            faces_per_edge = [[] for _ in range(edge_count)]
            linked_pairs = 0

            for edge in bm.edges:
                eidx = edge.index
                if not (0 <= eidx < edge_count):
                    continue

                linked = [face.index for face in edge.link_faces]
                faces_per_edge[eidx] = list(dict.fromkeys(linked))

                if len(faces_per_edge[eidx]) == 2:
                    linked_pairs += 1

            return faces_per_edge, linked_pairs

        except Exception as exc:
            result.warnings.append(f"bmesh connectivity unavailable: {exc}")
            return None, 0

        finally:
            if bm is not None:
                try:
                    bm.free()
                except Exception:
                    # A: freeing a bmesh that Blender already reclaimed raises rather
                    # than returning; there is nothing left to do about it either way.
                    pass

    @staticmethod
    def _analyze_vectorized(mesh, result):
        """
        Fast path: vectorized geometry reads plus bmesh topology.

        Returns True when both the geometry and the edge-to-face topology were
        read successfully.
        """
        if not MeshAnalyzer._fill_geometry_vectorized(mesh, result):
            return False

        faces_per_edge, linked_pairs = MeshAnalyzer._build_faces_per_edge_bmesh(
            mesh,
            result.edge_count,
            result,
        )

        if faces_per_edge is None:
            return False

        # A closed mesh must have interior edges. If nothing links two faces,
        # the topology read failed and the caller should try another path.
        if linked_pairs == 0 and result.face_count > 1:
            return False

        result.faces_per_edge = faces_per_edge
        return True

    @staticmethod
    def _analyze_with_bmesh(mesh, result):
        """
        Primary analysis path, built on bmesh.

        bmesh has been stable across Blender releases, while the direct mesh
        attributes (`MeshLoop.edge_index`, `MeshPolygon.loop_total`, ...) have
        been reshaped several times. Populates areas, normals, edge lengths and
        edge->face connectivity in a single traversal.

        Returns True when the topology was read successfully.
        """
        bm = None

        if bmesh is None:
            return False

        try:
            bm = bmesh.new()
            bm.from_mesh(mesh)

            bm.verts.ensure_lookup_table()
            bm.edges.ensure_lookup_table()
            bm.faces.ensure_lookup_table()
            bm.faces.index_update()
            bm.edges.index_update()

            face_count = len(bm.faces)
            edge_count = len(bm.edges)

            if face_count == 0 or edge_count == 0:
                return False

            face_areas = [0.0] * face_count
            face_normals = [(0.0, 1.0, 0.0)] * face_count
            face_centers = [(0.0, 0.0, 0.0)] * face_count
            face_vertices = [()] * face_count
            edges_per_face = [()] * face_count
            total_area = 0.0

            for face in bm.faces:
                idx = face.index
                if not (0 <= idx < face_count):
                    continue

                try:
                    area = float(face.calc_area())
                except Exception:
                    area = 0.0

                try:
                    normal = tuple(float(x) for x in face.normal)
                except Exception:
                    normal = (0.0, 1.0, 0.0)

                try:
                    face_centers[idx] = tuple(
                        float(x) for x in face.calc_center_median()
                    )
                except Exception:
                    face_centers[idx] = (0.0, 0.0, 0.0)

                try:
                    face_vertices[idx] = tuple(v.index for v in face.verts)
                    edges_per_face[idx] = tuple(e.index for e in face.edges)
                except Exception:
                    face_vertices[idx] = ()
                    edges_per_face[idx] = ()

                face_areas[idx] = area
                face_normals[idx] = normal
                total_area += area

            edge_lengths = [0.0] * edge_count
            edge_vertices = [()] * edge_count
            faces_per_edge = [[] for _ in range(edge_count)]
            linked_pairs = 0

            for edge in bm.edges:
                eidx = edge.index
                if not (0 <= eidx < edge_count):
                    continue

                try:
                    edge_lengths[eidx] = float(edge.calc_length())
                except Exception:
                    edge_lengths[eidx] = 0.0

                try:
                    edge_vertices[eidx] = tuple(v.index for v in edge.verts)
                except Exception:
                    edge_vertices[eidx] = ()

                linked = [f.index for f in edge.link_faces]
                faces_per_edge[eidx] = list(dict.fromkeys(linked))

                if len(faces_per_edge[eidx]) == 2:
                    linked_pairs += 1

            # A closed mesh must have interior edges. If nothing links two
            # faces, the read failed and the caller should try another path.
            if linked_pairs == 0 and face_count > 1:
                return False

            result.face_count = face_count
            result.edge_count = edge_count
            result.vertex_count = len(bm.verts)
            result.face_areas = face_areas
            result.face_normals = face_normals
            result.face_centers = face_centers
            result.face_vertices = face_vertices
            result.edges_per_face = edges_per_face
            result.vertex_positions = [
                tuple(float(x) for x in v.co) for v in bm.verts
            ]
            result.total_area = total_area
            result.edge_lengths = edge_lengths
            result.edge_vertices = edge_vertices
            result.faces_per_edge = faces_per_edge

            return True

        except Exception as exc:
            result.warnings.append(f"bmesh analysis unavailable: {exc}")
            return False

        finally:
            if bm is not None:
                try:
                    bm.free()
                except Exception:
                    # A: freeing a bmesh that Blender already reclaimed raises rather
                    # than returning; there is nothing left to do about it either way.
                    pass

    @staticmethod
    def _build_faces_per_edge(mesh, edge_count, result):
        """
        Builds the edge -> faces connectivity.

        Primary path uses mesh loops (fast, O(loops)). If that yields nothing
        (unexpected API shape), falls back to a vertex-pair lookup so the rest
        of the pipeline still has usable topology.
        """
        faces_per_edge = [[] for _ in range(edge_count)]
        loops = getattr(mesh, "loops", [])
        polygons = getattr(mesh, "polygons", [])
        assigned = 0

        try:
            for poly in polygons:
                start, end = polygon_loop_range(poly)
                for i in range(start, end):
                    if i >= len(loops):
                        break

                    eidx = loop_edge_index(loops[i])
                    if 0 <= eidx < edge_count:
                        faces_per_edge[eidx].append(poly.index)
                        assigned += 1
        except Exception as exc:
            result.warnings.append(f"Loop-based connectivity failed: {exc}")

        if assigned > 0:
            return faces_per_edge

        # Fallback: map each polygon edge (vertex pair) to its mesh edge index.
        result.warnings.append(
            "Loop-based connectivity unavailable: using the vertex-pair fallback."
        )
        faces_per_edge = [[] for _ in range(edge_count)]

        try:
            edge_lookup = {}
            for eidx, edge in enumerate(mesh.edges):
                try:
                    v1, v2 = (int(v) for v in list(edge.vertices)[:2])
                except Exception:
                    continue
                edge_lookup[(v1, v2)] = eidx
                edge_lookup[(v2, v1)] = eidx

            for poly in polygons:
                try:
                    verts = [int(v) for v in poly.vertices]
                except Exception:
                    continue

                n = len(verts)
                if n < 3:
                    continue

                for i in range(n):
                    eidx = edge_lookup.get((verts[i], verts[(i + 1) % n]))
                    if eidx is not None and 0 <= eidx < edge_count:
                        faces_per_edge[eidx].append(poly.index)
        except Exception as exc:
            result.warnings.append(f"Vertex-pair connectivity failed: {exc}")

        return faces_per_edge

    @staticmethod
    def analyze(mesh):
        result = MeshAnalysisResult()

        if not mesh:
            result.errors.append("Mesh data is invalid.")
            return result

        polygons = getattr(mesh, "polygons", [])
        if not hasattr(polygons, "__len__") or len(polygons) == 0:
            result.errors.append("The mesh has no faces.")
            return result

        # ------------------------------------------------------------------
        # Fast path: vectorized geometry + bmesh topology
        # ------------------------------------------------------------------
        used_vectorized = MeshAnalyzer._analyze_vectorized(mesh, result)
        used_bmesh = False

        if not used_vectorized:
            # --------------------------------------------------------------
            # Primary topology path: bmesh (stable across Blender versions)
            # --------------------------------------------------------------
            used_bmesh = MeshAnalyzer._analyze_with_bmesh(mesh, result)

            if not used_bmesh:
                result.warnings.append(
                    "bmesh path unavailable: falling back to direct mesh attributes."
                )
                MeshAnalyzer._analyze_direct(mesh, result)

        if used_vectorized:
            result.topology_source = "vectorized"
        else:
            result.topology_source = "bmesh" if used_bmesh else "direct"

        if result.face_count == 0:
            result.errors.append("The mesh has no faces.")
            return result

        # VSA and the topology resolver need per-face vertex/edge sets and real
        # vertex positions. The vectorized and direct paths do not collect them,
        # so they are filled in here once rather than duplicated three times.
        if len(result.face_vertices) != result.face_count:
            fverts = [()] * result.face_count
            try:
                for idx, poly in enumerate(polygons):
                    fverts[idx] = tuple(int(v) for v in poly.vertices)
            except (AttributeError, TypeError) as exc:
                result.warnings.append(
                    f"Face vertex lists unavailable ({exc}): VSA is disabled."
                )
            result.face_vertices = fverts

        if len(result.vertex_positions) != result.vertex_count:
            positions = [(0.0, 0.0, 0.0)] * result.vertex_count
            try:
                for idx, vert in enumerate(getattr(mesh, "vertices", [])):
                    if idx >= result.vertex_count:
                        break
                    positions[idx] = tuple(float(x) for x in vert.co)
            except (AttributeError, TypeError) as exc:
                result.warnings.append(
                    f"Vertex positions unavailable ({exc}): path finding is disabled."
                )
            result.vertex_positions = positions

        if len(result.edges_per_face) != result.face_count:
            # Derived from the edge -> face map already built above, which is
            # O(E) rather than a second traversal of every face corner.
            per_face = [[] for _ in range(result.face_count)]
            for eidx, face_list in enumerate(result.faces_per_edge):
                for fidx in face_list:
                    if 0 <= fidx < result.face_count:
                        per_face[fidx].append(eidx)
            result.edges_per_face = [tuple(e) for e in per_face]

        # Seams the user put there by hand. The planner builds its own array
        # from scratch and the marker writes that array over every edge, so
        # without reading these first, a run silently deletes hand-placed cuts.
        if not result.existing_seams:
            existing = set()
            try:
                edges = getattr(mesh, "edges", [])
                for eidx, edge in enumerate(edges):
                    if getattr(edge, "use_seam", False):
                        existing.add(eidx)
            except (AttributeError, TypeError) as exc:
                result.warnings.append(
                    f"Existing seams could not be read ({exc}); hand-placed "
                    "seams may be lost."
                )
            result.existing_seams = existing

        # Face centres drive the convex/concave test in the seam planner. The
        # vectorized reader may not get them, so fill them in here rather than
        # leaving the planner blind.
        if len(result.edge_vertices) != result.edge_count:
            pairs = [()] * result.edge_count
            try:
                for eidx, edge in enumerate(getattr(mesh, "edges", [])):
                    if eidx >= result.edge_count:
                        break
                    pairs[eidx] = tuple(int(v) for v in list(edge.vertices)[:2])
            except (AttributeError, TypeError) as exc:
                result.warnings.append(
                    f"Edge vertex pairs unavailable ({exc}): seam pruning disabled."
                )
            result.edge_vertices = pairs

        if len(result.face_centers) != result.face_count:
            centers = [(0.0, 0.0, 0.0)] * result.face_count
            try:
                for idx, poly in enumerate(polygons):
                    center = getattr(poly, "center", None)
                    if center is not None and hasattr(center, "__iter__"):
                        centers[idx] = tuple(float(x) for x in center)
            except (AttributeError, TypeError) as exc:
                result.warnings.append(
                    f"Face centres unavailable ({exc}): seams cannot prefer concave edges."
                )
            result.face_centers = centers

        if result.total_area <= 0.0:
            result.warnings.append("The total area of the mesh is zero or invalid.")

        # ------------------------------------------------------------------
        # Boundary / non-manifold classification
        # ------------------------------------------------------------------
        manifold_edges = 0

        for eidx, face_list in enumerate(result.faces_per_edge):
            if len(face_list) < 2:
                result.boundary_edges.add(eidx)
            elif len(face_list) > 2:
                result.non_manifold_edges.add(eidx)
            else:
                manifold_edges += 1

        result.manifold_edge_count = manifold_edges

        if manifold_edges == 0 and result.face_count > 1:
            result.errors.append(
                "Edge/face connectivity could not be read from this mesh "
                f"(source: {result.topology_source}). "
                "No edge links two faces, so no seam can be detected. "
                "Run 'Diagnose Mesh API' and report the output."
            )
            return result

        # ------------------------------------------------------------------
        # Connected components on faces (union-find)
        #
        # The previous implementation built a full adjacency of Python sets
        # and flood-filled it: on dense meshes the set overhead dominated both
        # the time and the memory of the whole analysis. Union-find needs one
        # int list and runs in near-linear time.
        # ------------------------------------------------------------------
        face_count = result.face_count
        parent = list(range(face_count))

        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        for face_list in result.faces_per_edge:
            n = len(face_list)
            if n < 2:
                continue

            root = -1
            for fidx in face_list:
                if not (0 <= fidx < face_count):
                    continue
                if root < 0:
                    root = find(fidx)
                    continue
                other = find(fidx)
                if other != root:
                    parent[other] = root

        component_ids = [-1] * face_count
        remap = {}

        for fidx in range(face_count):
            root = find(fidx)
            cid = remap.get(root)
            if cid is None:
                cid = len(remap)
                remap[root] = cid
            component_ids[fidx] = cid

        result.component_ids = component_ids
        result.component_count = len(remap)

        # The bmesh and direct paths never set the numpy normals copy; build
        # it here so downstream vectorization works regardless of the source.
        if np is not None and result.face_normals_np is None and result.face_normals:
            try:
                result.face_normals_np = np.asarray(
                    result.face_normals, dtype=np.float64
                ).reshape(face_count, 3)
            except Exception:
                result.face_normals_np = None

        # ------------------------------------------------------------------
        # Light topological warnings
        # ------------------------------------------------------------------
        if result.boundary_edges:
            result.warnings.append(
                f"Detected {len(result.boundary_edges)} boundary edges."
            )

        if result.non_manifold_edges:
            result.warnings.append(
                f"Detected {len(result.non_manifold_edges)} non-manifold edges."
            )

        if not result.errors:
            result.ok = True

        return result

    @staticmethod
    def _analyze_direct(mesh, result):
        """Fallback path reading the mesh attributes directly."""
        vertices = getattr(mesh, "vertices", [])
        edges = getattr(mesh, "edges", [])
        polygons = getattr(mesh, "polygons", [])

        result.vertex_count = len(vertices) if hasattr(vertices, "__len__") else 0
        result.edge_count = len(edges) if hasattr(edges, "__len__") else 0
        result.face_count = len(polygons) if hasattr(polygons, "__len__") else 0

        if result.face_count == 0:
            return

        result.face_areas = [0.0] * result.face_count
        result.face_normals = [(0.0, 1.0, 0.0)] * result.face_count
        result.face_centers = [(0.0, 0.0, 0.0)] * result.face_count

        total_area = 0.0

        for idx, poly in enumerate(polygons):
            try:
                area = float(getattr(poly, "area", 0.0))
            except Exception:
                area = 0.0

            normal = getattr(poly, "normal", None)
            if normal is not None and hasattr(normal, "__iter__"):
                normal_tuple = tuple(float(x) for x in normal)
            else:
                normal_tuple = (0.0, 1.0, 0.0)

            center = getattr(poly, "center", None)
            if center is not None and hasattr(center, "__iter__"):
                result.face_centers[idx] = tuple(float(x) for x in center)

            result.face_areas[idx] = area
            result.face_normals[idx] = normal_tuple
            total_area += area

        result.total_area = total_area

        result.edge_lengths = []
        for edge in edges:
            try:
                v1_idx, v2_idx = list(edge.vertices)[:2]
                length = (vertices[v1_idx].co - vertices[v2_idx].co).length
            except Exception:
                length = 0.0

            result.edge_lengths.append(float(length))

        faces_per_edge = MeshAnalyzer._build_faces_per_edge(
            mesh, result.edge_count, result
        )

        for eidx in range(result.edge_count):
            faces_per_edge[eidx] = list(dict.fromkeys(faces_per_edge[eidx]))

        result.faces_per_edge = faces_per_edge
