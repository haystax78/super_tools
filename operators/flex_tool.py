"""
Flex Tool Operator for Super Tools addon.
This module contains the main operator for creating 3D curves in the viewport.
"""
import bpy
import blf
import gpu
from gpu_extras.batch import batch_for_shader
import math
import time
from bpy_extras import view3d_utils
from mathutils import Vector, Matrix
import json

from ..utils.flex_state import state, load_custom_profiles_from_scene, save_custom_profiles_to_scene
from ..utils import flex_conversion as conversion
from ..utils import flex_math as math_utils
from ..utils import flex_mesh as mesh_utils
from .flex_operator_base import FlexOperatorBase
from . import flex_drawing
from . import flex_interaction_base


class MESH_OT_flex_create(FlexOperatorBase):
    """Draw a curve in 3D space to create a flex mesh"""
    bl_idname = "mesh.flex_create"
    bl_label = "Flex Create"
    bl_options = {'REGISTER', 'UNDO'}
    
    original_mode: bpy.props.StringProperty(default="")
    
    def draw_callback_px(self, context, _unused=None):
        """Draw the curve points and lines in the viewport"""
        flex_drawing.draw_callback_px(self, context)
    
    def invoke(self, context, event):
        """Initialize the operator when it's invoked"""
        if context.area.type != 'VIEW_3D':
            return {'CANCELLED'}
        
        # Prevent re-invocation while already running
        if state.is_running:
            self.report({'WARNING'}, "Flex tool is already active")
            return {'CANCELLED'}
            
        self.original_mode = context.mode

        edit_target = None
        if context.mode != 'SCULPT':
            if context.active_object and context.active_object.select_get():
                ao = context.active_object
                if ("flex_curve_data" in ao) or ("sculpt_kit_curve_data" in ao) or ("sculpt_buddy_curve_data" in ao):
                    edit_target = ao

        if edit_target is not None:
            return self._invoke_edit_mode(context, event, edit_target)
        
        return self._invoke_create_mode(context, event)
    
    def _invoke_create_mode(self, context, event):
        """Initialize for creating a new flex mesh"""
        state.initialize()
        load_custom_profiles_from_scene()
        state.is_running = True
        self._editing_existing = False

        depth_reference_world_point = None
        if context.active_object and context.active_object.type == 'MESH':
            if state.preview_mesh_obj is None or context.active_object != state.preview_mesh_obj:
                depth_reference_world_point = context.active_object.matrix_world.translation.copy()

        rv3d = context.space_data.region_3d if context.space_data else None
        if rv3d:
            view_matrix = rv3d.view_matrix
            view_dir = (view_matrix.inverted().to_3x3() @ Vector((0, 0, -1))).normalized()
            
            if depth_reference_world_point:
                state.construction_plane_origin = depth_reference_world_point
            else:
                state.construction_plane_origin = Vector((0, 0, 0))
            state.construction_plane_normal = view_dir
            state.last_camera_matrix = view_matrix.copy()
        else:
            state.last_camera_matrix = None
            state.construction_plane_origin = Vector((0, 0, 0))
            state.construction_plane_normal = Vector((0, 0, 1))

        for obj in context.selected_objects:
            obj.select_set(False)

        state.save_history_state()

        if state.draw_handle:
            try:
                bpy.types.SpaceView3D.draw_handler_remove(state.draw_handle, 'WINDOW')
            except Exception as e:
                print(f"Flex: Error removing drawing handler: {e}")
            state.draw_handle = None

        args = (self, context)
        state.draw_handle = bpy.types.SpaceView3D.draw_handler_add(self.draw_callback_px, args, 'WINDOW', 'POST_PIXEL')
        context.area.tag_redraw()
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}
    
    def _invoke_edit_mode(self, context, event, edit_target):
        """Initialize for editing an existing flex mesh"""
        state.initialize()
        load_custom_profiles_from_scene()
        state.is_running = True
        self._editing_existing = True

        muscle_obj = edit_target
        state.object_matrix_world = muscle_obj.matrix_world.copy()

        self._original_muscle_obj_name = muscle_obj.name
        self._original_world_matrix = muscle_obj.matrix_world.copy()
        
        self._original_material = None
        if len(muscle_obj.data.materials) > 0 and muscle_obj.data.materials[0]:
            self._original_material = muscle_obj.data.materials[0]
        
        self._original_shade_smooth = False
        if muscle_obj.data.polygons:
            self._original_shade_smooth = muscle_obj.data.polygons[0].use_smooth

        state.mirror_mode_active = False
        state.mirror_flip_x = False
        for mod in muscle_obj.modifiers:
            if mod.name in ("Flex_Mirror", "SculptKit_Mirror") and mod.type == 'MIRROR':
                state.mirror_mode_active = True
                state.mirror_flip_x = mod.use_bisect_flip_axis[0]
                break

        state.original_modifiers = []
        for mod in muscle_obj.modifiers:
            mod_data = {'name': mod.name, 'type': mod.type, 'properties': {}, 'object_references': {}, 'node_group': None}
            for prop in dir(mod):
                if not prop.startswith('__') and not prop.startswith('bl_') and prop != 'type':
                    try:
                        value = getattr(mod, prop)
                        if isinstance(value, bpy.types.Object):
                            mod_data['object_references'][prop] = value.name
                        elif isinstance(value, bpy.types.Collection):
                            mod_data['object_references'][prop] = value.name
                        elif isinstance(value, bpy.types.NodeTree):
                            mod_data['node_group'] = value.name
                        elif isinstance(value, (int, float, bool, str)):
                            mod_data['properties'][prop] = value
                    except:
                        pass
            state.original_modifiers.append(mod_data)

        self._original_parent = muscle_obj.parent
        self._original_parent_type = muscle_obj.parent_type
        self._original_parent_bone = muscle_obj.parent_bone if muscle_obj.parent_type == 'BONE' else ''
        self._original_matrix_parent_inverse = muscle_obj.matrix_parent_inverse.copy()
        self._original_collections = [c.name for c in muscle_obj.users_collection]
        self._original_children = []
        for child in muscle_obj.children:
            self._original_children.append({
                'name': child.name,
                'parent_type': child.parent_type,
                'parent_bone': child.parent_bone if child.parent_type == 'BONE' else '',
                'matrix_world': child.matrix_world.copy(),
                'matrix_parent_inverse': child.matrix_parent_inverse.copy(),
            })
        
        # Unparent children using CLEAR_KEEP_TRANSFORM
        for child_data in self._original_children:
            child = bpy.data.objects.get(child_data['name'])
            if child:
                bpy.ops.object.select_all(action='DESELECT')
                child.select_set(True)
                context.view_layer.objects.active = child
                bpy.ops.object.parent_clear(type='CLEAR_KEEP_TRANSFORM')

        curve_data_json = None
        for key in ("flex_curve_data", "sculpt_kit_curve_data", "sculpt_buddy_curve_data"):
            if key in muscle_obj:
                curve_data_json = muscle_obj[key]
                break

        if curve_data_json:
            try:
                curve_data = json.loads(curve_data_json)
                offset_dict = curve_data.get("metadata_origin")
                if offset_dict:
                    metadata_origin = Vector((offset_dict.get("x", 0.0), offset_dict.get("y", 0.0), offset_dict.get("z", 0.0)))
                else:
                    metadata_origin = Vector((0.0, 0.0, 0.0))

                if "curve_points" in curve_data:
                    for point_data in curve_data["curve_points"]:
                        point = Vector((point_data["x"], point_data["y"], point_data["z"]))
                        state.points_3d.append(point)

                if "radii" in curve_data:
                    state.point_radii_3d = curve_data["radii"]

                if "tensions" in curve_data:
                    state.point_tensions = curve_data["tensions"]

                if "no_tangent_points" in curve_data:
                    state.no_tangent_points = set(curve_data["no_tangent_points"])

                state.start_cap_type = curve_data.get('start_cap_type', 1)
                state.end_cap_type = curve_data.get('end_cap_type', 1)
                state.profile_aspect_ratio = curve_data.get('profile_aspect_ratio', 1.0)
                state.profile_global_twist = curve_data.get('profile_global_twist', 0.0)
                state.profile_point_twists = curve_data.get('profile_point_twists', [])
                state.profile_global_type = curve_data.get('profile_global_type', state.PROFILE_CIRCULAR)
                state.profile_roundness = curve_data.get('profile_roundness', 0.3)
                state.profile_point_roundness = curve_data.get('profile_point_roundness', [])
                
                loaded_custom_points = curve_data.get('custom_profile_points', [])
                if loaded_custom_points:
                    state.custom_profile_points = [tuple(p) for p in loaded_custom_points]
                    state.custom_profile_curve_name = curve_data.get('custom_profile_curve_name', None)
                state.adaptive_segmentation = curve_data.get('adaptive_segmentation', False)
                
                if "bspline_mode" in curve_data:
                    state.bspline_mode = bool(curve_data.get("bspline_mode", False))

                while len(state.profile_point_twists) < len(state.points_3d):
                    state.profile_point_twists.append(0.0)

                if "resolution" in curve_data:
                    self.resolution = curve_data["resolution"]
                if "segments" in curve_data:
                    self.segments = curve_data["segments"]

                if not curve_data.get("in_object_space", True):
                    matrix_world_inv = muscle_obj.matrix_world.inverted_safe()
                    for i, point in enumerate(state.points_3d):
                        state.points_3d[i] = matrix_world_inv @ point

                state.object_matrix_world = muscle_obj.matrix_world.copy()
            except Exception as e:
                self.report({'ERROR'}, f"Failed to load curve data: {e}")
                return {'CANCELLED'}
        else:
            self.report({'ERROR'}, "No curve data found on the selected object")
            return {'CANCELLED'}

        muscle_obj.hide_viewport = True
        self._original_hide_viewport = muscle_obj.hide_viewport
        state.edited_object_name = muscle_obj.name

        # Set up construction plane using the first point of the curve as reference
        # This ensures consistent depth placement matching create mode behavior
        rv3d = context.space_data.region_3d if context.space_data else None
        if rv3d:
            view_matrix = rv3d.view_matrix
            view_dir = (view_matrix.inverted().to_3x3() @ Vector((0, 0, -1))).normalized()
            
            # Use the first curve point (in world space) as the construction plane origin
            if len(state.points_3d) > 0 and state.object_matrix_world:
                first_point_world = state.object_matrix_world @ state.points_3d[0]
                state.construction_plane_origin = first_point_world
            else:
                state.construction_plane_origin = muscle_obj.matrix_world.translation.copy()
            
            state.construction_plane_normal = view_dir
            state.last_camera_matrix = view_matrix.copy()
        else:
            state.last_camera_matrix = None
            state.construction_plane_origin = Vector((0, 0, 0))
            state.construction_plane_normal = Vector((0, 0, 1))

        for obj in context.selected_objects:
            obj.select_set(False)

        state.save_history_state()

        if len(state.points_3d) >= 2 and len(state.point_radii_3d) >= 2:
            mesh_utils.update_preview_mesh(
                context,
                state.points_3d,
                state.point_radii_3d,
                resolution=self.resolution,
                segments=self.segments,
            )
            if state.preview_mesh_obj is not None:
                mesh_utils.update_preview_mesh(
                    context,
                    state.points_3d,
                    state.point_radii_3d,
                    resolution=self.resolution,
                    segments=self.segments,
                )

        if state.draw_handle:
            try:
                bpy.types.SpaceView3D.draw_handler_remove(state.draw_handle, 'WINDOW')
            except Exception as e:
                print(f"Flex: Error removing drawing handler: {e}")
            state.draw_handle = None

        args = (self, context)
        state.draw_handle = bpy.types.SpaceView3D.draw_handler_add(self.draw_callback_px, args, 'WINDOW', 'POST_PIXEL')
        context.area.tag_redraw()
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}
    
    def modal(self, context, event):
        """Handle modal events"""
        if not self.is_mouse_in_region(context, event):
            return {'PASS_THROUGH'}
        
        self.check_camera_movement(context)
        
        return flex_interaction_base.modal_handler(self, context, event)
    
    def cancel(self, context):
        """Called when the operator is cancelled (e.g., via Undo)"""
        self._edit_cancelled = True
        self.finish(context)
        return {'CANCELLED'}
    
    def finish(self, context):
        """Finish the operator and create the final mesh"""
        if getattr(self, '_edit_cancelled', False):
            self._cleanup(context)
            return
        
        self._finalize(context)
        self._cleanup(context)
    
    def _cleanup(self, context):
        """Clean up resources when operator is cancelled"""
        # Set is_running to False first to stop draw callbacks
        state.is_running = False
        
        if state.draw_handle:
            try:
                bpy.types.SpaceView3D.draw_handler_remove(state.draw_handle, 'WINDOW')
            except:
                pass
            state.draw_handle = None
        
        # Clean up preview materials (remove any orphaned Flex_Preview_Material)
        for mat in list(bpy.data.materials):
            if mat.name.startswith("Flex_Preview_Material") and mat.users == 0:
                bpy.data.materials.remove(mat)
        
        # Handle original object restoration or deletion
        original_name = getattr(self, '_original_muscle_obj_name', None)
        if original_name and original_name in bpy.data.objects:
            orig_obj = bpy.data.objects[original_name]
            if getattr(self, '_edit_cancelled', False):
                # Restore the original object when edit is cancelled
                orig_obj.hide_viewport = False
                orig_obj.hide_set(False)
                orig_obj.select_set(True)
                context.view_layer.objects.active = orig_obj
                
                # Reparent children back to the original object on cancel
                original_children = getattr(self, '_original_children', [])
                for child_data in original_children:
                    child = bpy.data.objects.get(child_data['name'])
                    if child:
                        bpy.ops.object.select_all(action='DESELECT')
                        child.select_set(True)
                        orig_obj.select_set(True)
                        context.view_layer.objects.active = orig_obj
                        bpy.ops.object.parent_set(type='OBJECT', keep_transform=False)
            elif not getattr(self, '_edit_cancelled', False) and not getattr(self, '_edit_completed', False):
                # Delete the original object after successful finalization
                try:
                    orig_obj.hide_viewport = False
                    orig_obj.hide_set(False)
                    for collection in orig_obj.users_collection:
                        collection.objects.unlink(orig_obj)
                    bpy.data.objects.remove(orig_obj)
                    self._edit_completed = True
                except Exception as e:
                    print(f"Failed to delete original flex mesh: {e}")
        
        # Reset transformation and modifier variables
        state.object_matrix_world = None
        state.original_modifiers = []
        
        state.cleanup()
        context.area.tag_redraw()
    
    def _finalize(self, context, do_cleanup=True):
        """Finalize the flex mesh creation.
        
        Args:
            context: Blender context
            do_cleanup: If True, cleanup resources after finalization. 
                       Set to False when using accept-and-continue.
        """
        if len(state.points_3d) < 2:
            if do_cleanup:
                self._cleanup(context)
            return
        
        # Create the final mesh
        final_obj = mesh_utils.create_flex_mesh_from_curve(
            context,
            state.points_3d,
            state.point_radii_3d,
            resolution=self.resolution,
            segments=self.segments,
            tensions=state.point_tensions,
            no_tangent_points=state.no_tangent_points,
            is_preview=False
        )
        
        if final_obj:
            # Clear any preview material from final object
            if final_obj.data.materials:
                while len(final_obj.data.materials) > 0:
                    final_obj.data.materials.pop(index=0)
            
            # Restore original material if editing, otherwise assign default
            original_mat = getattr(self, '_original_material', None)
            if original_mat is not None:
                final_obj.data.materials.append(original_mat)
            else:
                # Create or get default flex material
                default_mat = bpy.data.materials.get("Flex_Material")
                if default_mat is None:
                    default_mat = bpy.data.materials.new("Flex_Material")
                    default_mat.use_nodes = True
                    nodes = default_mat.node_tree.nodes
                    nodes.clear()
                    bsdf = nodes.new(type='ShaderNodeBsdfPrincipled')
                    bsdf.location = (0, 0)
                    bsdf.inputs['Base Color'].default_value = (0.268, 0.133, 0.101, 1.0)
                    bsdf.inputs['Roughness'].default_value = 0.6
                    output = nodes.new(type='ShaderNodeOutputMaterial')
                    output.location = (300, 0)
                    default_mat.node_tree.links.new(bsdf.outputs['BSDF'], output.inputs['Surface'])
                final_obj.data.materials.append(default_mat)
            
            # Restore original modifiers if editing an existing object
            # Skip mirror modifiers as we handle them separately via apply_mirror_modifier()
            original_modifiers = getattr(state, 'original_modifiers', [])
            for mod_data in original_modifiers:
                # Skip mirror modifiers - we apply these separately
                if mod_data.get('name') in ("Flex_Mirror", "SculptKit_Mirror") and mod_data.get('type') == 'MIRROR':
                    continue
                
                try:
                    new_mod = final_obj.modifiers.new(name=mod_data['name'], type=mod_data['type'])
                    
                    # Restore node_group for Geometry Nodes modifiers (must be set first)
                    node_group_name = mod_data.get('node_group')
                    if node_group_name and hasattr(new_mod, 'node_group'):
                        if node_group_name in bpy.data.node_groups:
                            new_mod.node_group = bpy.data.node_groups[node_group_name]
                    
                    # Set all the stored properties
                    for prop_name, prop_value in mod_data.get('properties', {}).items():
                        try:
                            if hasattr(new_mod, prop_name):
                                setattr(new_mod, prop_name, prop_value)
                        except:
                            pass
                    
                    # Handle object references (like mirror object)
                    for prop_name, obj_name in mod_data.get('object_references', {}).items():
                        try:
                            if hasattr(new_mod, prop_name):
                                # Remap old mirror empty names to flex_mirror_empty
                                if prop_name == 'mirror_object' and obj_name in ("mirror_obj_empty", "SculptKit_mirror_empty"):
                                    obj_name = state.mirror_empty_name
                                
                                if obj_name in bpy.data.objects:
                                    setattr(new_mod, prop_name, bpy.data.objects[obj_name])
                                elif obj_name in bpy.data.collections:
                                    setattr(new_mod, prop_name, bpy.data.collections[obj_name])
                        except:
                            pass
                except Exception as e:
                    print(f"Failed to restore modifier {mod_data.get('name', 'unknown')}: {e}")
            
            # Add Smooth by Angle modifier if enabled in preferences (for new meshes only)
            if not getattr(self, '_editing_existing', False):
                prefs = None
                try:
                    addon_prefs = bpy.context.preferences.addons.get("super_tools")
                    if addon_prefs:
                        prefs = addon_prefs.preferences
                except Exception:
                    pass
                
                if prefs and getattr(prefs, 'flex_add_smooth_by_angle', False):
                    import math
                    angle_rad = getattr(prefs, 'flex_smooth_by_angle_value', 0.523599)
                    
                    # Use the mesh auto_smooth_angle attribute (Blender 4.1+)
                    try:
                        # Set auto smooth angle on the mesh data
                        final_obj.data.use_auto_smooth = True
                        final_obj.data.auto_smooth_angle = angle_rad
                    except AttributeError:
                        # For Blender 4.1+ where auto_smooth is handled differently
                        # Try to add the Smooth by Angle geometry nodes modifier
                        try:
                            # First check if node group already exists
                            if "Smooth by Angle" in bpy.data.node_groups:
                                smooth_mod = final_obj.modifiers.new(name="Smooth by Angle", type='NODES')
                                smooth_mod.node_group = bpy.data.node_groups["Smooth by Angle"]
                                smooth_mod["Socket_1"] = angle_rad
                            else:
                                # Select the object and use the operator
                                orig_active = context.view_layer.objects.active
                                orig_selected = [o for o in context.selected_objects]
                                
                                bpy.ops.object.select_all(action='DESELECT')
                                final_obj.select_set(True)
                                context.view_layer.objects.active = final_obj
                                
                                # Try to add from essentials library
                                try:
                                    bpy.ops.object.modifier_add_node_group(
                                        asset_library_type='ESSENTIALS',
                                        asset_library_identifier="",
                                        relative_asset_identifier="geometry_nodes/smooth_by_angle.blend/NodeTree/Smooth by Angle"
                                    )
                                    # Set the angle on the newly added modifier
                                    for mod in final_obj.modifiers:
                                        if mod.type == 'NODES' and mod.node_group and "Smooth by Angle" in mod.node_group.name:
                                            mod["Socket_1"] = angle_rad
                                            break
                                except Exception:
                                    pass
                                
                                # Restore selection
                                bpy.ops.object.select_all(action='DESELECT')
                                for o in orig_selected:
                                    if o:
                                        o.select_set(True)
                                if orig_active:
                                    context.view_layer.objects.active = orig_active
                        except Exception:
                            pass
            
            # Apply mirror modifier if active (uses flex_mirror_empty)
            if state.mirror_mode_active:
                mesh_utils.apply_mirror_modifier(final_obj, True)
                mesh_utils.update_mirror_flip_from_points(final_obj, state.points_3d)
            
            # Handle parenting based on Parent Mode selection
            # None = not set (restore original parent if editing)
            # "" = explicitly cleared (no parent)
            # "ObjectName" = set to specific parent
            selected_parent = getattr(state, 'selected_parent_name', None)
            
            if selected_parent is not None and selected_parent != "":
                # Parent was explicitly set to an object
                parent_obj = bpy.data.objects.get(selected_parent)
                if parent_obj and parent_obj != final_obj:
                    child_world_before_parent = final_obj.matrix_world.copy()
                    final_obj.parent = parent_obj
                    try:
                        final_obj.parent_type = 'OBJECT'
                    except TypeError:
                        pass
                    parent_world_mat = parent_obj.matrix_world if hasattr(parent_obj, 'matrix_world') else None
                    if parent_world_mat is not None:
                        final_obj.matrix_parent_inverse = parent_world_mat.inverted() @ child_world_before_parent
                        final_obj.matrix_world = child_world_before_parent
            elif selected_parent == "":
                # Parent was explicitly cleared - do not parent
                final_obj.parent = None
            else:
                # selected_parent is None - restore original parent if editing existing object
                original_parent = getattr(self, "_original_parent", None)
                if original_parent is not None and original_parent != final_obj:
                    child_world_before_parent = final_obj.matrix_world.copy()
                    final_obj.parent = original_parent
                    original_parent_type = getattr(self, "_original_parent_type", 'OBJECT')
                    try:
                        final_obj.parent_type = original_parent_type
                    except TypeError:
                        pass
                    parent_world_mat = None
                    if original_parent_type == 'BONE':
                        final_obj.parent_bone = getattr(self, "_original_parent_bone", '')
                        bone_name = getattr(self, "_original_parent_bone", '')
                        try:
                            pb = original_parent.pose.bones.get(bone_name) if hasattr(original_parent, 'pose') else None
                            if pb is not None:
                                parent_world_mat = original_parent.matrix_world @ pb.matrix
                        except Exception:
                            parent_world_mat = None
                    if parent_world_mat is None and hasattr(original_parent, 'matrix_world'):
                        parent_world_mat = original_parent.matrix_world
                    if parent_world_mat is not None:
                        final_obj.matrix_parent_inverse = parent_world_mat.inverted() @ child_world_before_parent
                        final_obj.matrix_world = child_world_before_parent
            
            # Restore shade smooth state if editing, otherwise apply smooth shading by default
            original_smooth = getattr(self, '_original_shade_smooth', None)
            if original_smooth is not None:
                for poly in final_obj.data.polygons:
                    poly.use_smooth = original_smooth
            else:
                for poly in final_obj.data.polygons:
                    poly.use_smooth = True
            
            # Place the object origin at the first control point while preserving world position
            first_point_local = state.points_3d[0].copy() if state.points_3d else None
            if first_point_local is not None:
                # Shift mesh data so the first point sits at the local origin
                final_obj.data.transform(Matrix.Translation(-first_point_local))
                final_obj.data.update()
                # Compensate by moving the object transform so world-space geometry is unchanged
                final_obj.matrix_world = final_obj.matrix_world @ Matrix.Translation(first_point_local)
            
            # Store curve data in the object for later editing
            # Store points relative to metadata_origin (first point)
            metadata_origin = first_point_local if first_point_local is not None else Vector((0.0, 0.0, 0.0))
            original_points_data = []
            for point in state.points_3d:
                offset_point = point - metadata_origin
                original_points_data.append({
                    "x": offset_point.x,
                    "y": offset_point.y,
                    "z": offset_point.z
                })
            
            curve_data = {
                "curve_points": original_points_data,
                "radii": list(state.point_radii_3d),
                "tensions": list(state.point_tensions),
                "no_tangent_points": list(state.no_tangent_points),
                "resolution": self.resolution,
                "segments": self.segments,
                "start_cap_type": state.start_cap_type,
                "end_cap_type": state.end_cap_type,
                "profile_aspect_ratio": state.profile_aspect_ratio,
                "profile_global_twist": state.profile_global_twist,
                "profile_point_twists": list(state.profile_point_twists),
                "profile_global_type": state.profile_global_type,
                "profile_roundness": state.profile_roundness,
                "profile_point_roundness": list(state.profile_point_roundness),
                "custom_profile_points": list(state.custom_profile_points),
                "adaptive_segmentation": state.adaptive_segmentation,
                "bspline_mode": state.bspline_mode,
                "in_object_space": True,
                "metadata_origin": {"x": metadata_origin.x, "y": metadata_origin.y, "z": metadata_origin.z}
            }
            final_obj["flex_curve_data"] = json.dumps(curve_data)
            
            # Reparent original children to the new final object
            original_children = getattr(self, '_original_children', [])
            for child_data in original_children:
                child = bpy.data.objects.get(child_data['name'])
                if child:
                    bpy.ops.object.select_all(action='DESELECT')
                    child.select_set(True)
                    final_obj.select_set(True)
                    context.view_layer.objects.active = final_obj
                    bpy.ops.object.parent_set(type='OBJECT', keep_transform=False)
        
        if do_cleanup:
            self._cleanup(context)


classes = (
    MESH_OT_flex_create,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
