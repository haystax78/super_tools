import bpy
from bpy.types import Operator
from mathutils import Matrix

from ..utils.align_points import get_object_points_world, PROP_POINTS
from ..utils.align_similarity import compute_similarity_transform_from_points


class SUPERTOOLS_OT_align_to_active(Operator):
    bl_idname = "super_tools.align_to_active"
    bl_label = "Align To Active"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        sel = getattr(context, "selected_objects", None) or []
        meshes = [o for o in sel if getattr(o, 'type', None) == 'MESH']
        if len(meshes) < 2:
            return False
        if context.active_object not in meshes:
            return False
        # All selected meshes must have our custom property present
        return all(PROP_POINTS in o for o in meshes)

    def execute(self, context):
        sel = [o for o in context.selected_objects if o.type == 'MESH']
        if len(sel) < 2:
            self.report({'ERROR'}, "Select at least two mesh objects with alignment points.")
            return {'CANCELLED'}
        target = context.active_object
        if target not in sel:
            self.report({'ERROR'}, "Active object must be among the selection.")
            return {'CANCELLED'}

        tgt_pts = get_object_points_world(target)
        if tgt_pts is None:
            self.report({'ERROR'}, f"Active object '{target.name}' does not have A, B, C points.")
            return {'CANCELLED'}
        T_A, T_B, T_C = tgt_pts

        aligned_count = 0

        for obj in sel:
            if obj == target:
                continue
            src_pts = get_object_points_world(obj)
            if src_pts is None:
                self.report({'WARNING'}, f"Skipping '{obj.name}': missing A, B, C points.")
                continue
            S_A, S_B, S_C = src_pts

            try:
                R, s, t = compute_similarity_transform_from_points(S_A, S_B, S_C, T_A, T_B, T_C)
            except Exception as e:
                self.report({'WARNING'}, f"'{obj.name}' transform solve failed: {e}")
                continue

            R4 = R.to_4x4()
            S4 = Matrix.Diagonal((s, s, s, 1.0))
            T4 = Matrix.Translation(t)
            M = T4 @ R4 @ S4

            obj.matrix_world = M @ obj.matrix_world
            aligned_count += 1

        self.report({'INFO'}, f"Aligned {aligned_count} object(s) to '{target.name}'.")
        return {'FINISHED'}


def register():
    bpy.utils.register_class(SUPERTOOLS_OT_align_to_active)


def unregister():
    bpy.utils.unregister_class(SUPERTOOLS_OT_align_to_active)
