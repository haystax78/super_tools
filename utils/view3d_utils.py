import bpy
import mathutils
import bmesh
from mathutils import Vector


def mouse_delta_to_plane_delta(region, rv3d, mouse_prev, mouse_cur, plane_point, plane_normal):
    """Convert mouse delta to 3D translation on a plane"""
    # Handle edge cases
    if not region or not rv3d:
        return Vector((0, 0, 0))
    
    # Convert mouse positions to 3D rays
    try:
        ray_prev = region_2d_to_vector_3d(region, rv3d, mouse_prev)
        ray_cur = region_2d_to_vector_3d(region, rv3d, mouse_cur)
    except:
        return Vector((0, 0, 0))
    
    # Convert region coordinates to 3D locations
    try:
        origin_prev = region_2d_to_location_3d(region, rv3d, mouse_prev, plane_point)
        origin_cur = region_2d_to_location_3d(region, rv3d, mouse_cur, plane_point)
    except:
        return Vector((0, 0, 0))
    
    # Handle zero-length normal
    if plane_normal.length == 0:
        return Vector((0, 0, 0))
    
    # Calculate intersection points on the plane
    try:
        prev_point = mathutils.geometry.intersect_line_plane(
            origin_prev, origin_prev + ray_prev, plane_point, plane_normal
        )
        
        cur_point = mathutils.geometry.intersect_line_plane(
            origin_cur, origin_cur + ray_cur, plane_point, plane_normal
        )
    except:
        return Vector((0, 0, 0))
    
    # Return the difference
    if prev_point is not None and cur_point is not None:
        return cur_point - prev_point
    else:
        return Vector((0, 0, 0))


def region_2d_to_vector_3d(region, rv3d, coord):
    """Convert region 2D coordinates to 3D vector"""
    from bpy_extras.view3d_utils import region_2d_to_vector_3d
    return region_2d_to_vector_3d(region, rv3d, coord)


def region_2d_to_location_3d(region, rv3d, coord, depth_location):
    """Convert region 2D coordinates to 3D location"""
    from bpy_extras.view3d_utils import region_2d_to_location_3d
    return region_2d_to_location_3d(region, rv3d, coord, depth_location)
