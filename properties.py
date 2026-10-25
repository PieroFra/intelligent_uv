# pylint: disable=invalid-name
"""
Intelligent UV Mapping — PROPERTY GROUP

User-facing settings for the add-on.
"""

import bpy


# =============================================================================
# 1. PROPERTY GROUP — User Settings
# =============================================================================

class IntelligentUVProperties(bpy.types.PropertyGroup):
    """Main settings for the add-on."""

    auto_curvature_threshold: bpy.props.BoolProperty(
        name="Auto Curvature",
        description=(
            "Derive the curvature threshold from the dihedral angle distribution "
            "of the mesh instead of using the manual value."
        ),
        default=True,
    )

    curvature_threshold: bpy.props.FloatProperty(
        name="Curvature Threshold",
        description=(
            "Angle threshold in degrees for seam detection. Higher values produce fewer cuts. "
            "Used as the manual value and as the fallback for Auto Curvature."
        ),
        default=60.0,
        min=10.0,
        max=170.0,
    )

    auto_island_margin: bpy.props.BoolProperty(
        name="Auto Island Margin",
        description=(
            "Calculate the island margin automatically from texture resolution, "
            "island count and mesh complexity."
        ),
        default=True,
    )

    island_margin: bpy.props.FloatProperty(
        name="Manual Island Margin",
        description="Manual UV margin used when Auto Island Margin is disabled.",
        default=0.02,
        min=0.005,
        max=0.1,
    )

    target_coverage: bpy.props.FloatProperty(
        name="Target Coverage",
        description="Fraction of the UV space to occupy (e.g. 0.95 = 95%).",
        default=0.95,
        min=0.70,
        max=0.98,
        subtype='FACTOR',
    )

    separate_by_material: bpy.props.BoolProperty(
        name="Separate by Material",
        description="Force a cut at edges where the material changes.",
        default=True,
    )

    recover_failed_islands: bpy.props.BoolProperty(
        name="Retry Failed Islands",
        description=(
            "Find the islands the solver could not flatten, which come back "
            "with no UV area at all, cut them open and unwrap again. Only "
            "those islands are touched"
        ),
        default=True,
    )

    recovery_rounds: bpy.props.IntProperty(
        name="Retry Rounds",
        description=(
            "How many times to cut and retry. Each round cuts harder than the "
            "last, since what survived is the more stubborn geometry"
        ),
        default=2,
        min=0,
        max=6,
    )

    recovery_tolerance: bpy.props.FloatProperty(
        name="Retry Tolerance",
        description=(
            "Angular tolerance used when re-cutting a failed island. Lower "
            "cuts it into more, flatter pieces"
        ),
        default=15.0,
        min=3.0,
        max=60.0,
    )

    minimize_stretch: bpy.props.BoolProperty(
        name="Relax Stretch",
        description=(
            "Relax the UVs after unwrapping to even out the remaining "
            "distortion. Unwrap solves for angles and stops; this smooths the "
            "interior of each island without moving the seams"
        ),
        default=True,
    )

    minimize_stretch_iterations: bpy.props.IntProperty(
        name="Relax Iterations",
        description="More iterations relax further, with diminishing returns.",
        default=32,
        min=1,
        max=500,
    )

    use_udim: bpy.props.BoolProperty(
        name="UDIM Tiles",
        description=(
            "Lay each material out on its own tile in one continuous UV space, "
            "instead of stacking them in the same square. Substance and film "
            "renderers address tiles natively; a real-time engine usually wants "
            "Texture Sets instead"
        ),
        default=False,
    )

    udim_max_tiles: bpy.props.IntProperty(
        name="Max Tiles",
        description="Upper bound on how many tiles the layout may spread over.",
        default=20,
        min=2,
        max=100,
    )

    texture_sets: bpy.props.BoolProperty(
        name="Texture Set per Material",
        description=(
            "Give each material its own full UV square instead of sharing one. "
            "Each material gets its own texture addressed by the same 0-1 "
            "coordinates, so sharing a square wastes most of every image. The "
            "sets overlap each other on purpose: they read from different "
            "images and cannot collide"
        ),
        default=False,
    )

    orient_islands: bpy.props.BoolProperty(
        name="Orient Islands",
        description=(
            "Turn each island to the angle where it occupies the least "
            "rectangle, before packing. The packer arranges islands but never "
            "reshapes them, so a shell left at an angle wastes space whatever "
            "the packer does with it"
        ),
        default=True,
    )

    stack_duplicates: bpy.props.BoolProperty(
        name="Stack Repeated Parts",
        description=(
            "Lay the UVs of identical pieces on top of each other, so twenty "
            "copies of the same screw cost the texture space of one. Every "
            "match is verified after the copy and undone if it does not hold. "
            "Repeated parts then share a texture, which is usually what you "
            "want and occasionally is not"
        ),
        default=False,
    )

    normalize_texel_density: bpy.props.BoolProperty(
        name="Normalize Texel Density",
        description="Uniformize texel density between UV islands before final packing.",
        default=True,
    )

    uv_layer_name: bpy.props.StringProperty(
        name="UV Layer Name",
        description="Name of the target UV layer created by the tool.",
        default="SmartUV",
    )

    # Texture resolution selector (shared by native engine and RizomUV)
    # EnumProperty items must be tuples: (identifier, name, description)
    texture_resolution_mode: bpy.props.EnumProperty(
        name="Texture Resolution",
        description="Target texture resolution used for margin calculation and external engines.",
        items=[
            ('1K', "1K", "1024 x 1024"),
            ('2K', "2K", "2048 x 2048"),
            ('4K', "4K", "4096 x 4096"),
            ('CUSTOM', "Custom", "Use the custom resolution value"),
        ],
        default='2K',
    )

    custom_texture_resolution: bpy.props.IntProperty(
        name="Custom Texture Resolution",
        description="Texture resolution used when the mode is set to Custom.",
        default=2048,
        min=64,
        max=16384,
    )

    # Advanced parameters
    min_seam_edge_length: bpy.props.FloatProperty(
        name="Min Seam Edge Length",
        description=(
            "Manual minimum edge length for curvature-based cuts. "
            "Material boundaries stay active regardless of this value."
        ),
        default=0.0,
        min=0.0,
    )

    auto_seam_margin: bpy.props.BoolProperty(
        name="Auto Seam Margin",
        description=(
            "Derive the minimum seam edge length from the effective island margin "
            "and the estimated texel density."
        ),
        default=True,
    )

    concave_seam_bias: bpy.props.FloatProperty(
        name="Prefer Concave",
        description=(
            "Lower the curvature threshold by this many degrees on concave "
            "edges and raise it on convex ones. Seams hide in valleys and show "
            "on ridges, so this places cuts where an artist would. Set to 0 to "
            "treat both the same"
        ),
        default=15.0,
        min=0.0,
        max=60.0,
    )

    split_non_developable: bpy.props.BoolProperty(
        name="Split Wrapped Regions",
        description=(
            "Cut regions whose surface wraps too far to be flattened, such as "
            "cylinders and tubes. No curvature threshold can catch these: they "
            "have no sharp edge anywhere, yet the unwrap solver fails on them"
        ),
        default=True,
    )

    split_max_cone_angle: bpy.props.FloatProperty(
        name="Wrap Limit",
        description=(
            "Maximum spread of face normals a region may have before it is cut "
            "open. Lower cuts more shapes; higher only the most wrapped"
        ),
        default=100.0,
        min=30.0,
        max=180.0,
    )

    show_advanced: bpy.props.BoolProperty(
        name="Advanced",
        description=(
            "Show every tuning parameter. The defaults and the presets cover "
            "most assets; these are here for when they do not"
        ),
        default=False,
    )

    run_preflight: bpy.props.BoolProperty(
        name="Check Mesh First",
        description=(
            "Look for the problems that make unwrapping fail before planning "
            "anything, and say what to do about each"
        ),
        default=True,
    )

    stop_on_blockers: bpy.props.BoolProperty(
        name="Stop On Problems",
        description=(
            "Refuse to run when the mesh has a problem that guarantees a bad "
            "result, such as degenerate faces or non-manifold edges. Turn off "
            "to run anyway and see what happens"
        ),
        default=True,
    )

    seam_method: bpy.props.EnumProperty(
        name="Seam Method",
        description="How seams are decided.",
        items=[
            ('THRESHOLD', "Curvature Threshold",
             "Cut individual edges whose dihedral angle exceeds a threshold"),
            ('VSA', "Shape Clustering",
             "Grow faces into near-flat clusters and cut along their borders, "
             "then open any cluster that is topologically not a disc"),
        ],
        default='VSA',
    )

    auto_parameters: bpy.props.BoolProperty(
        name="Automatic",
        description=(
            "Work the clustering settings out from this mesh and this texture "
            "size instead of using fixed numbers. The tolerance comes from the "
            "model's own angle distribution, the minimum island size from the "
            "margin, and the crease pull from whether the model has folds to "
            "hide a seam in"
        ),
        default=True,
    )

    vsa_max_angle_deviation: bpy.props.FloatProperty(
        name="Cluster Tolerance",
        description=(
            "How far a face normal may deviate from its cluster average before "
            "a new cluster starts. Lower gives more, flatter patches"
        ),
        default=25.0,
        min=1.0,
        max=90.0,
    )

    vsa_area_weighted: bpy.props.BoolProperty(
        name="Weight by Area",
        description=(
            "Let large faces dominate the cluster average, so a panel is not "
            "pulled off course by the small bevels around it"
        ),
        default=True,
    )

    vsa_iterations: bpy.props.IntProperty(
        name="Refinement Passes",
        description=(
            "Lloyd relaxation rounds after the first pass. Growing clusters "
            "once is order-dependent; each round lets faces change hands until "
            "the partition stops moving. 0 disables it"
        ),
        default=6,
        min=0,
        max=50,
    )

    vsa_target_clusters: bpy.props.IntProperty(
        name="Target Islands",
        description=(
            "Aim for roughly this many clusters instead of deriving the count "
            "from the tolerance. 0 uses the tolerance"
        ),
        default=0,
        min=0,
        max=2000,
    )

    vsa_smooth_passes: bpy.props.IntProperty(
        name="Border Smoothing",
        description=(
            "Passes that straighten cluster borders and pull them onto "
            "creases. Growing regions leaves ragged outlines that pack badly "
            "and put the visible cut in an arbitrary place. 0 disables it"
        ),
        default=3,
        min=0,
        max=20,
    )

    vsa_crease_weight: bpy.props.FloatProperty(
        name="Hide in Creases",
        description=(
            "How strongly borders are drawn towards sharp folds, where a seam "
            "is least visible. 0 straightens the border without caring where "
            "it lands"
        ),
        default=1.0,
        min=0.0,
        max=4.0,
    )

    vsa_min_cluster_faces: bpy.props.IntProperty(
        name="Min Cluster Faces",
        description=(
            "Clusters smaller than this are folded into the neighbour whose "
            "average normal is closest, so bevel slivers do not each become "
            "their own island"
        ),
        default=3,
        min=1,
        max=50,
    )

    vsa_resolve_topology: bpy.props.BoolProperty(
        name="Resolve Topology",
        description=(
            "Detect clusters that are rings or have holes, using the Euler "
            "characteristic, and cut them open along a shortest path. No "
            "angular test can find these: a cylinder band is flat everywhere"
        ),
        default=True,
    )

    vsa_merge_clusters: bpy.props.BoolProperty(
        name="Merge Clusters Afterwards",
        description=(
            "Run the island merger on top of the clusters. Clustering already "
            "produces coherent regions, and the merger is by far the slowest "
            "stage on dense meshes, so this is off by default"
        ),
        default=False,
    )

    symmetrize_seams: bpy.props.BoolProperty(
        name="Mirror Seams",
        description=(
            "Detect the plane the model is mirrored about and make the seams "
            "mirror with it. Clustering grows the two halves independently, so "
            "they end up cut in subtly different places, which reads as a "
            "mistake on a symmetric object. Mirrored halves cut identically "
            "also become stackable"
        ),
        default=True,
    )

    symmetry_min_coverage: bpy.props.FloatProperty(
        name="Symmetry Threshold",
        description=(
            "Fraction of faces that must find a mirrored partner before the "
            "model counts as symmetric. Below 1.0 so an asymmetric detail, "
            "such as an ejection port, does not disqualify the whole model"
        ),
        default=0.8,
        min=0.5,
        max=1.0,
        subtype='FACTOR',
    )

    preserve_existing_seams: bpy.props.BoolProperty(
        name="Keep Existing Seams",
        description=(
            "Add to the seams already on the mesh instead of replacing them. "
            "A hand-placed cut encodes intent no threshold can infer, so it is "
            "kept and the planner works around it"
        ),
        default=True,
    )

    prune_dangling_seams: bpy.props.BoolProperty(
        name="Prune Dangling Seams",
        description=(
            "Remove seam edges that dead-end inside a surface. They separate "
            "nothing and only add spurs to the island outline"
        ),
        default=True,
    )

    minimum_island_face_count: bpy.props.IntProperty(
        name="Minimum Island Face Count",
        description="Minimum faces per island/region candidate, used for warnings.",
        default=3,
        min=1,
    )

    # --- Island merging (quality) ---
    merge_islands: bpy.props.BoolProperty(
        name="Merge Islands",
        description=(
            "Merge adjacent regions whose combined surface stays flat enough to "
            "unwrap well. Strongly reduces fragmentation."
        ),
        default=True,
    )

    merge_max_cone_angle: bpy.props.FloatProperty(
        name="Merge Flatness",
        description=(
            "Maximum spread of face normals allowed inside a merged island, in "
            "degrees. Lower keeps islands flatter; higher merges more aggressively."
        ),
        default=60.0,
        min=5.0,
        max=120.0,
    )

    absorb_micro_islands: bpy.props.BoolProperty(
        name="Absorb Micro Islands",
        description=(
            "Always merge islands below the minimum face count into their best "
            "neighbour, regardless of flatness."
        ),
        default=True,
    )

    # --- Reporting / safety ---
    report_distortion: bpy.props.BoolProperty(
        name="Report Distortion",
        description="Measure texel density variation and angular distortion after unwrapping.",
        default=True,
    )

    check_overlaps: bpy.props.BoolProperty(
        name="Check Overlaps",
        description="Warn when island bounding boxes overlap after packing.",
        default=True,
    )

    backup_uv_layer: bpy.props.BoolProperty(
        name="Backup UV Layer",
        description=(
            "Copy an existing target UV layer to '<name>_backup' before overwriting it."
        ),
        default=True,
    )

    dry_run: bpy.props.BoolProperty(
        name="Dry Run",
        description=(
            "Analyse and plan only: report the result without writing seams or UVs. "
            "Useful for tuning settings."
        ),
        default=False,
    )

    mark_bevel_debug: bpy.props.BoolProperty(
        name="Also Mark Bevel Weights",
        description=(
            "In addition to real UV seams, write bevel weights for quick visual debugging."
        ),
        default=False,
    )

    process_selected: bpy.props.BoolProperty(
        name="Process Selected",
        description=(
            "Process every selected mesh object instead of just the active one."
        ),
        default=False,
    )

    # RizomUV Engine Settings
    use_rizomuv: bpy.props.BoolProperty(
        name="Automated RizomUV",
        description=(
            "Drive RizomUV automatically from inside the Unwrap operator via "
            "Live Link or Lua Script (Windows)"
        ),
        default=False,
    )

    rizomuv_engine_mode: bpy.props.EnumProperty(
        name="RizomUV Mode",
        description="How to drive RizomUV.",
        items=[
            ('AUTO', "Auto",
             "Use the live link when available, otherwise fall back to the "
             "Lua script"),
            ('LINK', "Live Link",
             "Drive RizomUV through its official Python API. Windows only, "
             "requires RizomUV 2025 or later"),
            ('SCRIPT', "Lua Script",
             "Write a Lua script and launch RizomUV with it. Kept for builds "
             "without the Python API"),
        ],
        default='AUTO',
    )

    link_optimize: bpy.props.BoolProperty(
        name="Optimize in RizomUV",
        description=(
            "Run RizomUV's Optimize pass to reduce stretch before packing"
        ),
        default=True,
    )

    link_keep_open: bpy.props.BoolProperty(
        name="Keep RizomUV Open",
        description=(
            "Leave RizomUV running after the live link finishes, so the "
            "result can be inspected in its viewport. Off: RizomUV is closed "
            "automatically at the end of the run"
        ),
        default=False,
    )

    rizomuv_path: bpy.props.StringProperty(
        name="RizomUV Path",
        description="Path to the RizomUV executable.",
        subtype='FILE_PATH',
        default=r"C:\Program Files\Rizom Lab\RizomUV 2025.0\rizomuv.exe",
    )

    rizomuv_args: bpy.props.StringProperty(
        name="RizomUV Arguments",
        description=(
            "Command line arguments. {script} is replaced with the generated Lua "
            "file. If RizomUV opens its window and stays open, this build likely "
            "needs an extra headless flag here (check 'rizomuv.exe -h')."
        ),
        default="-cfi {script}",
    )

    rizomuv_timeout: bpy.props.IntProperty(
        name="RizomUV Timeout",
        description="Maximum seconds to wait for the external process.",
        default=300,
        min=10,
        max=3600,
    )

    last_export_path: bpy.props.StringProperty(
        name="Last Export Path",
        description="Path of the last manual FBX export, offered back on import.",
        subtype='FILE_PATH',
        default="",
    )

    active_preset_name: bpy.props.StringProperty(
        name="Active Preset",
        description="Name of the preset last applied. Display only.",
        default="",
    )

    keep_temp_files: bpy.props.BoolProperty(
        name="Keep Temp Files",
        description=(
            "Do not delete the FBX and Lua files generated for RizomUV. "
            "Their paths are printed to the System Console for inspection."
        ),
        default=False,
    )
