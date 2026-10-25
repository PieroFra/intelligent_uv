# pylint: disable=invalid-name
"""
Intelligent UV Mapping — UI PANEL

Sidebar panel.
"""

import os

import bpy

from . import preview as _preview

from .operators import (
    IntelligentUV_OT_ApplyPreview,
    IntelligentUV_OT_Check,
    IntelligentUV_OT_DiscardPreview,
    IntelligentUV_OT_Preview,
    IntelligentUV_OT_Diagnose,
    IntelligentUV_OT_ResetState,
    IntelligentUV_OT_MarkSeams,
    IntelligentUV_OT_Run,
)
from .manual_io import (
    IntelligentUV_OT_ExportFBX,
    IntelligentUV_OT_ImportFBX,
    IntelligentUV_OT_ImportLast,
    last_import_candidate,
)
from .presets import (
    IntelligentUV_MT_Presets,
    IntelligentUV_OT_DeletePreset,
    IntelligentUV_OT_SavePreset,
)


# =============================================================================
# 14. UI PANEL
# =============================================================================

class _EnglishLayout:
    """Layout proxy that keeps labels untranslated.

    Almost every label in this panel is a technical term (VSA, UDIM, cone
    angle, texel density): translating them renames the controls and the
    docs stop matching what the user reads on screen. The proxy forwards
    everything to the real layout and only adds ``translate=False`` to the
    string-carrying calls, so call sites stay plain ``row.operator(...)``.
    """

    __slots__ = ("_layout",)

    def __init__(self, layout):
        object.__setattr__(self, "_layout", layout)

    def __getattr__(self, name):
        return getattr(self._layout, name)

    def __setattr__(self, name, value):
        setattr(self._layout, name, value)

    def _child(self, name, *args, **kwargs):
        method = getattr(self._layout, name)
        return _EnglishLayout(method(*args, **kwargs))

    def _text(self, name, *args, **kwargs):
        kwargs.setdefault("translate", False)
        method = getattr(self._layout, name)
        try:
            return method(*args, **kwargs)
        except TypeError:
            # Older layouts may lack the `translate` keyword.
            kwargs.pop("translate", None)
            return method(*args, **kwargs)

    def row(self, *args, **kwargs):
        return self._child("row", *args, **kwargs)

    def column(self, *args, **kwargs):
        return self._child("column", *args, **kwargs)

    def box(self, *args, **kwargs):
        return self._child("box", *args, **kwargs)

    def split(self, *args, **kwargs):
        return self._child("split", *args, **kwargs)

    def label(self, *args, **kwargs):
        return self._text("label", *args, **kwargs)

    def prop(self, *args, **kwargs):
        if "text" not in kwargs and len(args) >= 2:
            try:
                kwargs["text"] = args[0].bl_rna.properties[args[1]].name
            except Exception:
                pass
        return self._text("prop", *args, **kwargs)

    def operator(self, *args, **kwargs):
        return self._text("operator", *args, **kwargs)

    def menu(self, *args, **kwargs):
        return self._text("menu", *args, **kwargs)


_QUICK_GUIDE_LINES = (
    "Check Mesh - validates the mesh before anything is unwrapped.",
    "Unwrap / Preview - full run on the scene, or a dry run on the mesh.",
    "RizomUV Auto - batch hand-off, waits for the islands to come back.",
    "RizomUV Live Link - keeps the session open and syncs both ways.",
    "RizomUV Lua Script - drives RizomUV headless, no GUI needed.",
)

_LICENSE_LINES = (
    "Free software released under the GNU GPL v3.0 or later.",
    "You are free to use, study, share, and modify it.",
    "No warranty: use it at your own risk.",
)


