# pylint: disable=invalid-name
"""Intelligent UV Mapping — pre-flight check operator."""


from ..mesh_analysis import MeshAnalyzer
from ..preflight import BLOCKER, Preflight
from ..validation import ContextGuard

from .base import IntelligentUVBaseOperator


class IntelligentUV_OT_Check(IntelligentUVBaseOperator):
    """Reports what would spoil the unwrap, without changing anything."""

    bl_idname = "intelligent_uv.check"
    bl_label = "Check Mesh"
    bl_description = (
        "Look for the problems that make unwrapping fail, and say what to do "
        "about each one. Changes nothing"
    )
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        obj = ContextGuard.get_context_object(context)
        return bool(obj) and obj.type == 'MESH'

    def execute(self, context):
        obj = ContextGuard.get_context_object(context)

        try:
            mesh_analysis = MeshAnalyzer.analyze(obj.data)
        except Exception as exc:
            self.report({'ERROR'}, f"Could not read the mesh: {exc}")
            return {'CANCELLED'}

        result = Preflight.run(obj, mesh_analysis)

        # Blockers first: a list ordered by severity is read top-down and the
        # reader stops when they have enough to act on.
        for finding in result.findings:
            level = (
                {'ERROR'} if finding.severity == BLOCKER
                else {'WARNING'} if finding.severity == "WARNING"
                else {'INFO'}
            )
            self.report(level, finding.format())

        self.report(
            {'INFO'} if result.ok else {'WARNING'}, result.summary()
        )
        return {'FINISHED'}
