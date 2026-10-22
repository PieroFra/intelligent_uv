# pylint: disable=invalid-name
"""
Intelligent UV Mapping — VALIDATION RESULT / CONTEXT GUARD

Structured validation results and context checking.
"""

import bpy


# =============================================================================
# 2. VALIDATION RESULT — Structured Validation Output
# =============================================================================

class ValidationResult:
    """Contains success status, errors, warnings and context information."""

    def __init__(self):
        self.ok = False
        self.errors = []
        self.warnings = []
        self.info = []

        self.object = None
        self.mode = ""
        self.face_count = 0
        self.selected_face_count = 0
        self.material_slot_count = 0
        self.modifier_count = 0

    def add_error(self, message):
        self.errors.append(message)
        self.ok = False

    def add_warning(self, message):
        if message not in self.warnings:
            self.warnings.append(message)

    def add_info(self, message):
        if message not in self.info:
            self.info.append(message)

    @property
    def has_errors(self):
        return len(self.errors) > 0

    @property
    def has_warnings(self):
        return len(self.warnings) > 0

    def error_message(self):
        return " | ".join(self.errors) if self.errors else ""

    def warning_message(self):
        return " | ".join(self.warnings) if self.warnings else ""

# =============================================================================
# 3. CONTEXT GUARD — Advanced Context Validation
# =============================================================================

class ContextGuard:
    """Centralized management of context validity for the add-on."""

    SUPPORTED_MODES = ('OBJECT', 'EDIT_MESH')

    @staticmethod
    def get_context_object(context):
        obj = getattr(context, "active_object", None)
        if not obj:
            obj = getattr(context, "object", None)
        return obj

    @staticmethod
    def get_context_mode(context):
        mode = getattr(context, "mode", "")
        return mode.upper() if isinstance(mode, str) else ""

    @classmethod
    def validate_for_uv(cls, context):
        """Validates the context for UV execution."""
        result = ValidationResult()
        obj = cls.get_context_object(context)
        mode = cls.get_context_mode(context)
        result.mode = mode or "UNKNOWN"

        if not obj:
            result.add_error("No active object found.")
            return result

        result.object = obj

        if obj.type != 'MESH':
            result.add_error(
                f"The active object '{obj.name}' is not a Mesh, but {obj.type}."
            )
            return result

        mesh_data = getattr(obj, "data", None)
        if not mesh_data:
            result.add_error("The mesh object does not expose valid mesh data.")
            return result

        polygons = getattr(mesh_data, "polygons", [])
        face_count = len(polygons) if hasattr(polygons, "__len__") else 0
        result.face_count = face_count

        if face_count == 0:
            result.add_error("The active mesh has no faces. Select a valid mesh.")
            return result

        if mode not in cls.SUPPORTED_MODES:
            result.add_error(
                f"Mode not supported for the UV workflow: '{result.mode}'. "
                "Use Object Mode or Edit Mesh."
            )
            return result

        if mode == 'EDIT_MESH':
            selected_faces = 0
            try:
                import array as _array

                select_buf = None
                if hasattr(polygons, "foreach_get"):
                    try:
                        select_buf = _array.array('b', [0] * face_count)
                        polygons.foreach_get("select", select_buf)
                    except Exception:
                        select_buf = None

                if select_buf is not None:
                    selected_faces = sum(1 for flag in select_buf if flag)
                else:
                    for poly in polygons:
                        if getattr(poly, "select", False):
                            selected_faces += 1
            except Exception:
                selected_faces = 0

            result.selected_face_count = selected_faces

            if selected_faces == 0:
                result.add_warning(
                    "No faces selected in Edit Mode. "
                    "The workflow will select all faces for the base unwrap."
                )
        else:
            result.selected_face_count = face_count

        # Non-blocking warnings
        try:
            if hasattr(obj, "visible_get") and not obj.visible_get():
                result.add_warning(
                    f"The object '{obj.name}' is hidden or not visible in the viewport."
                )
        except (AttributeError, TypeError):
            # A: viewport visibility API differs across Blender versions.
            pass

        try:
            view_layer = getattr(context, "view_layer", None) or bpy.context.view_layer
            if view_layer and obj.name not in view_layer.objects:
                result.add_warning(
                    f"The object '{obj.name}' is not present in the current View Layer."
                )
        except (AttributeError, TypeError, KeyError):
            # A: view-layer object lookup differs across Blender versions.
            pass

        try:
            modifiers = getattr(obj, "modifiers", [])
            if hasattr(modifiers, "__len__"):
                result.modifier_count = len(modifiers)
                if result.modifier_count > 0:
                    result.add_warning(
                        f"The object has {result.modifier_count} active modifiers. "
                        "The workflow uses the base mesh."
                    )
        except (AttributeError, TypeError):
            # A: modifier collection access differs across Blender versions.
            pass

        try:
            material_slots = getattr(obj, "material_slots", [])
            if hasattr(material_slots, "__len__"):
                result.material_slot_count = len(material_slots)
        except (AttributeError, TypeError):
            # A: material slot collection access differs across Blender versions.
            pass

        if not result.has_errors:
            result.ok = True
            result.add_info(
                f"Context valid: '{obj.name}' ({result.mode}). Faces: {face_count}."
            )

        return result
