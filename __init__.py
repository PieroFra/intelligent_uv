# pylint: disable=invalid-name
"""
Intelligent UV Mapping — Blender add-on

Automated UV unwrapping with curvature-driven seam planning, island merging,
texel density normalization and an optional RizomUV bridge.

Install:
1. Zip the `intelligent_uv` folder.
2. Blender > Edit > Preferences > Add-ons > Install from Disk.
3. Enable "Intelligent UV Mapping".

Or, for development, drop the folder into your scripts/addons directory.

Module map
----------
utils.py              version-tolerant mesh API helpers, shared geometry maths
properties.py         the PropertyGroup holding every user setting
validation.py         context validation before any heavy operation
mesh_analysis.py      topology and geometry (bmesh first, fallbacks after)
material_analysis.py  material groups and material-boundary edges
margins.py            texture resolution -> pixel margin -> UV margin
curvature.py          automatic curvature threshold (Otsu)
seam_planning.py      seam candidates from curvature + material boundaries
region_merge.py       island merging via the normal-cone flatness test
distortion.py         texel density spread, angular error, overlap checks
seam_marking.py       writes edge.use_seam (and optional bevel weights)
uv_executor.py        native unwrap, packing, coverage, UV layer backup
island_extraction.py  final UV islands with area/centroid/bbox stats
texel_density.py      per-island scaling to a uniform density
rizomuv_bridge.py     phased, non-blocking external engine bridge
operators.py          the modal Run operator, seam marking, diagnostics
ui.py                 sidebar panel
"""

import bpy

# ---------------------------------------------------------------------------
# Reload guard
#
# Reinstalling an add-on does not restart Python. Blender re-imports the top
# level package, but every submodule is still in sys.modules from the previous
# session, so `from .run import NewClass` hands back the OLD cached module and
# raises ImportError even though the file on disk is correct.
#
# Reloading the submodules explicitly, leaves first, makes reinstalling work
# without restarting Blender.
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Why there is no automatic module reload here
#
# Reloading submodules on re-import looks convenient, but `properties.py`
# defines the PropertyGroup that `bpy.types.Scene.intelligent_uv_settings`
# points at. Reloading it builds a NEW class object while Blender's RNA still
# references the old one, and once the old module is collected that pointer
# dangles — which crashes Blender outright rather than raising in Python.
# The same hazard applies to every registered operator and panel class.
#
# Reinstalling therefore requires restarting Blender. That is the cost of not
# corrupting memory, and `register()` below states it if a stale load is
# detected.
# ---------------------------------------------------------------------------



from .operators import (
    PREVIEW_CLASSES,
    IntelligentUV_OT_Check,
    IntelligentUV_OT_Diagnose,
    IntelligentUV_OT_MarkSeams,
    IntelligentUV_OT_ResetState,
    IntelligentUV_OT_Run,
)
from .manual_io import MANUAL_IO_CLASSES
from .presets import PRESET_CLASSES
from .properties import IntelligentUVProperties
from .ui import VIEW3D_PT_IntelligentUV

bl_info = {
    "name": "Intelligent UV Mapping",
    "author": "Your Name",
    "version": (0, 34, 0),
    "blender": (4, 2, 0),
    "location": "View3D > Sidebar (N) > Intelligent UV",
    "description": "Automatic workflow for intelligent UV mapping.",
    "category": "UV",
}

# PropertyGroup first: the Scene pointer depends on it being registered.
CLASSES = (
    IntelligentUVProperties,
) + PRESET_CLASSES + MANUAL_IO_CLASSES + PREVIEW_CLASSES + (
    IntelligentUV_OT_Run,
    IntelligentUV_OT_ResetState,
    IntelligentUV_OT_MarkSeams,
    IntelligentUV_OT_Check,
    IntelligentUV_OT_Diagnose,
    VIEW3D_PT_IntelligentUV,
)


def _unregister_class_safe(cls):
    try:
        bpy.utils.unregister_class(cls)
    except Exception:
        # A: a class Blender never registered cannot be unregistered.
        # That happens whenever registration failed part-way, and the
        # remaining classes still need their turn.
        pass


def register():
    """Registers every class and attaches the settings to the Scene."""
    # A class already present under this name means a previous version of the
    # add-on is still loaded in this session. Re-registering over it is safe;
    # reloading its module would not be, so the user is told to restart rather
    # than left with half of each version running.
    stale = any(hasattr(bpy.types, cls.__name__) for cls in CLASSES)

    # The Scene pointer must go before the PropertyGroup it points at is
    # replaced, or the RNA reference outlives the class it targets.
    if hasattr(bpy.types.Scene, "intelligent_uv_settings"):
        try:
            del bpy.types.Scene.intelligent_uv_settings
        except Exception:
            # A: the pointer may already be gone if a previous unregister got
            # part-way through; removing it twice is not an error worth raising.
            pass

    for cls in CLASSES:
        if hasattr(bpy.types, cls.__name__):
            _unregister_class_safe(cls)
        bpy.utils.register_class(cls)

    bpy.types.Scene.intelligent_uv_settings = bpy.props.PointerProperty(
        type=IntelligentUVProperties
    )

    if stale:
        print(
            "[IUV] An earlier version was still loaded in this session. "
            "Blender caches Python modules, so parts of the old version may "
            "still be running. Restart Blender to be sure the new one is active."
        )


def unregister():
    """Removes the Scene pointer first, then the classes it referenced."""
    if hasattr(bpy.types.Scene, "intelligent_uv_settings"):
        try:
            del bpy.types.Scene.intelligent_uv_settings
        except Exception:
            # A: a class Blender never registered cannot be unregistered.
            # That happens whenever registration failed part-way, and the
            # remaining classes still need their turn.
            pass

    for cls in reversed(CLASSES):
        _unregister_class_safe(cls)
