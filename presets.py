# pylint: disable=invalid-name
"""
Intelligent UV Mapping — PRESET SYSTEM

Named setting bundles, stored as JSON in:
    bpy.utils.user_resource('SCRIPTS', path="presets/intelligent_uv")

Why JSON and not Blender's AddPresetBase:
AddPresetBase writes presets as executable Python and is designed to be mixed
into an Operator, not a Menu. Reading a preset then means running arbitrary
code from disk. JSON keeps the same user-visible behaviour (named presets in a
menu, saved to the user scripts folder) while staying inert data that can be
validated before it touches the settings.

Unknown keys and out-of-range values in a preset file are skipped with a
warning rather than raising, so a preset written by an older version of the
add-on still applies as far as it can.
"""

import json
import os

import bpy

PRESET_SUBDIR = os.path.join("presets", "intelligent_uv")

# Every setting a preset is allowed to carry. Anything outside this list is
# ignored on load: presets should not be able to set the RizomUV executable
# path or the temp-file debug flags.
PRESET_KEYS = (
    # Method and clustering
    "seam_method",
    "vsa_max_angle_deviation",
    "vsa_target_clusters",
    "vsa_iterations",
    "vsa_smooth_passes",
    "vsa_crease_weight",
    "vsa_min_cluster_faces",
    "vsa_area_weighted",
    "vsa_resolve_topology",
    # Shared seam behaviour
    "separate_by_material",
    "preserve_existing_seams",
    "prune_dangling_seams",
    # Threshold engine, kept so a preset can still drive it
    "auto_curvature_threshold",
    "curvature_threshold",
    "concave_seam_bias",
    "split_non_developable",
    "split_max_cone_angle",
    "merge_islands",
    "merge_max_cone_angle",
    "absorb_micro_islands",
    "minimum_island_face_count",
    "auto_seam_margin",
    "min_seam_edge_length",
    # Result handling
    "recover_failed_islands",
    "recovery_rounds",
    "recovery_tolerance",
    "minimize_stretch",
    "minimize_stretch_iterations",
    "run_preflight",
    # Texture and layout
    "texture_resolution_mode",
    "custom_texture_resolution",
    "auto_island_margin",
    "island_margin",
    "target_coverage",
    "normalize_texel_density",
)

# ---------------------------------------------------------------------------
# Built-in presets
#
# minimum_island_face_count is the value to be careful with: with
# absorb_micro_islands enabled it is the size below which an island is folded
# into a neighbour. Measured on a 384-face sphere, raising it past ~5 starts
# absorbing islands that were not fragments, so none of the presets goes above
# that.
# ---------------------------------------------------------------------------

BUILTIN_PRESETS = {
    "Hard Surface": {
        # Panels meeting at crisp edges. A tight tolerance keeps each panel its
        # own cluster, and a strong crease pull is worth it here because hard
        # surface models have real folds for a seam to disappear into.
        "seam_method": 'VSA',
        "vsa_max_angle_deviation": 20.0,
        "vsa_iterations": 6,
        "vsa_smooth_passes": 4,
        "vsa_crease_weight": 1.5,
        "vsa_min_cluster_faces": 4,
        "vsa_area_weighted": True,
        "vsa_resolve_topology": True,
        "separate_by_material": True,
        "preserve_existing_seams": True,
        "prune_dangling_seams": True,
        "recover_failed_islands": True,
        "recovery_rounds": 2,
        "recovery_tolerance": 12.0,
        "minimize_stretch": True,
        "minimize_stretch_iterations": 32,
        "run_preflight": True,
        "texture_resolution_mode": '2K',
        "auto_island_margin": True,
        "target_coverage": 0.95,
        "normalize_texel_density": True,
    },
    "Organic": {
        # Nothing on a character is flat, so a tight tolerance would shatter it.
        # A looser cluster with more refinement passes finds the broad regions,
        # and the crease pull is lowered because there are few folds to hide in.
        "seam_method": 'VSA',
        "vsa_max_angle_deviation": 38.0,
        "vsa_iterations": 10,
        "vsa_smooth_passes": 5,
        "vsa_crease_weight": 0.5,
        "vsa_min_cluster_faces": 3,
        "vsa_area_weighted": True,
        "vsa_resolve_topology": True,
        "separate_by_material": True,
        "preserve_existing_seams": True,
        "prune_dangling_seams": True,
        "recover_failed_islands": True,
        "recovery_rounds": 3,
        "recovery_tolerance": 18.0,
        "minimize_stretch": True,
        "minimize_stretch_iterations": 64,
        "run_preflight": True,
        "texture_resolution_mode": '2K',
        "auto_island_margin": True,
        "target_coverage": 0.90,
        "normalize_texel_density": True,
    },
    "Game Asset 1K": {
        # At 1K the island count matters more than perfect flatness: every
        # island border costs padding, and padding is most of the texture at
        # this size. The target drives the count directly.
        "seam_method": 'VSA',
        "vsa_target_clusters": 40,
        "vsa_max_angle_deviation": 32.0,
        "vsa_iterations": 8,
        "vsa_smooth_passes": 4,
        "vsa_crease_weight": 1.0,
        "vsa_min_cluster_faces": 6,
        "vsa_area_weighted": True,
        "vsa_resolve_topology": True,
        "separate_by_material": True,
        "preserve_existing_seams": True,
        "prune_dangling_seams": True,
        "recover_failed_islands": True,
        "recovery_rounds": 2,
        "recovery_tolerance": 15.0,
        "minimize_stretch": True,
        "minimize_stretch_iterations": 32,
        "run_preflight": True,
        "texture_resolution_mode": '1K',
        "auto_island_margin": False,
        "island_margin": 0.008,
        "target_coverage": 0.97,
        "normalize_texel_density": True,
    },
}



# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

def get_preset_dir(create=True):
    """Absolute path of the preset folder, or None when unavailable."""
    try:
        base = bpy.utils.user_resource('SCRIPTS', path=PRESET_SUBDIR, create=create)
    except (AttributeError, TypeError):
        # A: user_resource signature differs between Blender versions.
        try:
            base = os.path.join(
                bpy.utils.user_resource('SCRIPTS'), PRESET_SUBDIR
            )
            if create:
                os.makedirs(base, exist_ok=True)
        except Exception as exc:
            print(f"[IUV_PRESET] Unable to resolve the preset folder: {exc}")
            return None

    return base or None


def sanitize_name(name):
    """Filesystem-safe preset name."""
    cleaned = "".join(
        c if (c.isalnum() or c in (" ", "-", "_")) else "_"
        for c in str(name)
    ).strip()

    return cleaned or "Preset"


def list_presets():
    """Names of every preset on disk, built-ins included, sorted."""
    names = set(BUILTIN_PRESETS)

    preset_dir = get_preset_dir(create=False)
    if preset_dir and os.path.isdir(preset_dir):
        try:
            for filename in os.listdir(preset_dir):
                if filename.endswith(".json"):
                    names.add(filename[:-5])
        except OSError as exc:
            print(f"[IUV_PRESET] Unable to list presets: {exc}")

    return sorted(names)


def load_preset_values(name):
    """
    Values for a preset. A user file overrides a built-in of the same name.

    Returns a dict, or None when the preset cannot be found or parsed.
    """
    preset_dir = get_preset_dir(create=False)

    if preset_dir:
        path = os.path.join(preset_dir, f"{sanitize_name(name)}.json")
        if os.path.isfile(path):
            try:
                with open(path, "r", encoding="utf-8") as handle:
                    data = json.load(handle)
                if isinstance(data, dict):
                    return data
                print(f"[IUV_PRESET] '{name}' is not a JSON object; ignoring it.")
            except (OSError, ValueError) as exc:
                # B: a corrupt user preset must not be silently swallowed.
                print(f"[IUV_PRESET] Unable to read preset '{name}': {exc}")

    return dict(BUILTIN_PRESETS[name]) if name in BUILTIN_PRESETS else None


def save_preset_values(name, values):
    """Writes a preset to disk. Returns (ok: bool, message: str)."""
    preset_dir = get_preset_dir(create=True)
    if not preset_dir:
        return False, "Preset folder unavailable."

    safe = sanitize_name(name)
    path = os.path.join(preset_dir, f"{safe}.json")

    try:
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(values, handle, indent=2, sort_keys=True)
    except OSError as exc:
        return False, f"Unable to write preset '{safe}': {exc}"

    return True, f"Preset '{safe}' saved."


def collect_current_values(settings):
    """Reads the preset-relevant settings into a plain dict."""
    values = {}

    for key in PRESET_KEYS:
        if not hasattr(settings, key):
            continue
        try:
            values[key] = getattr(settings, key)
        except (AttributeError, TypeError) as exc:
            # A: a property may not exist on an older settings version.
            print(f"[IUV_PRESET] Unable to read '{key}': {exc}")

    return values


def apply_values(settings, values):
    """
    Writes preset values onto the settings.

    Returns (applied_count, skipped_keys). Unknown or invalid keys are skipped
    rather than aborting, so a preset from another version still applies.
    """
    applied = 0
    skipped = []

    for key, value in values.items():
        if key not in PRESET_KEYS:
            skipped.append(key)
            continue

        if not hasattr(settings, key):
            skipped.append(key)
            continue

        try:
            setattr(settings, key, value)
            applied += 1
        except (AttributeError, TypeError, ValueError) as exc:
            # B: an out-of-range or wrongly typed value should not stop the
            # rest of the preset from applying, but must be traceable.
            print(f"[IUV_PRESET] Skipped '{key}' = {value!r}: {exc}")
            skipped.append(key)

    return applied, skipped


