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
from .ui import IntelligentUV_OT_ShowInfo, VIEW3D_PT_IntelligentUV

bl_info = {
    "name": "Intelligent UV Mapping",
    "author": "Pierfrancesco Diodato",
    "version": (0, 35, 1),
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
    IntelligentUV_OT_ShowInfo,
    VIEW3D_PT_IntelligentUV,
)

# Classes this module registered, in registration order. `bpy.types` does not
# list every registered type (PropertyGroups in particular), so a second
# `register()` cannot rely on it to find what the first one left behind.
_registered_classes = []


def _unregister_class_safe(cls):
    try:
        bpy.utils.unregister_class(cls)
    except Exception:
        # A: a class Blender never registered cannot be unregistered.
        # That happens whenever registration failed part-way, and the
        # remaining classes still need their turn.
        pass


def _registered_name(cls):
    """Returns the attribute under which Blender stores a registered class."""
    # Operators live under their bl_idname; every other type under __name__.
    if issubclass(cls, bpy.types.Operator):
        return getattr(cls, "bl_idname", cls.__name__)
    return cls.__name__


def register():
    """Registers every class and attaches the settings to the Scene."""
    # Dropping the pointer clears the settings stored on every scene, so their
    # values are read first and written back once the pointer is re-attached.
    snapshot = {}
    try:
        # Blender runs this function inside RestrictBlend when the add-on is
        # enabled: `bpy.data` is a _RestrictData object there and exposes no
        # collections, so the scenes are read through getattr and a missing
        # collection leaves the snapshot empty instead of aborting the load.
        scenes = getattr(bpy.data, "scenes", None) or ()
    except Exception:
        # A: restricted data that still raises is treated the same way, the
        # values are simply not restored afterwards.
        scenes = ()
    for scene in scenes:
        settings = getattr(scene, "intelligent_uv_settings", None)
        if settings is None:
            continue
        values = {}
        for prop in settings.bl_rna.properties:
            if prop.identifier == "rna_type" or prop.is_readonly:
                continue
            try:
                values[prop.identifier] = getattr(settings, prop.identifier)
            except Exception:
                # A: a value that cannot be read is skipped instead of
                # aborting the whole registration.
                continue
        snapshot[scene] = values

    # The pointer must go before the PropertyGroup it points at is replaced,
    # or the RNA reference outlives the class it targets.
    if hasattr(bpy.types.Scene, "intelligent_uv_settings"):
        try:
            del bpy.types.Scene.intelligent_uv_settings
        except Exception:
            # A: the pointer may already be gone if a previous unregister got
            # part-way through; removing it twice is not an error worth raising.
            pass

    # A second call in the same session first removes what the previous one
    # registered: Blender refuses a class that is still registered, and the
    # types it does not expose under `bpy.types` (PropertyGroups above all)
    # cannot be found again by name.
    while _registered_classes:
        _unregister_class_safe(_registered_classes.pop())

    # Anything still present under a registered name was left by another load
    # of this add-on. Re-registering over it is safe; reloading its module
    # would not be, so the user is told to restart rather than left with half
    # of each version running.
    stale = any(hasattr(bpy.types, _registered_name(cls)) for cls in CLASSES)

    try:
        for cls in CLASSES:
            if hasattr(bpy.types, _registered_name(cls)):
                _unregister_class_safe(cls)
            bpy.utils.register_class(cls)
            _registered_classes.append(cls)
    finally:
        # The Scene must never be left without its pointer, even when one of
        # the classes above failed to register.
        if not hasattr(bpy.types.Scene, "intelligent_uv_settings"):
            bpy.types.Scene.intelligent_uv_settings = bpy.props.PointerProperty(
                type=IntelligentUVProperties
            )
        for scene, values in snapshot.items():
            try:
                settings = getattr(scene, "intelligent_uv_settings", None)
            except Exception:
                # B: a scene that disappeared while the classes were being
                # replaced cannot take its values back.
                continue
            if settings is None:
                continue
            for identifier, value in values.items():
                try:
                    setattr(settings, identifier, value)
                except Exception:
                    # B: a value that no longer fits the property is dropped
                    # rather than leaving the scene without its settings.
                    continue

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
