import bpy
from mathutils import Vector
from typing import Optional


def is_view_nav_event(event) -> bool:
    # Middle mouse and mouse wheel zoom
    if event.type in {'MIDDLEMOUSE', 'WHEELUPMOUSE', 'WHEELDOWNMOUSE', 'WHEELINMOUSE', 'WHEELOUTMOUSE'}:
        return True
    # Trackpad navigation
    if event.type in {'TRACKPADPAN', 'TRACKPADZOOM'}:
        return True
    # 3D mouse (NDOF)
    if event.type in {
        'NDOF_MOTION',
        'NDOF_BUTTON_MENU', 'NDOF_BUTTON_FIT',
        'NDOF_BUTTON_TOP', 'NDOF_BUTTON_BOTTOM', 'NDOF_BUTTON_LEFT', 'NDOF_BUTTON_RIGHT',
        'NDOF_BUTTON_FRONT', 'NDOF_BUTTON_BACK',
        'NDOF_BUTTON_ISO1', 'NDOF_BUTTON_ISO2'
    }:
        return True
    # Industry Compatible: Alt + mouse
    if event.alt and event.type in {'LEFTMOUSE', 'MIDDLEMOUSE', 'RIGHTMOUSE'}:
        return True
    return False


def raycast_object_under_mouse(context, event, target_obj: bpy.types.Object) -> Optional[Vector]:
    region = context.region
    space = context.space_data
    rv3d = space.region_3d if space and space.type == 'VIEW_3D' else None
    if region is None or rv3d is None:
        return None

    from bpy_extras import view3d_utils
    mouse_coord = (event.mouse_region_x, event.mouse_region_y)

    view_vector = view3d_utils.region_2d_to_vector_3d(region, rv3d, mouse_coord)
    ray_origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, mouse_coord)

    depsgraph = context.evaluated_depsgraph_get()
    target_eval = target_obj.evaluated_get(depsgraph)
    matrix = target_eval.matrix_world
    matrix_inv = matrix.inverted()

    # Transform to local space of target
    ray_origin_local = matrix_inv @ ray_origin
    ray_dir_local = (matrix_inv.to_3x3() @ view_vector).normalized()

    success, location, normal, face_index = target_eval.ray_cast(ray_origin_local, ray_dir_local)
    if success:
        return matrix @ location
    return None