class IntelligentUV_OT_ShowInfo(bpy.types.Operator):
    """Popup with author, license, and documentation links."""

    bl_idname = "intelligent_uv.show_info"
    bl_label = "License & Credits"
    bl_description = "Show add-on author, license, and documentation links"
    bl_options = {'INTERNAL'}

    def invoke(self, context, event):
        return context.window_manager.invoke_popup(self, width=520)

    def execute(self, context):
        return {'FINISHED'}

    def draw(self, context):
        from pathlib import Path

        layout = _EnglishLayout(self.layout)

        try:
            from . import bl_info as _bl_info
            version = ".".join(str(n) for n in _bl_info.get("version", ()))
        except Exception:
            version = "?"

        layout.label(text=f"Intelligent UV Mapping v{version}", icon='UV')
        layout.label(text="Author: Pierfrancesco Diodato", icon='USER')

        row = layout.row(align=True)
        row.operator(
            "wm.url_open", text="GitHub Repository", icon='URL',
        ).url = "https://github.com/PieroFra/intelligent_uv"
        row.operator(
            "wm.url_open", text="Discord Profile", icon='URL',
        ).url = "https://discord.com/users/1176582483165327382"
        row.operator(
            "wm.url_open", text="Full GPL-3.0 License", icon='URL',
        ).url = "https://www.gnu.org/licenses/gpl-3.0.html"

        box = layout.box()
        box.label(text="Quick Guide", icon='TEXT')
        for line in _QUICK_GUIDE_LINES:
            box.label(text=line)

        box = layout.box()
        box.label(text="License: GPL-3.0-or-later", icon='INFO')
        for line in _LICENSE_LINES:
            box.label(text=line)

        root = Path(__file__).resolve().parent
        local = layout.row(align=True)
        for fname in ("README.md", "CHANGELOG.md", "LICENSE"):
            path = root.joinpath(fname)
            if path.is_file():
                local.operator(
                    "wm.url_open", text=fname, icon='FILEBROWSER',
                ).url = path.as_uri()


