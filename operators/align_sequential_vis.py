import bpy
from bpy.types import Operator


class SUPERTOOLS_OT_mesh_flipbook(Operator):
    bl_idname = "super_tools.mesh_flipbook"
    bl_label = "Sequential Vis (toggle)"
    bl_description = "Toggle sequential visibility keyframes for selected objects (adds if none, removes if present)"
    bl_options = {'REGISTER', 'UNDO'}

    duration: bpy.props.IntProperty(
        name="Duration",
        description="Number of frames each object stays visible",
        default=5,
        min=1,
        max=250,
    )

    def execute(self, context):
        duration = int(self.duration)
        objects = context.selected_objects or list(context.scene.objects)

        if not objects:
            self.report({'WARNING'}, "No objects found.")
            return {'CANCELLED'}

        # Check if keyframes already exist on any of the objects
        def has_visibility_keys(obj):
            ad = obj.animation_data
            if not (ad and ad.action):
                return False
            for fc in ad.action.fcurves:
                if fc.data_path in {"hide_viewport", "hide_render"}:
                    return True
            return False

        has_keys = any(has_visibility_keys(obj) for obj in objects)

        if has_keys:
            # Remove all visibility keyframes, restore visibility
            for obj in objects:
                ad = obj.animation_data
                if ad and ad.action:
                    for fcurve in list(ad.action.fcurves):
                        if fcurve.data_path in {"hide_viewport", "hide_render"}:
                            ad.action.fcurves.remove(fcurve)
                obj.hide_viewport = False
                obj.hide_render = False
            self.report({'INFO'}, "Visibility keyframes removed and all objects made visible.")
            return {'FINISHED'}

        # Add sequential visibility keyframes only if there are selected objects
        if context.selected_objects:
            start_frame = context.scene.frame_start
            objs = list(context.selected_objects)

            # Baseline: hide all selected at start_frame
            for o in objs:
                o.hide_viewport = True
                o.hide_render = True
                o.keyframe_insert(data_path="hide_viewport", frame=start_frame)
                o.keyframe_insert(data_path="hide_render", frame=start_frame)

            # For each object, make it visible for [f, f+duration-1], then hide at f+duration (except last)
            for i, obj in enumerate(objs):
                f = start_frame + i * duration

                # Visible ON at f
                obj.hide_viewport = False
                obj.hide_render = False
                obj.keyframe_insert(data_path="hide_viewport", frame=f)
                obj.keyframe_insert(data_path="hide_render", frame=f)

                # Stay visible through f+duration-1
                obj.hide_viewport = False
                obj.hide_render = False
                obj.keyframe_insert(data_path="hide_viewport", frame=f + duration - 1)
                obj.keyframe_insert(data_path="hide_render", frame=f + duration - 1)

                # Turn OFF (hide) at f+duration if not last
                if i < len(objs) - 1:
                    obj.hide_viewport = True
                    obj.hide_render = True
                    obj.keyframe_insert(data_path="hide_viewport", frame=f + duration)
                    obj.keyframe_insert(data_path="hide_render", frame=f + duration)

            # Force CONSTANT interpolation to avoid blending/overlap between boolean keys
            for obj in objs:
                ad = obj.animation_data
                if ad and ad.action:
                    for fc in ad.action.fcurves:
                        if fc.data_path in {"hide_viewport", "hide_render"}:
                            for kp in fc.keyframe_points:
                                kp.interpolation = 'CONSTANT'

            self.report({'INFO'}, f"Sequential visibility keyframes added (duration={duration} frames each).")
            return {'FINISHED'}
        else:
            self.report({'WARNING'}, "No objects selected. Nothing to keyframe.")
            return {'CANCELLED'}


def register():
    bpy.utils.register_class(SUPERTOOLS_OT_mesh_flipbook)


def unregister():
    bpy.utils.unregister_class(SUPERTOOLS_OT_mesh_flipbook)
