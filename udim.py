# pylint: disable=invalid-name
"""
Intelligent UV Mapping — UDIM TILES

Spreads the layout across several texture tiles instead of one square.

Texture sets and UDIM answer the same question — one image is not enough — and
answer it differently. Texture sets give each material its own image, all
addressed by the same 0-1 coordinates, so the sets sit on top of each other.
UDIM lays the images out side by side in one continuous coordinate space: tile
1001 is 0-1, tile 1002 is 1-2 in U, and a renderer given a filename with a
<UDIM> token picks the right image from the coordinate itself.

Which to use is not a quality decision. Texture sets are what a real-time engine
wants, because it draws one material at a time and a shared coordinate space
costs it nothing. UDIM is what a film or texturing pipeline wants, because
Substance and RenderMan both address tiles natively and a single UV layout that
spills across four tiles is simpler to author than four sets.

The offsetting here is deliberately dumb: each group is already packed into 0-1
by the time it arrives, and moving it to tile N is adding an integer. Everything
that decides *how* the islands are packed happened earlier, which is what keeps
this from turning into a second packer.
"""

from .utils import loop_uv, polygon_loop_range, set_loop_uv

# UDIM numbering: 1001 is the first tile, and U advances by one per tile with a
# row of ten before V increments. The convention is fixed, not a choice.
FIRST_TILE = 1001
TILES_PER_ROW = 10


class UDIMResult:
    """What the UDIM pass assigned and moved."""
    def __init__(self):
        self.tiles = 0
        self.moved_islands = 0
        self.assignments = {}
        self.messages = []

    def tile_numbers(self):
        return sorted(
            tile_number(u, v) for (u, v) in set(self.assignments.values())
        )


def tile_number(tile_u, tile_v):
    """UDIM number for a tile position."""
    return FIRST_TILE + tile_u + tile_v * TILES_PER_ROW


def tile_position(index):
    """Tile position for the index-th tile, filling rows of ten."""
    return index % TILES_PER_ROW, index // TILES_PER_ROW


def assign_by_material(island_analysis, material_analysis, max_tiles=100):
    """
    One tile per material, in slot order.

    Slot order rather than area order on purpose: an artist who reorders their
    material slots expects the tiles to follow, and a layout whose tile numbers
    shuffle whenever a material grows is impossible to keep textures matched
    to.

    Returns {island_id: (tile_u, tile_v)}.
    """
    islands = getattr(island_analysis, "islands", None) or []
    face_group = getattr(material_analysis, "face_material_group", None) or {}

    if not islands:
        return {}

    island_group = {}
    for record in islands:
        tally = {}
        for fidx in record.get("faces", ()):
            group = face_group.get(fidx)
            if group is not None:
                tally[group] = tally.get(group, 0) + 1

        # The dominant material owns the island. An island straddling two
        # materials has to land somewhere, and splitting it would undo the
        # seam planning that put it together.
        island_group[record.get("id")] = max(tally, key=tally.get) if tally else 0

    groups = sorted(set(island_group.values()))
    if len(groups) > max_tiles:
        groups = groups[:max_tiles]

    slot_to_tile = {
        group: tile_position(i) for i, group in enumerate(groups)
    }

    return {
        island_id: slot_to_tile[group]
        for island_id, group in island_group.items()
        if group in slot_to_tile
    }


def offset_islands(mesh, uv_layer, island_analysis, assignments, report=None):
    """
    Moves each island into its assigned tile.

    Islands are assumed to be packed into 0-1 already, so this adds the tile
    index to every coordinate. An island that is not in 0-1 is moved by the
    same amount anyway rather than being normalised: silently rescaling
    someone's layout is worse than leaving it visibly in the wrong place.

    Returns the number of islands moved.
    """
    islands = getattr(island_analysis, "islands", None) or []
    if not islands or uv_layer is None or not assignments:
        return 0

    polygons = mesh.polygons
    loop_count = len(mesh.loops)
    moved = 0

    for record in islands:
        island_id = record.get("id")
        target = assignments.get(island_id)

        if target is None:
            continue

        tile_u, tile_v = target
        if tile_u == 0 and tile_v == 0:
            # Tile 1001 is where everything already is.
            continue

        for fidx in record.get("faces", ()):
            if not (0 <= fidx < len(polygons)):
                continue

            start, end = polygon_loop_range(polygons[fidx])
            for i in range(start, min(end, loop_count)):
                uv = loop_uv(uv_layer, i)
                if uv is not None:
                    set_loop_uv(uv_layer, i, uv[0] + tile_u, uv[1] + tile_v)

        moved += 1

    if report and moved:
        report("INFO", f"Moved {moved} islands into their UDIM tiles.")

    return moved


def apply(mesh, uv_layer, island_analysis, material_analysis, settings,
          report=None):
    """
    Assigns tiles and moves the islands. Returns a UDIMResult.
    """
    result = UDIMResult()

    def say(level, message):
        result.messages.append(message)
        if report:
            report(level, message)

    if uv_layer is None or island_analysis is None or not island_analysis.ok:
        say("WARNING", "UDIM skipped: no usable UV layer or island analysis.")
        return result

    try:
        max_tiles = int(getattr(settings, "udim_max_tiles", 20) or 20)
    except (TypeError, ValueError):
        max_tiles = 20

    assignments = assign_by_material(
        island_analysis, material_analysis, max_tiles=max_tiles
    )

    if not assignments:
        say("WARNING", "UDIM skipped: no material grouping available.")
        return result

    tiles = set(assignments.values())

    if len(tiles) < 2:
        say(
            "INFO",
            "UDIM skipped: everything belongs to one material, so a single "
            "tile is the whole layout."
        )
        return result

    result.assignments = assignments
    result.tiles = len(tiles)
    result.moved_islands = offset_islands(
        mesh, uv_layer, island_analysis, assignments, report=None
    )

    numbers = result.tile_numbers()
    say(
        "INFO",
        f"UDIM: {result.tiles} tiles ({numbers[0]}-{numbers[-1]}), "
        f"{result.moved_islands} islands moved. Name textures with a <UDIM> "
        "token so the renderer picks the right one."
    )

    return result
