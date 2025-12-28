import bpy
from bpy.types import Operator


def get_channelbag_for_object(obj):
    """Get the channelbag for an object, handling both Blender 4.x and 5.0+ APIs."""
    ad = obj.animation_data
    if not ad or not ad.action:
        return None
    
    action = ad.action
    
    # Try Blender 5.0+ API first (slotted actions)
    try:
        from bpy_extras import anim_utils
        if hasattr(ad, 'action_slot') and ad.action_slot is not None:
            channelbag = anim_utils.action_get_channelbag_for_slot(action, ad.action_slot)
            return channelbag
    except (ImportError, AttributeError, TypeError):
        pass
    
    return None


def get_fcurves_for_object(obj):
    """Get fcurves for an object, handling both Blender 4.x and 5.0+ APIs."""
    ad = obj.animation_data
    if not ad or not ad.action:
        return None
    
    # Try Blender 5.0+ API first (slotted actions)
    channelbag = get_channelbag_for_object(obj)
    if channelbag is not None:
        return channelbag.fcurves
    
    # Fallback to legacy API (Blender 4.x and earlier)
    try:
        return ad.action.fcurves
    except AttributeError:
        return None


def remove_visibility_fcurves(obj):
    """Remove visibility fcurves from an object, handling both Blender 4.x and 5.0+ APIs."""
    # First, try to delete all keyframes on hide_viewport using keyframe_delete
    # This works across Blender versions
    try:
        obj.keyframe_delete(data_path="hide_viewport")
    except RuntimeError:
        # No keyframes to delete
        pass
    
    # Also try to clean up any remaining fcurves directly
    fcurves = get_fcurves_for_object(obj)
    if fcurves is None:
        return
    
    to_remove = [fc for fc in fcurves if fc.data_path == "hide_viewport"]
    for fc in to_remove:
        try:
            fcurves.remove(fc)
        except (RuntimeError, TypeError):
            pass


class SUPERTOOLS_OT_mesh_flipbook(Operator):
    bl_idname = "super_tools.mesh_flipbook"
    bl_label = "Sequential Vis (toggle)"
    bl_description = "Toggle sequential visibility keyframes for selected objects (adds if none, removes if present)"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        # Get duration from scene property
        duration = getattr(context.scene, 'supertools_seqvis_duration', 5)
        
        # Get stored object names from previous run
        stored_names = ""
        if hasattr(context.scene, 'supertools_seqvis_objects'):
            stored_names = context.scene.supertools_seqvis_objects or ""
        stored_list = [n.strip() for n in stored_names.split(";") if n.strip()]
        
        # If no selection, check if we have stored objects to reset
        if not context.selected_objects:
            if stored_list:
                # Reset stored objects
                reset_count = 0
                for name in stored_list:
                    obj = bpy.data.objects.get(name)
                    if obj:
                        remove_visibility_fcurves(obj)
                        obj.hide_viewport = False
                        reset_count += 1
                # Clear the stored list
                context.scene.supertools_seqvis_objects = ""
                self.report({'INFO'}, f"Reset {reset_count} objects to visible and removed keyframes.")
                return {'FINISHED'}
            else:
                self.report({'WARNING'}, "No objects selected and no stored objects to reset.")
                return {'CANCELLED'}
        
        # We have a selection - add sequential visibility keyframes
        if context.selected_objects:
            start_frame = context.scene.frame_start
            objs = list(context.selected_objects)

            # Baseline: hide all selected at start_frame
            for o in objs:
                o.hide_viewport = True
                o.keyframe_insert(data_path="hide_viewport", frame=start_frame)

            # For each object, make it visible for [f, f+duration-1], then hide at f+duration (except last)
            for i, obj in enumerate(objs):
                f = start_frame + i * duration

                # Visible ON at f
                obj.hide_viewport = False
                obj.keyframe_insert(data_path="hide_viewport", frame=f)

                # Stay visible through f+duration-1
                obj.keyframe_insert(data_path="hide_viewport", frame=f + duration - 1)

                # Turn OFF (hide) at f+duration if not last
                if i < len(objs) - 1:
                    obj.hide_viewport = True
                    obj.keyframe_insert(data_path="hide_viewport", frame=f + duration)

            # Force CONSTANT interpolation to avoid blending/overlap between boolean keys
            for obj in objs:
                fcurves = get_fcurves_for_object(obj)
                if fcurves:
                    for fc in fcurves:
                        if fc.data_path == "hide_viewport":
                            for kp in fc.keyframe_points:
                                kp.interpolation = 'CONSTANT'

            # Store the object names for later reset
            context.scene.supertools_seqvis_objects = ";".join(obj.name for obj in objs)
            
            self.report({'INFO'}, f"Sequential visibility keyframes added (duration={duration} frames each). Run again with no selection to reset.")
            return {'FINISHED'}
        else:
            self.report({'WARNING'}, "No objects selected. Nothing to keyframe.")
            return {'CANCELLED'}


def register():
    bpy.types.Scene.supertools_seqvis_duration = bpy.props.IntProperty(
        name="Duration",
        description="Number of frames each object stays visible",
        default=5,
        min=1,
        max=250,
    )
    bpy.types.Scene.supertools_seqvis_objects = bpy.props.StringProperty(
        name="Sequenced Objects",
        description="Semicolon-separated list of object names with sequential visibility keyframes",
        default="",
    )
    bpy.utils.register_class(SUPERTOOLS_OT_mesh_flipbook)


def unregister():
    bpy.utils.unregister_class(SUPERTOOLS_OT_mesh_flipbook)
    if hasattr(bpy.types.Scene, 'supertools_seqvis_objects'):
        del bpy.types.Scene.supertools_seqvis_objects
    if hasattr(bpy.types.Scene, 'supertools_seqvis_duration'):
        del bpy.types.Scene.supertools_seqvis_duration
