import bpy
from bpy.types import Operator
from bpy.props import BoolProperty

from ..utils.align_points import ensure_points_dict, set_point_name, get_point_object
from ..utils.align_raycast import is_view_nav_event, raycast_object_under_mouse
from ..utils.align_locators import create_locator


class SUPERTOOLS_OT_plot_points(Operator):
    bl_idname = "super_tools.plot_points"
    bl_label = "Plot Alignment Points"
    bl_options = {'REGISTER', 'UNDO'}

    running: BoolProperty(default=False)

    def invoke(self, context, event):
        obj = context.active_object
        if obj is None or obj.type != 'MESH':
            self.report({'ERROR'}, "Active object must be a Mesh")
            return {'CANCELLED'}

        self._target_obj = obj
        self._labels = ['A', 'B', 'C']
        self._index = 0

        ensure_points_dict(obj)
        # Remove any existing alignment locators on this object
        existing = [get_point_object(obj, k) for k in ('A', 'B', 'C')]
        for p in existing:
            if p is not None:
                try:
                    bpy.data.objects.remove(p, do_unlink=True)
                except Exception:
                    pass
        # Clear references
        d = obj.get("SuperAlignPoints", {"A": "", "B": "", "C": ""})
        for k in ("A", "B", "C"):
            d[k] = ""
        obj["SuperAlignPoints"] = d

        context.window_manager.modal_handler_add(self)
        self.running = True
        self.report({'INFO'}, "Click on the object to place A, B, and C points. ESC to cancel.")
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        if is_view_nav_event(event):
            return {'PASS_THROUGH'}

        if event.type in {'ESC'}:
            self.running = False
            return {'CANCELLED'}

        if (event.type == 'LEFTMOUSE' and event.value == 'PRESS'
                and not (event.alt or event.shift or event.ctrl)):
            hit_loc = raycast_object_under_mouse(context, event, self._target_obj)
            if hit_loc is not None:
                label = self._labels[self._index]
                locator = create_locator(self._target_obj, label, hit_loc)
                set_point_name(self._target_obj, label, locator.name)

                self._index += 1
                if self._index >= len(self._labels):
                    self.running = False
                    self.report({'INFO'}, "Alignment points A, B, C set.")
                    return {'FINISHED'}
                else:
                    self.report({'INFO'}, f"Placed {label}. Click to place {self._labels[self._index]}.")
            else:
                self.report({'WARNING'}, "No hit detected on object under mouse.")

        return {'RUNNING_MODAL'}


def register():
    bpy.utils.register_class(SUPERTOOLS_OT_plot_points)


def unregister():
    bpy.utils.unregister_class(SUPERTOOLS_OT_plot_points)
