"""
Conversion utilities for the Flex tool in Super Tools addon.
Handles conversions between 2D and 3D coordinates, screen space and world space.
"""
import bpy
import math
from mathutils import Vector
from bpy_extras import view3d_utils
from .flex_state import state


def get_3d_from_mouse(context, mouse_pos, depth=None, use_special_depth_logic=False, require_face_hit=False):
    """Convert a 2D mouse position to a 3D point in object space.
    
    Args:
        context: Blender context
        mouse_pos: 2D mouse position (x, y)
        depth: Optional Z-depth value to use. If not provided, will use a raycast
               to find the depth or fall back to a default value
        use_special_depth_logic: If True, use special logic for the first point in a new curve
        require_face_hit: If True and face projection is enabled, return None when no
                          raycast hit is found instead of falling back to current depth.
               
    Returns:
        Vector: 3D point in object space
    """
    region = context.region
    rv3d = context.region_data
    
    view_vector = view3d_utils.region_2d_to_vector_3d(region, rv3d, mouse_pos)
    ray_origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, mouse_pos)
    
    if depth is not None:
        world_point = ray_origin + view_vector * depth
        
        if state.object_matrix_world is not None:
            matrix_world_inv = state.object_matrix_world.inverted()
            point_3d = matrix_world_inv @ world_point
        else:
            point_3d = world_point
            
        return point_3d
    
    if use_special_depth_logic:
        if state.construction_plane_origin is not None and state.construction_plane_normal is not None:
            denom = view_vector.dot(state.construction_plane_normal)
            if abs(denom) > 1e-6:
                t = (state.construction_plane_origin - ray_origin).dot(state.construction_plane_normal) / denom
                if t > 0.0:
                    point_3d = ray_origin + view_vector * t
                    state.current_depth = (point_3d - ray_origin).length
                    return point_3d
        
        if context.active_object and context.active_object.type == 'MESH':
            if (state.preview_mesh_obj is None or context.active_object != state.preview_mesh_obj) and (
                getattr(state, 'edited_object_name', None) is None or context.active_object.name != state.edited_object_name
            ):
                matrix = context.active_object.matrix_world.inverted()
                ray_origin_obj = matrix @ ray_origin
                ray_direction_obj = matrix.to_3x3() @ view_vector
                
                success, location, normal, index = context.active_object.ray_cast(ray_origin_obj, ray_direction_obj)
                
                if success:
                    hit_point = context.active_object.matrix_world @ location
                    return hit_point
                else:
                    obj_center = context.active_object.matrix_world.translation
                    depth_value = (obj_center - ray_origin).dot(view_vector)
                    point_3d = ray_origin + view_vector * depth_value
                    return point_3d
        
        view_abs = [abs(view_vector.x), abs(view_vector.y), abs(view_vector.z)]
        max_index = view_abs.index(max(view_abs))
        
        if max_index == 0:
            if abs(view_vector.x) > 0.0001:
                t = -ray_origin.x / view_vector.x
                point_3d = ray_origin + view_vector * t
            else:
                point_3d = ray_origin + view_vector * 10.0
        elif max_index == 1:
            if abs(view_vector.y) > 0.0001:
                t = -ray_origin.y / view_vector.y
                point_3d = ray_origin + view_vector * t
            else:
                point_3d = ray_origin + view_vector * 10.0
        else:
            if abs(view_vector.z) > 0.0001:
                t = -ray_origin.z / view_vector.z
                point_3d = ray_origin + view_vector * t
            else:
                point_3d = ray_origin + view_vector * 10.0
        
        state.current_depth = (point_3d - ray_origin).length
        return point_3d
    
    if state.face_projection_enabled:
        hit_obj = None
        hit_point = None
        hit_dist = float('inf')
        
        for obj in context.visible_objects:
            if obj.type == 'MESH':
                if (state.preview_mesh_obj is not None and obj == state.preview_mesh_obj) or (
                    getattr(state, 'edited_object_name', None) is not None and obj.name == state.edited_object_name
                ):
                    continue
                
                matrix = obj.matrix_world.inverted()
                ray_origin_obj = matrix @ ray_origin
                ray_direction_obj = matrix.to_3x3() @ view_vector
                
                success, location, normal, index = obj.ray_cast(ray_origin_obj, ray_direction_obj)
                
                if success:
                    world_hit = obj.matrix_world @ location
                    dist = (world_hit - ray_origin).length
                    
                    if dist < hit_dist:
                        hit_dist = dist
                        hit_point = world_hit
                        hit_obj = obj
        
        if hit_point is not None:
            if state.object_matrix_world is not None:
                matrix_world_inv = state.object_matrix_world.inverted()
                return matrix_world_inv @ hit_point
            else:
                return hit_point
        elif require_face_hit:
            return None
    
    world_point = ray_origin + view_vector * state.current_depth
    
    if state.object_matrix_world is not None:
        matrix_world_inv = state.object_matrix_world.inverted()
        return matrix_world_inv @ world_point
    else:
        return world_point


