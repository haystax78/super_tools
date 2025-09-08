import bpy
from bpy.types import Operator

from ..utils.align_points import PROP_POINTS, LABELS, get_point_object


class SUPERTOOLS_OT_delete_points_selected(Operator):
    bl_idname = "super_tools.delete_points_selected"
    bl_label = "Delete Points (Selected)"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        sel = list(context.selected_objects)
        if not sel:
            self.report({'WARNING'}, "No selected objects.")
            return {'CANCELLED'}

        # Only operate on meshes that actually have the custom property
        targets = [o for o in sel if o.type == 'MESH' and PROP_POINTS in o]
        if not targets:
            self.report({'WARNING'}, "No selected meshes with SuperAlignPoints.")
            return {'CANCELLED'}

        removed = 0
        for obj in targets:
            # Remove locator objects
            for label in LABELS:
                p = get_point_object(obj, label)
                if p is not None and p.name in bpy.data.objects:
                    try:
                        bpy.data.objects.remove(p, do_unlink=True)
                        removed += 1
                    except Exception:
                        pass
            # Remove the custom property entirely
            try:
                if PROP_POINTS in obj:
                    del obj[PROP_POINTS]
            except Exception:
                pass

        self.report({'INFO'}, f"Removed {removed} locator(s) from selected objects.")
        return {'FINISHED'}


def register():
    bpy.utils.register_class(SUPERTOOLS_OT_delete_points_selected)


def unregister():
    bpy.utils.unregister_class(SUPERTOOLS_OT_delete_points_selected)