class VIEW3D_PT_IntelligentUV(bpy.types.Panel):
    """Main panel in the 3D View N sidebar."""

    bl_idname = "VIEW3D_PT_intelligent_uv"
    bl_label = "Intelligent UV"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Intelligent UV"

    @classmethod
    def poll(cls, context):
        scene = getattr(context, "scene", None)
        return bool(scene) and hasattr(scene, "intelligent_uv_settings")

    def draw(self, context):
        layout = _EnglishLayout(self.layout)
        settings = context.scene.intelligent_uv_settings

        try:
            from . import bl_info as _bl_info
            version = ".".join(str(n) for n in _bl_info.get("version", ()))
        except Exception:
            version = "?"

        # Presets first and the Run button right under them: on most assets
        # that is the entire interaction, and burying it under thirty tuning
        # controls is what makes a tool feel like it needs a manual.
        row = layout.row(align=True)
        row.menu(
            IntelligentUV_MT_Presets.bl_idname,
            text=settings.active_preset_name or "Preset",
            icon='PRESET',
        )
        row.operator(IntelligentUV_OT_SavePreset.bl_idname, text="", icon='ADD')
        if settings.active_preset_name:
            row.operator(
                IntelligentUV_OT_DeletePreset.bl_idname, text="", icon='REMOVE'
            ).preset_name = settings.active_preset_name

        obj = context.active_object
        pending = (
            obj is not None and obj.type == 'MESH'
            and _preview.has_pending(obj.data)
        )

        if pending:
            # While a preview is waiting, deciding on it is the only sensible
            # next action, so nothing else competes for attention.
            box_pending = layout.box()
            box_pending.alert = True
            box_pending.label(text="Preview waiting", icon='INFO')
            row = box_pending.row(align=True)
            row.scale_y = 1.4
            row.operator(
                IntelligentUV_OT_ApplyPreview.bl_idname, text="Apply",
                icon='CHECKMARK',
            )
            row.operator(
                IntelligentUV_OT_DiscardPreview.bl_idname, text="Discard",
                icon='CANCEL',
            )
        else:
            col = layout.column(align=True)
            col.scale_y = 1.4
            col.operator(IntelligentUV_OT_Run.bl_idname, text="Unwrap", icon='UV')
            col.scale_y = 1.0
            col.operator(
                IntelligentUV_OT_Preview.bl_idname, text="Preview", icon='HIDE_OFF'
            )

        row = layout.row(align=True)
        row.operator(IntelligentUV_OT_Check.bl_idname, icon='CHECKMARK')
        row.prop(settings, "dry_run", toggle=True, icon='HIDE_OFF')

        if IntelligentUV_OT_Run._busy:
            warn = layout.row()
            warn.alert = True
            warn.operator(IntelligentUV_OT_ResetState.bl_idname, icon='LOOP_BACK')

        if settings.dry_run:
            info = layout.row()
            info.alert = True
            info.label(text="Dry Run: nothing will be written", icon='INFO')

        # The three controls that actually change the result on most meshes.
        box = layout.box()
        box.label(text="Layout", icon='UV')
        col = box.column(align=True)
        col.prop(settings, "texture_resolution_mode", text="Tex Size")
        if settings.texture_resolution_mode == 'CUSTOM':
            col.prop(settings, "custom_texture_resolution", text="Pixels")

        if settings.seam_method == 'VSA':
            col.prop(settings, "vsa_target_clusters", text="Target Islands")
            sub = col.row()
            sub.enabled = settings.vsa_target_clusters == 0
            sub.prop(settings, "vsa_max_angle_deviation", text="Detail")
        else:
            col.prop(settings, "curvature_threshold", text="Detail")

        col.prop(settings, "process_selected", text="All Selected Objects")

        # RizomUV round trip: export, work by hand, import.
        box_io = layout.box()
        box_io.label(text="External Editor", icon='FILE_REFRESH')
        col = box_io.column(align=True)
        col.prop(settings, "rizomuv_path", text="")
        row = col.row(align=True)
        row.scale_y = 1.2
        row.operator(
            IntelligentUV_OT_ExportFBX.bl_idname, text="Export & Open",
            icon='EXPORT',
        )
        pending = last_import_candidate(settings)
        sub = row.row(align=True)
        sub.enabled = bool(pending)
        sub.operator(
            IntelligentUV_OT_ImportLast.bl_idname, text="Import", icon='IMPORT'
        )
        if pending:
            col.label(text=os.path.basename(pending), icon='FILE_TICK')
        col.operator(
            IntelligentUV_OT_ImportFBX.bl_idname, text="Import from...",
            icon='FILEBROWSER',
        )

        layout.separator()
        row = layout.row()
        row.operator(
            IntelligentUV_OT_ShowInfo.bl_idname,
            text="License & Credits", icon='INFO',
        )
        sub = row.row()
        sub.alignment = 'RIGHT'
        sub.label(text=f"v{version}")

        layout.prop(
            settings, "show_advanced",
            icon='TRIA_DOWN' if settings.show_advanced else 'TRIA_RIGHT',
            emboss=False,
        )

        if settings.show_advanced:
            self._draw_advanced(layout, settings)

    def _draw_advanced(self, layout, settings):
        """Everything that has a sensible default and rarely needs changing."""
        box = layout.box()
        box.label(text="Seams", icon='EDGESEL')
        col = box.column(align=True)
        col.prop(settings, "seam_method", text="Method")

        if settings.seam_method == 'VSA':
            col.prop(settings, "auto_parameters")
            sub = col.column(align=True)
            sub.enabled = not settings.auto_parameters
            sub.prop(settings, "vsa_iterations", text="Refine")
            sub.prop(settings, "vsa_smooth_passes", text="Smooth Borders")
            sub.prop(settings, "vsa_crease_weight", text="Hide in Creases")
            sub.prop(settings, "vsa_min_cluster_faces", text="Min Faces")
            col.prop(settings, "vsa_area_weighted")
            col.prop(settings, "vsa_resolve_topology")
            col.prop(settings, "vsa_merge_clusters")
        else:
            col.prop(settings, "auto_curvature_threshold")
            col.prop(settings, "concave_seam_bias", text="Prefer Concave")
            col.prop(settings, "split_non_developable")
            if settings.split_non_developable:
                col.prop(settings, "split_max_cone_angle", text="Wrap Limit")
            col.prop(settings, "merge_islands")
            if settings.merge_islands:
                col.prop(settings, "merge_max_cone_angle", text="Flatness")
                col.prop(settings, "absorb_micro_islands")
                col.prop(settings, "minimum_island_face_count", text="Min Faces")
            col.prop(settings, "auto_seam_margin")
            if not settings.auto_seam_margin:
                col.prop(settings, "min_seam_edge_length", text="Min Edge Length")

        col.separator()
        col.prop(settings, "symmetrize_seams")
        if settings.symmetrize_seams:
            col.prop(settings, "symmetry_min_coverage", text="Threshold")
        col.prop(settings, "preserve_existing_seams")
        col.prop(settings, "separate_by_material")
        col.prop(settings, "prune_dangling_seams")

        box = layout.box()
        box.label(text="Result", icon='CHECKMARK')
        col = box.column(align=True)
        col.prop(settings, "run_preflight")
        if settings.run_preflight:
            col.prop(settings, "stop_on_blockers")
        col.prop(settings, "recover_failed_islands")
        if settings.recover_failed_islands:
            row = col.row(align=True)
            row.prop(settings, "recovery_rounds", text="Rounds")
            row.prop(settings, "recovery_tolerance", text="Tolerance")
        col.prop(settings, "minimize_stretch")
        if settings.minimize_stretch:
            col.prop(settings, "minimize_stretch_iterations", text="Iterations")
        col.prop(settings, "texture_sets")
        col.prop(settings, "use_udim")
        if settings.use_udim:
            col.prop(settings, "udim_max_tiles", text="Max Tiles")
        col.prop(settings, "orient_islands")
        col.prop(settings, "stack_duplicates")
        col.prop(settings, "normalize_texel_density")
        col.prop(settings, "auto_island_margin")
        if not settings.auto_island_margin:
            col.prop(settings, "island_margin", text="Margin")
        col.prop(settings, "target_coverage", text="Coverage")
        col.prop(settings, "backup_uv_layer")
        col.prop(settings, "uv_layer_name", text="UV Layer")
        col.prop(settings, "report_distortion")
        col.prop(settings, "check_overlaps")

        box = layout.box()
        box.label(text="Tools", icon='TOOL_SETTINGS')
        col = box.column(align=True)
        col.operator(IntelligentUV_OT_MarkSeams.bl_idname, icon='EDGESEL')
        col.prop(settings, "mark_bevel_debug")
        col.operator(IntelligentUV_OT_Diagnose.bl_idname, icon='CONSOLE')

        col.separator()
        col.prop(settings, "use_rizomuv")
        if settings.use_rizomuv:
            warn = col.box()
            warn.label(text="RizomUV Bridge (Windows)", icon='INFO')
            warn.prop(settings, "rizomuv_engine_mode", text="Mode")
            from .rizomuv_link import (
                ensure_link_on_path as _link_probe,
                is_available as _link_available,
                unavailable_reason as _link_reason,
            )
            # The probe is the only place that puts <install>\RizomUVLink on
            # sys.path, so it has to run before the availability check.
            _link_probe(getattr(settings, "rizomuv_path", "") or None)
            r = warn.row()
            if _link_available():
                r.label(text="Live link available", icon='CHECKMARK')
            else:
                r.label(text=_link_reason()[:120], icon='INFO')
            warn.prop(settings, "link_optimize")
            warn.prop(settings, "link_keep_open")
            warn.prop(settings, "rizomuv_timeout", text="Timeout (s)")
            warn.prop(settings, "keep_temp_files")
