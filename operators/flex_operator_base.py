"""
Base Flex Operator for Super Tools addon.
This module contains the shared functionality for Flex curve-based operators.
"""
import bpy
import blf
import gpu
from gpu_extras.batch import batch_for_shader
import math
import time
from bpy_extras import view3d_utils
from mathutils import Vector, Matrix

from ..utils.flex_state import state
from ..utils import flex_conversion as conversion
from ..utils import flex_math as math_utils
from ..utils import flex_mesh as mesh_utils


class FlexOperatorBase(bpy.types.Operator):
    """Base class for Flex curve-based operators with shared functionality"""
    
    resolution: bpy.props.IntProperty(
        name="Circumference Resolution",
        description="Resolution of the flex mesh (number of vertices around circumference)",
        default=16,
        min=4,
        max=64
    )
    segments: bpy.props.IntProperty(
        name="Length Segments",
        description="Number of segments along the length of the curve",
        default=32,
        min=8,
        max=128
    )
    
    @classmethod
    def poll(cls, context):
        """Check if the operator can be called."""
        area = getattr(context, "area", None)
        if not area or area.type != 'VIEW_3D':
            return False
        mode = getattr(context, "mode", None)
        if mode in {"OBJECT", "SCULPT"}:
            return True
        return False
    
    def is_mouse_in_region(self, context, event):
        """Check if the mouse is inside the 3D view region"""
        return (0 <= event.mouse_region_x <= context.region.width and
                0 <= event.mouse_region_y <= context.region.height)
    
    def check_camera_movement(self, context):
        """Check if the camera has moved and update the current_depth if needed"""
        current_matrix = context.region_data.view_matrix.copy()
        if hasattr(self, '_camera_matrix') and self._camera_matrix != current_matrix:
            if state.points_3d:
                last_point = state.points_3d[-1]
                if state.object_matrix_world:
                    world_point = state.object_matrix_world @ last_point
                else:
                    world_point = last_point
                
                view_location = context.region_data.view_location
                state.current_depth = (world_point - view_location).length

            if getattr(state, 'face_drag_ref_world', None) is not None and state.active_point_index >= 0:
                rv3d = context.region_data
                if rv3d:
                    if rv3d.view_perspective != 'ORTHO':
                        cam_loc = rv3d.view_matrix.inverted().translation
                        state.face_drag_depth_t = (state.face_drag_ref_world - cam_loc).length
                        state.face_drag_is_ortho = False
                        state.face_drag_view_normal = None
                    else:
                        state.face_drag_is_ortho = True
                        state.face_drag_view_normal = (rv3d.view_rotation @ Vector((0.0, 0.0, -1.0))).normalized()
                        state.face_drag_depth_t = None
            
            self._camera_matrix = current_matrix
            return True
        elif not hasattr(self, '_camera_matrix'):
            self._camera_matrix = current_matrix
            
        return False
    
    def modal(self, context, event):
        """Handle modal events - to be implemented by subclasses"""
        if not self.is_mouse_in_region(context, event):
            return {'PASS_THROUGH'}
        
        self.check_camera_movement(context)
        
        # Subclasses should override this to handle specific events
        return {'RUNNING_MODAL'}
    
    def _get_new_point_3d(self, context, mouse_pos):
        """Get a new 3D point from mouse position using various projection methods.
        
        This method tries multiple projection techniques in order of preference:
        1. Face projection (if enabled and face is found)
        2. Construction plane projection (if enabled)
        3. Connecting-end depth (when camera moved or face mode with no hit)
        4. Fallback to nearest point depth
        """
        region = context.region
        rv3d = context.region_data
        
        if not rv3d:
            return None
        
        new_point_3d = None

        # First point: use special depth logic
        if len(state.points_3d) == 0:
            first_point = conversion.get_3d_from_mouse(context, mouse_pos, use_special_depth_logic=True)
            if first_point is not None:
                return first_point
        
        # 1. Try Face Projection if enabled (snapping mode = FACE)
        if state.snapping_mode == state.SNAPPING_FACE:
            attempted_point = conversion.get_3d_from_mouse(context, mouse_pos, require_face_hit=True)
            if attempted_point:
                new_point_3d = attempted_point

        # Detect camera movement
        camera_moved = False
        try:
            if state.last_camera_matrix is not None and rv3d and rv3d.view_matrix:
                camera_moved = any(abs(a - b) > 1e-10 for a, b in zip(state.last_camera_matrix, rv3d.view_matrix))
        except Exception:
            camera_moved = False
        
        # Fallback detection: compare current view direction to stored construction plane normal
        if not camera_moved and rv3d is not None:
            try:
                current_view_dir = (rv3d.view_matrix.inverted().to_3x3() @ Vector((0, 0, -1))).normalized()
                if state.construction_plane_normal is not None:
                    dot_val = max(-1.0, min(1.0, current_view_dir.dot(state.construction_plane_normal)))
                    if dot_val < 0.9999:
                        camera_moved = True
            except Exception:
                pass

        # Use connecting-end depth when camera moved or face mode with no hit
        if new_point_3d is None and len(state.points_3d) > 0 and (camera_moved or state.snapping_mode == state.SNAPPING_FACE):
            world_ray_origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, mouse_pos)
            world_ray_direction = view3d_utils.region_2d_to_vector_3d(region, rv3d, mouse_pos).normalized()

            # Get start and end in world space
            start_world = state.points_3d[0]
            end_world = state.points_3d[-1]
            if state.object_matrix_world:
                start_world = state.object_matrix_world @ start_world
                end_world = state.object_matrix_world @ end_world

            start_2d = conversion.get_2d_from_3d(context, start_world, is_world_space=True)
            end_2d = conversion.get_2d_from_3d(context, end_world, is_world_space=True)

            mouse_vec_2d = Vector((mouse_pos[0], mouse_pos[1]))
            connecting_world = None
            if start_2d and end_2d:
                dist_start = (mouse_vec_2d - Vector(start_2d)).length
                dist_end = (mouse_vec_2d - Vector(end_2d)).length
                connecting_world = start_world if dist_start < dist_end else end_world
            elif start_2d:
                connecting_world = start_world
            elif end_2d:
                connecting_world = end_world

            if rv3d.view_perspective != 'ORTHO':
                depth_to_use = state.current_depth
                if connecting_world is not None:
                    # Use dot product for correct depth along view ray
                    depth_to_use = (connecting_world - world_ray_origin).dot(world_ray_direction)
                
                candidate = conversion.get_3d_from_mouse(context, mouse_pos, depth=depth_to_use)
                if candidate is not None:
                    new_point_3d = candidate
                    # Re-anchor construction plane if camera moved
                    if camera_moved:
                        try:
                            view_dir = (rv3d.view_matrix.inverted().to_3x3() @ Vector((0, 0, -1))).normalized()
                            state.construction_plane_normal = view_dir
                            state.construction_plane_origin = world_ray_origin + view_dir * depth_to_use
                            state.current_depth = depth_to_use
                        except Exception:
                            pass
            else:
                # Orthographic: intersect with view-plane through connecting end
                view_inv_local = rv3d.view_matrix.inverted()
                view_normal = (view_inv_local.to_3x3() @ Vector((0.0, 0.0, -1.0))).normalized()
                denom = world_ray_direction.dot(view_normal)
                if abs(denom) < 1e-6:
                    denom = 1e-6 if denom >= 0 else -1e-6
                anchor = connecting_world if connecting_world is not None else (state.construction_plane_origin or view_inv_local.translation)
                t = (anchor - world_ray_origin).dot(view_normal) / denom
                t = max(t, 0.001)
                world_point = world_ray_origin + world_ray_direction * t
                if state.object_matrix_world:
                    new_point_3d = state.object_matrix_world.inverted() @ world_point
                else:
                    new_point_3d = world_point
                # Re-anchor plane if camera moved
                if camera_moved:
                    try:
                        view_dir = (rv3d.view_matrix.inverted().to_3x3() @ Vector((0, 0, -1))).normalized()
                        state.construction_plane_normal = view_dir
                        state.construction_plane_origin = anchor
                    except Exception:
                        pass

        # 2. Construction plane projection (when not in FACE mode)
        if new_point_3d is None and state.snapping_mode != state.SNAPPING_FACE:
            if state.construction_plane_normal is not None and state.current_depth is not None:
                world_ray_origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, mouse_pos)
                world_ray_direction = view3d_utils.region_2d_to_vector_3d(region, rv3d, mouse_pos).normalized()

                view_inv = rv3d.view_matrix.inverted()
                plane_normal = (view_inv.to_3x3() @ Vector((0, 0, -1))).normalized()
                
                # Use the connecting endpoint directly as plane origin for true plane intersection
                # This avoids depth drift that occurs when calculating depth per-ray
                plane_origin = state.construction_plane_origin
                if len(state.points_3d) > 0:
                    start_world = state.points_3d[0]
                    end_world = state.points_3d[-1]
                    if state.object_matrix_world:
                        start_world = state.object_matrix_world @ start_world
                        end_world = state.object_matrix_world @ end_world
                    
                    start_2d = conversion.get_2d_from_3d(context, start_world, is_world_space=True)
                    end_2d = conversion.get_2d_from_3d(context, end_world, is_world_space=True)
                    
                    mouse_vec_2d = Vector((mouse_pos[0], mouse_pos[1]))
                    if start_2d and end_2d:
                        dist_start = (mouse_vec_2d - Vector(start_2d)).length
                        dist_end = (mouse_vec_2d - Vector(end_2d)).length
                        plane_origin = start_world if dist_start < dist_end else end_world
                    elif start_2d:
                        plane_origin = start_world
                    elif end_2d:
                        plane_origin = end_world
                
                # Fallback if plane_origin is still None
                if plane_origin is None:
                    if rv3d.view_perspective != 'ORTHO':
                        cam_loc = view_inv.translation
                        plane_origin = cam_loc + plane_normal * state.current_depth
                    else:
                        plane_origin = view_inv.translation

                denom = world_ray_direction.dot(plane_normal)
                if abs(denom) > 1e-6:
                    t = (plane_origin - world_ray_origin).dot(plane_normal) / denom
                    if t > 0:
                        world_intersection_point = world_ray_origin + t * world_ray_direction
                        
                        if state.object_matrix_world:
                            new_point_3d = state.object_matrix_world.inverted() @ world_intersection_point
                        else:
                            new_point_3d = world_intersection_point
                        
                        # Keep plane normal in sync
                        try:
                            state.construction_plane_normal = plane_normal
                        except Exception:
                            pass

        # Update last_camera_matrix after computing the placement
        try:
            if rv3d and rv3d.view_matrix:
                state.last_camera_matrix = rv3d.view_matrix.copy()
        except Exception:
            pass

        # 3. Fallback to depth-based projection using connecting-end depth
        if new_point_3d is None:
            depth_to_use = state.current_depth
            used_connecting_end = False
            
            if len(state.points_3d) > 0:
                world_ray_origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, mouse_pos)
                world_ray_direction = view3d_utils.region_2d_to_vector_3d(region, rv3d, mouse_pos).normalized()

                start_world = state.points_3d[0]
                end_world = state.points_3d[-1]
                if state.object_matrix_world:
                    start_world = state.object_matrix_world @ start_world
                    end_world = state.object_matrix_world @ end_world

                start_2d = conversion.get_2d_from_3d(context, start_world, is_world_space=True)
                end_2d = conversion.get_2d_from_3d(context, end_world, is_world_space=True)

                mouse_vec_2d = Vector((mouse_pos[0], mouse_pos[1]))
                connecting_world = None
                if start_2d and end_2d:
                    dist_start = (mouse_vec_2d - Vector(start_2d)).length
                    dist_end = (mouse_vec_2d - Vector(end_2d)).length
                    connecting_world = start_world if dist_start < dist_end else end_world
                elif start_2d:
                    connecting_world = start_world
                elif end_2d:
                    connecting_world = end_world

                if connecting_world is not None:
                    depth_to_use = (connecting_world - world_ray_origin).dot(world_ray_direction)
                    used_connecting_end = True

            # Secondary fallback: nearest point depth
            if not used_connecting_end and len(state.points_3d) > 0:
                nearest_point_world = None
                min_distance_2d = float('inf')
                mouse_vec_2d = Vector((mouse_pos[0], mouse_pos[1]))
                for point_3d in state.points_3d:
                    pw = state.object_matrix_world @ point_3d if state.object_matrix_world else point_3d
                    p2d = conversion.get_2d_from_3d(context, pw)
                    if p2d:
                        d2d = (mouse_vec_2d - Vector(p2d)).length
                        if d2d < min_distance_2d:
                            min_distance_2d = d2d
                            nearest_point_world = pw
                if nearest_point_world is not None:
                    camera_location = rv3d.view_matrix.inverted().translation
                    depth_to_use = (nearest_point_world - camera_location).length

            new_point_3d = conversion.get_3d_from_mouse(context, mouse_pos, depth=depth_to_use)
        
        return new_point_3d
    
    def _add_first_point(self, new_point_3d):
        """Add the first point to start a new curve."""
        state.points_3d.append(new_point_3d)
        state.point_radii_3d.append(state.DEFAULT_RADIUS)
        state.point_tensions.append(0.5)
        if hasattr(state, 'profile_point_twists'):
            state.profile_point_twists.append(0.0)
        if hasattr(state, 'profile_point_roundness'):
            state.profile_point_roundness.append(state.profile_roundness)
        state.creating_point_index = 0
        state.creating_point_start_pos = new_point_3d.copy() if hasattr(new_point_3d, 'copy') else new_point_3d
    
    def _add_point_to_closest_end(self, context, mouse_pos, new_point_3d=None):
        """Add a point to whichever end of the curve is closest to the mouse."""
        # Get the new point if not provided
        new_point = new_point_3d if new_point_3d is not None else self._get_new_point_3d(context, mouse_pos)
        if not new_point:
            return
        
        if len(state.points_3d) == 0:
            state.points_3d.append(new_point)
            state.point_radii_3d.append(state.DEFAULT_RADIUS)
            state.point_tensions.append(0.5)
            if hasattr(state, 'profile_point_twists'):
                state.profile_point_twists.append(0.0)
            if hasattr(state, 'profile_point_roundness'):
                state.profile_point_roundness.append(state.profile_roundness)
            state.creating_point_index = 0
            state.creating_point_start_pos = new_point.copy() if hasattr(new_point, 'copy') else new_point
            return
        
        start_point = state.points_3d[0]
        end_point = state.points_3d[-1]
        
        start_2d = conversion.get_2d_from_3d(context, start_point)
        end_2d = conversion.get_2d_from_3d(context, end_point)
        
        # Default to append if projection fails
        add_to_start = False
        if start_2d is not None and end_2d is not None:
            dist_to_start = math.sqrt((mouse_pos[0] - start_2d[0])**2 + (mouse_pos[1] - start_2d[1])**2)
            dist_to_end = math.sqrt((mouse_pos[0] - end_2d[0])**2 + (mouse_pos[1] - end_2d[1])**2)
            add_to_start = dist_to_start < dist_to_end
        
        if add_to_start:
            state.points_3d.insert(0, new_point)
            state.point_radii_3d.insert(0, state.point_radii_3d[0] if state.point_radii_3d else state.DEFAULT_RADIUS)
            state.point_tensions.insert(0, 0.5)
            if hasattr(state, 'profile_point_twists'):
                state.profile_point_twists.insert(0, 0.0)
            if hasattr(state, 'profile_point_roundness'):
                state.profile_point_roundness.insert(0, state.profile_roundness)
            state.no_tangent_points = {i + 1 for i in state.no_tangent_points}
            state.creating_point_index = 0
        else:
            state.points_3d.append(new_point)
            state.point_radii_3d.append(state.point_radii_3d[-1] if state.point_radii_3d else state.DEFAULT_RADIUS)
            state.point_tensions.append(0.5)
            if hasattr(state, 'profile_point_twists'):
                state.profile_point_twists.append(0.0)
            if hasattr(state, 'profile_point_roundness'):
                state.profile_point_roundness.append(state.profile_roundness)
            state.creating_point_index = len(state.points_3d) - 1
        
        state.creating_point_start_pos = new_point.copy() if hasattr(new_point, 'copy') else new_point


def register():
    # FlexOperatorBase is a base class - do not register it directly
    pass


def unregister():
    # FlexOperatorBase is a base class - do not unregister it directly
    pass