def get_2d_from_3d(context, point_3d, *, is_world_space=False):
    """Convert a 3D point to 2D screen coordinates.

    Args:
        context: Blender context (optional, falls back to bpy.context)
        point_3d: Point in object or world space
        is_world_space: Treat point_3d as world-space when True
    """
    try:
        region = getattr(context, "region", None) if context else None
        rv3d = getattr(context, "region_data", None) if context else None
    except ReferenceError:
        region = None
        rv3d = None

    if region is None or rv3d is None:
        region = bpy.context.region
        rv3d = bpy.context.region_data

    if region is None or rv3d is None:
        return None

    try:
        world_point = point_3d if isinstance(point_3d, Vector) else Vector(point_3d)
        if not is_world_space and state.object_matrix_world is not None:
            world_point = state.object_matrix_world @ world_point
        return view3d_utils.location_3d_to_region_2d(region, rv3d, world_point)
    except Exception:
        return None


def get_screen_distance(context, world_distance, point_3d):
    """Convert a world space distance to screen space distance.
    
    Args:
        context: Blender context
        world_distance: Distance in world units
        point_3d: 3D reference point for the conversion
        
    Returns:
        float: Distance in screen space (pixels)
    """
    point_2d = get_2d_from_3d(context, point_3d)
    if point_2d is None:
        return 0.0
    
    offset_point = point_3d.copy()
    offset_point.x += world_distance
    
    offset_2d = get_2d_from_3d(context, offset_point)
    if offset_2d is None:
        return 0.0
    
    return math.sqrt((offset_2d[0] - point_2d[0])**2 + (offset_2d[1] - point_2d[1])**2)


def get_consistent_screen_radius(context, radius_3d, point_3d, tangent=None):
    """
    Convert a 3D radius to screen space, aligned with the cross-section of the tube mesh.
    
    Args:
        context: Blender context
        radius_3d: Radius in world units
        point_3d: 3D reference point in object space
        tangent: Optional tangent vector at the point (Vector)
        
    Returns:
        float: Radius in screen space (pixels) that matches the tube cross-section
    """
    try:
        region = getattr(context, "region", None) if context else None
        rv3d = getattr(context, "region_data", None) if context else None
        if region is None or rv3d is None:
            region = bpy.context.region
            rv3d = bpy.context.region_data
        if region is None or rv3d is None:
            return 30.0

        world_point = point_3d.copy() if isinstance(point_3d, Vector) else Vector(point_3d)
        if state.object_matrix_world is not None:
            world_point = state.object_matrix_world @ world_point

        point_2d = view3d_utils.location_3d_to_region_2d(region, rv3d, world_point)
        if point_2d is None:
            return 30.0
        
        view_vector = rv3d.view_rotation @ Vector((0.0, 0.0, -1.0))
        
        if tangent is None:
            tangent = Vector((1, 0, 0))
        
        side = tangent.cross(view_vector)
        if side.length < 1e-6:
            side = Vector((0, 1, 0))
        side.normalize()
        
        offset_point = world_point + side * radius_3d
        offset_2d = view3d_utils.location_3d_to_region_2d(region, rv3d, offset_point)
        if offset_2d is None:
            return 30.0
        
        screen_radius = (offset_2d - point_2d).length
        return max(screen_radius, 10.0)
    except Exception:
        return 30.0


def get_world_distance(context, screen_distance, point_3d):
    """Convert a screen space distance to world space distance.
    
    Args:
        context: Blender context
        screen_distance: Distance in screen space (pixels)
        point_3d: 3D reference point in object space
        
    Returns:
        float: Distance in world units
    """
    region = context.region
    rv3d = context.region_data
    
    world_point = point_3d
    if state.object_matrix_world is not None:
        world_point = state.object_matrix_world @ point_3d
    
    point_2d = view3d_utils.location_3d_to_region_2d(region, rv3d, world_point)
    if point_2d is None:
        return 0.0
    
    if rv3d.is_perspective:
        view_vector = view3d_utils.region_2d_to_vector_3d(region, rv3d, point_2d)
        ray_origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, point_2d)
        
        distance = (world_point - ray_origin).length
        
        if hasattr(rv3d, 'lens'):
            lens = rv3d.lens
        else:
            lens = context.space_data.lens
        
        fov_rad = 2 * math.atan(16.0 / lens)
        world_distance = (screen_distance * distance * math.tan(fov_rad / 2)) / (region.width / 2)
        
        return world_distance
    else:
        world_distance = screen_distance * (rv3d.view_distance * 2) / region.width
        return world_distance


def register():
    pass


def unregister():
    pass