# ---------------------------------------------------------------------------
# Operators
# ---------------------------------------------------------------------------

class IntelligentUV_OT_ApplyPreset(bpy.types.Operator):
    """Applies a named preset to the current settings."""

    bl_idname = "intelligent_uv.apply_preset"
    bl_label = "Apply Preset"
    bl_description = "Apply the saved settings of this preset"
    bl_options = {'REGISTER', 'UNDO'}

    preset_name: bpy.props.StringProperty(
        name="Preset Name",
        description="Preset to apply",
        default="",
    )

    @classmethod
    def poll(cls, context):
        scene = getattr(context, "scene", None)
        return bool(scene) and hasattr(scene, "intelligent_uv_settings")

    def execute(self, context):
        values = load_preset_values(self.preset_name)

        if values is None:
            self.report({'ERROR'}, f"Preset '{self.preset_name}' not found.")
            return {'CANCELLED'}

        settings = context.scene.intelligent_uv_settings
        applied, skipped = apply_values(settings, values)

        try:
            settings.active_preset_name = self.preset_name
        except (AttributeError, TypeError):
            # A: the display-only property may be absent on an older build.
            pass

        if skipped:
            self.report(
                {'WARNING'},
                f"Preset '{self.preset_name}': {applied} settings applied, "
                f"{len(skipped)} skipped ({', '.join(skipped[:4])})."
            )
        else:
            self.report(
                {'INFO'},
                f"Preset '{self.preset_name}' applied ({applied} settings)."
            )

        return {'FINISHED'}


class IntelligentUV_OT_SavePreset(bpy.types.Operator):
    """Saves the current settings as a named preset."""

    bl_idname = "intelligent_uv.save_preset"
    bl_label = "Save Preset"
    bl_description = "Save the current settings as a reusable preset"
    bl_options = {'REGISTER'}

    preset_name: bpy.props.StringProperty(
        name="Name",
        description="Name for the preset",
        default="My Preset",
    )

    @classmethod
    def poll(cls, context):
        scene = getattr(context, "scene", None)
        return bool(scene) and hasattr(scene, "intelligent_uv_settings")

    def invoke(self, context, event):
        settings = context.scene.intelligent_uv_settings
        self.preset_name = getattr(settings, "active_preset_name", "") or "My Preset"
        return context.window_manager.invoke_props_dialog(self, width=300)

    def draw(self, context):
        self.layout.prop(self, "preset_name")

    def execute(self, context):
        settings = context.scene.intelligent_uv_settings
        values = collect_current_values(settings)

        ok, message = save_preset_values(self.preset_name, values)
        self.report({'INFO'} if ok else {'ERROR'}, message)

        if not ok:
            return {'CANCELLED'}

        try:
            settings.active_preset_name = sanitize_name(self.preset_name)
        except (AttributeError, TypeError):
            # A: the display-only property may be absent on an older build.
            pass

        return {'FINISHED'}


class IntelligentUV_OT_DeletePreset(bpy.types.Operator):
    """Deletes a user preset. Built-in presets cannot be removed."""

    bl_idname = "intelligent_uv.delete_preset"
    bl_label = "Delete Preset"
    bl_description = "Delete this user preset from disk"
    bl_options = {'REGISTER'}

    preset_name: bpy.props.StringProperty(name="Preset Name", default="")

    def execute(self, context):
        name = sanitize_name(self.preset_name)

        preset_dir = get_preset_dir(create=False)
        path = os.path.join(preset_dir, f"{name}.json") if preset_dir else None

        if not path or not os.path.isfile(path):
            if self.preset_name in BUILTIN_PRESETS:
                self.report({'WARNING'}, "Built-in presets cannot be deleted.")
            else:
                self.report({'ERROR'}, f"Preset '{name}' not found.")
            return {'CANCELLED'}

        try:
            os.remove(path)
        except OSError as exc:
            self.report({'ERROR'}, f"Unable to delete '{name}': {exc}")
            return {'CANCELLED'}

        self.report({'INFO'}, f"Preset '{name}' deleted.")
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# Menu
# ---------------------------------------------------------------------------

class IntelligentUV_MT_Presets(bpy.types.Menu):
    """Lists the available presets."""

    bl_idname = "INTELLIGENTUV_MT_presets"
    bl_label = "Presets"

    def draw(self, context):
        layout = self.layout
        names = list_presets()

        if not names:
            layout.label(text="No presets available")
            return

        for name in names:
            icon = 'PRESET' if name in BUILTIN_PRESETS else 'FILE'
            layout.operator(
                IntelligentUV_OT_ApplyPreset.bl_idname,
                text=name,
                icon=icon,
            ).preset_name = name


PRESET_CLASSES = (
    IntelligentUV_OT_ApplyPreset,
    IntelligentUV_OT_SavePreset,
    IntelligentUV_OT_DeletePreset,
    IntelligentUV_MT_Presets,
)
