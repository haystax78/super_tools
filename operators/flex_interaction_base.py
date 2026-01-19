"""
Base Flex Interaction Module for Super Tools addon.
This module contains the core modal handler and basic interactions.
"""
import bpy
import time
import math
import json
from mathutils import Vector, Matrix
from bpy_extras import view3d_utils

from ..utils.flex_state import state, save_custom_profiles_to_scene, load_custom_profiles_from_scene
from ..utils import flex_conversion as conversion
from ..utils import flex_math as math_utils
from ..utils import flex_mesh as mesh_utils
from . import flex_interaction_points


def find_closest_point(context, mouse_pos, points_3d, threshold=20):
    """Find the closest point to the mouse position"""
    return math_utils.find_closest_point(context, mouse_pos, points_3d, threshold)


def find_radius_circle_hit(context, mouse_pos, points_3d, radii_3d, threshold=10):
    """Find if the mouse is near any radius circle"""
    return math_utils.find_radius_circle_hover(context, mouse_pos, points_3d, radii_3d, threshold)


def find_tension_control_hover(context, mouse_pos, points_3d, radii_3d, tensions, threshold=12):
    """Find if the mouse is hovering near any tension control dot"""
    return math_utils.find_tension_control_hover(context, mouse_pos, points_3d, radii_3d, tensions, threshold)


def find_closest_point_on_curve(context, mouse_pos, curve_points_3d, threshold=15):
    """Find the closest point on the curve to the mouse position"""
    return math_utils.find_closest_point_on_curve(context, mouse_pos, curve_points_3d, threshold)


def _find_closest_custom_profile_point(mouse_pos, screen_points, threshold=15.0):
    """Find the closest custom profile screen point to the mouse position."""
    if not screen_points:
        return -1
    
    closest_idx = -1
    closest_dist = float('inf')
    
    for i, pt in enumerate(screen_points):
        dx = mouse_pos[0] - pt[0]
        dy = mouse_pos[1] - pt[1]
        dist = math.sqrt(dx * dx + dy * dy)
        if dist <= threshold and dist < closest_dist:
            closest_dist = dist
            closest_idx = i
    
    return closest_idx


def _find_closest_custom_profile_edge(mouse_pos, screen_points, threshold=10.0):
    """Find the closest edge to the mouse position."""
    if not screen_points or len(screen_points) < 2:
        return -1, None
    
    closest_edge = -1
    closest_dist = float('inf')
    closest_point = None
    
    n = len(screen_points)
    for i in range(n):
        p1 = screen_points[i]
        p2 = screen_points[(i + 1) % n]
        
        edge_x = p2[0] - p1[0]
        edge_y = p2[1] - p1[1]
        edge_len_sq = edge_x * edge_x + edge_y * edge_y
        
        if edge_len_sq < 1e-6:
            continue
        
        t = ((mouse_pos[0] - p1[0]) * edge_x + (mouse_pos[1] - p1[1]) * edge_y) / edge_len_sq
        t = max(0.0, min(1.0, t))
        
        cx = p1[0] + t * edge_x
        cy = p1[1] + t * edge_y
        
        dx = mouse_pos[0] - cx
        dy = mouse_pos[1] - cy
        dist = math.sqrt(dx * dx + dy * dy)
        
        if dist <= threshold and dist < closest_dist:
            closest_dist = dist
            closest_edge = i
            closest_point = (cx, cy)
    
    return closest_edge, closest_point


def _get_profile_center(screen_points):
    """Get the center of the profile points."""
    if screen_points and len(screen_points) >= 1:
        cx = sum(pt[0] for pt in screen_points) / len(screen_points)
        cy = sum(pt[1] for pt in screen_points) / len(screen_points)
        return (cx, cy)
    return None


def _mirror_point(point, center, angle):
    """Mirror a point across a line through center at given angle."""
    cx, cy = center
    # Translate to origin
    px, py = point[0] - cx, point[1] - cy
    # Rotate to align symmetry axis with Y-axis
    cos_a = math.cos(-angle)
    sin_a = math.sin(-angle)
    rx = px * cos_a - py * sin_a
    ry = px * sin_a + py * cos_a
    # Mirror across Y-axis (negate X)
    rx = -rx
    # Rotate back
    cos_a = math.cos(angle)
    sin_a = math.sin(angle)
    mx = rx * cos_a - ry * sin_a
    my = rx * sin_a + ry * cos_a
    # Translate back
    return (mx + cx, my + cy)


def _get_mirror_index(point_index):
    """Get the mirror index for a point from the pairs dict."""
    return state.custom_profile_point_pairs.get(point_index, -1)


def _set_point_pair(idx1, idx2):
    """Set two points as mirrors of each other."""
    state.custom_profile_point_pairs[idx1] = idx2
    state.custom_profile_point_pairs[idx2] = idx1


def _remove_point_from_pairs(idx):
    """Remove a point from the pairs dict and update indices."""
    # Find and remove the pair
    mirror_idx = state.custom_profile_point_pairs.pop(idx, -1)
    if mirror_idx >= 0 and mirror_idx in state.custom_profile_point_pairs:
        del state.custom_profile_point_pairs[mirror_idx]
    
    # Update indices for points after the removed one
    new_pairs = {}
    for k, v in state.custom_profile_point_pairs.items():
        new_k = k - 1 if k > idx else k
        new_v = v - 1 if v > idx else v
        new_pairs[new_k] = new_v
    state.custom_profile_point_pairs = new_pairs


def _insert_point_update_pairs(insert_idx):
    """Update pair indices after inserting a point."""
    new_pairs = {}
    for k, v in state.custom_profile_point_pairs.items():
        new_k = k + 1 if k >= insert_idx else k
        new_v = v + 1 if v >= insert_idx else v
        new_pairs[new_k] = new_v
    state.custom_profile_point_pairs = new_pairs


def _distance_to_symmetry_axis(point, center, angle):
    """Calculate perpendicular distance from point to symmetry axis."""
    cx, cy = center
    px, py = point[0] - cx, point[1] - cy
    # Rotate to align axis with Y
    cos_a = math.cos(-angle)
    sin_a = math.sin(-angle)
    rx = px * cos_a - py * sin_a
    return abs(rx)


def _is_point_on_right_side(point, center, angle):
    """Check if point is on the right side of the symmetry axis."""
    if center is None:
        return True
    cx, cy = center
    px, py = point[0] - cx, point[1] - cy
    # Rotate to align axis with Y
    cos_a = math.cos(-angle)
    sin_a = math.sin(-angle)
    rx = px * cos_a - py * sin_a
    return rx >= 0  # Right side is positive X after rotation


def _get_signed_distance_to_axis(point, center, angle):
    """Get signed distance from point to symmetry axis (positive = right side)."""
    if center is None:
        return 0
    cx, cy = center
    px, py = point[0] - cx, point[1] - cy
    cos_a = math.cos(-angle)
    sin_a = math.sin(-angle)
    rx = px * cos_a - py * sin_a
    return rx


def _project_point_to_axis(point, center, angle):
    """Project a point onto the symmetry axis."""
    if center is None:
        return point
    cx, cy = center
    px, py = point[0] - cx, point[1] - cy
    # Rotate to align axis with Y
    cos_a = math.cos(-angle)
    sin_a = math.sin(-angle)
    # rx = px * cos_a - py * sin_a  # Distance from axis (set to 0)
    ry = px * sin_a + py * cos_a  # Position along axis (keep this)
    # Rotate back with rx = 0
    cos_a = math.cos(angle)
    sin_a = math.sin(angle)
    new_x = -ry * sin_a  # rx=0, so just -ry*sin_a
    new_y = ry * cos_a   # rx=0, so just ry*cos_a
    return (new_x + cx, new_y + cy)


def _is_point_on_axis(point, center, angle, threshold=5.0):
    """Check if a point is on (or very close to) the symmetry axis."""
    dist = abs(_get_signed_distance_to_axis(point, center, angle))
    return dist < threshold


def _line_crosses_axis(p1, p2, center, angle):
    """Check if line segment from p1 to p2 crosses the symmetry axis."""
    d1 = _get_signed_distance_to_axis(p1, center, angle)
    d2 = _get_signed_distance_to_axis(p2, center, angle)
    # Crosses if signs are different (one positive, one negative)
    return d1 * d2 < 0


def _get_axis_crossing_point(p1, p2, center, angle):
    """Get the point where line segment p1-p2 crosses the symmetry axis."""
    d1 = _get_signed_distance_to_axis(p1, center, angle)
    d2 = _get_signed_distance_to_axis(p2, center, angle)
    
    if abs(d1 - d2) < 0.001:
        return None  # Parallel to axis or same point
    
    # Linear interpolation to find crossing point
    t = d1 / (d1 - d2)
    crossing_x = p1[0] + t * (p2[0] - p1[0])
    crossing_y = p1[1] + t * (p2[1] - p1[1])
    
    # Snap to axis to ensure it's exactly on it
    return _project_point_to_axis((crossing_x, crossing_y), center, angle)


def _extract_right_side_with_crossings(screen_points, center, angle):
    """Extract right-side points from a profile and add crossing points on the axis.
    
    This is used when enabling symmetry on an existing profile.
    It finds all points on the right side, and where the profile crosses
    the symmetry axis, it generates a point on the axis.
    """
    if len(screen_points) < 2:
        return list(screen_points)
    
    result = []
    n = len(screen_points)
    
    for i in range(n):
        curr_pt = screen_points[i]
        next_pt = screen_points[(i + 1) % n]
        
        curr_on_right = _is_point_on_right_side(curr_pt, center, angle)
        next_on_right = _is_point_on_right_side(next_pt, center, angle)
        curr_on_axis = _is_point_on_axis(curr_pt, center, angle)
        
        # Add current point if it's on right side or on axis
        if curr_on_right or curr_on_axis:
            # If on axis, snap it to exact axis position
            if curr_on_axis:
                result.append(_project_point_to_axis(curr_pt, center, angle))
            else:
                result.append(curr_pt)
        
        # Check if edge crosses the axis (going from right to left or left to right)
        if _line_crosses_axis(curr_pt, next_pt, center, angle):
            crossing = _get_axis_crossing_point(curr_pt, next_pt, center, angle)
            if crossing:
                # Only add crossing if it's not too close to an existing point
                should_add = True
                if result:
                    last_pt = result[-1]
                    dist = math.sqrt((crossing[0] - last_pt[0])**2 + (crossing[1] - last_pt[1])**2)
                    if dist < 10:
                        should_add = False
                if should_add:
                    result.append(crossing)
    
    # Remove duplicate consecutive points
    if len(result) > 1:
        cleaned = [result[0]]
        for pt in result[1:]:
            last = cleaned[-1]
            dist = math.sqrt((pt[0] - last[0])**2 + (pt[1] - last[1])**2)
            if dist >= 5:
                cleaned.append(pt)
        result = cleaned
    
    return result


def _generate_symmetric_profile(right_side_points, center, angle):
    """Generate full symmetric profile from right-side points only.
    
    Points on the axis (center points) are not mirrored.
    The profile connects: mirror_last -> ... -> mirror_first -> first -> ... -> last
    With center points at the crossings if first/last are not on the axis.
    """
    if len(right_side_points) < 1:
        return []
    
    if len(right_side_points) == 1:
        pt = right_side_points[0]
        if _is_point_on_axis(pt, center, angle):
            return [pt]  # Single center point, no mirror
        mirror = _mirror_point(pt, center, angle)
        return [pt, mirror]
    
    # Separate center points (on axis) from right-side points
    center_point_indices = set()
    for i, pt in enumerate(right_side_points):
        if _is_point_on_axis(pt, center, angle):
            center_point_indices.add(i)
    
    # Build the full profile
    # Structure: [mirrored points in reverse] + [original points]
    # But center points (on axis) should not be mirrored
    
    result = []
    
    # First, add mirrored points in reverse order (skip center points)
    for i in range(len(right_side_points) - 1, -1, -1):
        if i not in center_point_indices:
            result.append(_mirror_point(right_side_points[i], center, angle))
    
    # Then add original points in forward order
    for i, pt in enumerate(right_side_points):
        result.append(pt)
    
    return result


def _find_mirror_edge(screen_points, edge_idx, center, angle):
    """Find the edge on the mirror side corresponding to the given edge."""
    if edge_idx < 0 or edge_idx >= len(screen_points):
        return -1
    
    # Get midpoint of the edge
    p1 = screen_points[edge_idx]
    p2 = screen_points[(edge_idx + 1) % len(screen_points)]
    mid = ((p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2)
    
    # Mirror the midpoint
    mirrored_mid = _mirror_point(mid, center, angle)
    
    # Find edge closest to mirrored midpoint
    best_edge = -1
    best_dist = float('inf')
    
    for i in range(len(screen_points)):
        if i == edge_idx:
            continue
        ep1 = screen_points[i]
        ep2 = screen_points[(i + 1) % len(screen_points)]
        edge_mid = ((ep1[0] + ep2[0]) / 2, (ep1[1] + ep2[1]) / 2)
        dist = math.sqrt((edge_mid[0] - mirrored_mid[0])**2 + (edge_mid[1] - mirrored_mid[1])**2)
        if dist < best_dist:
            best_dist = dist
            best_edge = i
    
    return best_edge if best_dist < 50 else -1


def _normalize_screen_points_to_profile(screen_points):
    """Convert screen-space points to normalized 2D profile points."""
    if not screen_points or len(screen_points) < 3:
        return []
    
    center_x = sum(p[0] for p in screen_points) / len(screen_points)
    center_y = sum(p[1] for p in screen_points) / len(screen_points)
    
    centered_points = [(p[0] - center_x, p[1] - center_y) for p in screen_points]
    
    max_dist = 0.0
    for p in centered_points:
        dist = math.sqrt(p[0]**2 + p[1]**2)
        if dist > max_dist:
            max_dist = dist
    
    if max_dist > 0.0001:
        normalized_points = [(p[0] / max_dist, p[1] / max_dist) for p in centered_points]
    else:
        normalized_points = centered_points
    
    return normalized_points


def _profile_points_to_screen(normalized_points, context):
    """Convert normalized profile points to screen-space points for editing."""
    if not normalized_points:
        return []
    
    region = context.region
    center_x = region.width / 2
    center_y = region.height / 2
    
    scale = min(region.width, region.height) * 0.25
    
    screen_points = []
    for p in normalized_points:
        sx = center_x + p[0] * scale
        sy = center_y + p[1] * scale
        screen_points.append((sx, sy))
    
    return screen_points


def _get_profile_center(screen_points):
    """Get the center of the profile points."""
    if not screen_points:
        return (0, 0)
    cx = sum(p[0] for p in screen_points) / len(screen_points)
    cy = sum(p[1] for p in screen_points) / len(screen_points)
    return (cx, cy)


def _scale_profile_points(screen_points, scale_factor, center=None):
    """Scale profile points around center."""
    if not screen_points:
        return []
    if center is None:
        center = _get_profile_center(screen_points)
    
    scaled = []
    for p in screen_points:
        dx = p[0] - center[0]
        dy = p[1] - center[1]
        scaled.append((center[0] + dx * scale_factor, center[1] + dy * scale_factor))
    return scaled


def _rotate_profile_points(screen_points, angle, center=None):
    """Rotate profile points around center by angle (radians)."""
    if not screen_points:
        return []
    if center is None:
        center = _get_profile_center(screen_points)
    
    cos_a = math.cos(angle)
    sin_a = math.sin(angle)
    
    rotated = []
    for p in screen_points:
        dx = p[0] - center[0]
        dy = p[1] - center[1]
        rx = dx * cos_a - dy * sin_a
        ry = dx * sin_a + dy * cos_a
        rotated.append((center[0] + rx, center[1] + ry))
    return rotated


def _move_profile_points(screen_points, offset):
    """Move all profile points by an offset."""
    if not screen_points:
        return []
    moved = []
    for p in screen_points:
        moved.append((p[0] + offset[0], p[1] + offset[1]))
    return moved


def _update_mesh_from_profile_edit(operator, context, screen_points):
    """Update the flex mesh preview from current screen profile points."""
    if len(screen_points) < 3:
        return
    if len(state.points_3d) < 2 or len(state.point_radii_3d) < 2:
        return
    
    normalized_points = _normalize_screen_points_to_profile(screen_points)
    if len(normalized_points) < 3:
        return
    
    state.custom_profile_points = normalized_points
    state.profile_global_type = state.PROFILE_CUSTOM
    
    n_pts = len(normalized_points)
    operator.resolution = n_pts
    
    mesh_utils.update_preview_mesh(
        context, state.points_3d, state.point_radii_3d,
        resolution=operator.resolution, segments=operator.segments
    )


def _cancel_profile_edit_mode(operator, context):
    """Cancel profile edit mode and restore the previous profile state."""
    # Restore from backup if available
    if state._custom_profile_backup is not None:
        state.custom_profile_points = state._custom_profile_backup.get('points', [])
        state.profile_global_type = state._custom_profile_backup.get('profile_type', state.PROFILE_CIRCULAR)
        state.custom_profile_curve_name = state._custom_profile_backup.get('curve_name', None)
        state._custom_profile_backup = None
        
        # Update mesh to reflect restored profile
        if len(state.points_3d) >= 2 and len(state.point_radii_3d) >= 2:
            if state.custom_profile_points and len(state.custom_profile_points) >= 3:
                operator.resolution = len(state.custom_profile_points)
            mesh_utils.update_preview_mesh(
                context, state.points_3d, state.point_radii_3d,
                resolution=operator.resolution, segments=operator.segments
            )
    
    # Set lockout if G was being used to prevent group move trigger
    if state.custom_profile_moving:
        state._profile_exit_g_lockout = True
    
    # Reset all profile edit mode state
    state.custom_profile_draw_mode = False
    state._custom_profile_data['screen_points'] = []
    state.custom_profile_hover_index = -1
    state.custom_profile_active_index = -1
    state.custom_profile_hover_edge = -1
    state.custom_profile_hover_edge_point = None
    state.custom_profile_scaling = False
    state.custom_profile_rotating = False
    state.custom_profile_moving = False
    state.custom_profile_transform_start_pos = None
    state.custom_profile_symmetry = False
    state.custom_profile_symmetry_angle = 0.0
    state.custom_profile_symmetry_center = None
    state.custom_profile_point_pairs = {}
    
    operator.report({'INFO'}, "Profile edit cancelled")
    context.area.tag_redraw()


def modal_handler(operator, context, event):
    """Handle modal events for the flex tool"""
    
    if event.type == state.KEY_CANCEL and event.value == 'PRESS':
        if getattr(state, 'custom_profile_draw_mode', False):
            # Cancel profile edit and restore previous state
            _cancel_profile_edit_mode(operator, context)
            return {'RUNNING_MODAL'}
        operator._edit_cancelled = True
        operator.finish(context)
        return {'CANCELLED'}
    
    # Parent Mode toggle with TAB (hold to activate) with lockout until TAB released
    if event.type == state.KEY_PARENT_MODE and event.value == 'PRESS':
        if not getattr(state, 'parent_mode_lockout', False):
            state.parent_mode_active = True
            context.area.tag_redraw()
            operator.report({'INFO'}, "Parent Mode: Click an object to set as parent")
        return {'RUNNING_MODAL'}

    if event.type == state.KEY_PARENT_MODE and event.value == 'RELEASE':
        state.parent_mode_active = False
        state.parent_mode_lockout = False
        context.area.tag_redraw()
        return {'RUNNING_MODAL'}

    # When in Parent Mode, intercept LMB to pick an object in the viewport
    if state.parent_mode_active and event.type == 'LEFTMOUSE' and event.value == 'PRESS':
        # Avoid modifiers to not clash with navigation
        if event.alt or event.ctrl or event.shift or event.oskey:
            return {'PASS_THROUGH'}
        region = context.region
        rv3d = context.region_data
        if not rv3d:
            return {'RUNNING_MODAL'}
        mouse_pos = (event.mouse_region_x, event.mouse_region_y)
        origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, mouse_pos)
        direction = view3d_utils.region_2d_to_vector_3d(region, rv3d, mouse_pos).normalized()
        depsgraph = context.evaluated_depsgraph_get()
        hit, loc, normal, face_index, obj, matrix, *_rest = context.scene.ray_cast(depsgraph, origin, direction, distance=1.0e10)
        if hit and obj is not None:
            # Ignore preview mesh if present
            if not (state.preview_mesh_obj and obj == state.preview_mesh_obj):
                state.selected_parent_name = obj.name
                operator.report({'INFO'}, f"Parent set to: {obj.name}")
        else:
            # Use empty string to indicate explicitly cleared parent (different from None which means not set)
            state.selected_parent_name = ""
            operator.report({'INFO'}, "No object under cursor. Parent cleared.")
        # Exit Parent Mode after click and lock until TAB is released
        state.parent_mode_active = False
        state.parent_mode_lockout = True
        context.area.tag_redraw()
        return {'RUNNING_MODAL'}

    if event.type == state.KEY_TOGGLE_HUD and event.value == 'PRESS':
        state.hud_help_visible = not getattr(state, 'hud_help_visible', True)
        status = "ON" if state.hud_help_visible else "OFF"
        operator.report({'INFO'}, f"HUD Help: {status}")
        context.area.tag_redraw()
        return {'RUNNING_MODAL'}

    if event.type == state.KEY_BSPLINE and event.value == 'PRESS':
        state.bspline_mode = not getattr(state, 'bspline_mode', False)
        status = "ON" if state.bspline_mode else "OFF"
        operator.report({'INFO'}, f"B-spline mode: {status}")
        state.save_history_state()
        if len(state.points_3d) >= 2 and len(state.point_radii_3d) >= 2:
            mesh_utils.update_preview_mesh(context, state.points_3d, state.point_radii_3d,
                                          resolution=operator.resolution, segments=operator.segments)
        context.area.tag_redraw()
        return {'RUNNING_MODAL'}

    if event.type == state.KEY_PROFILE_CAP_TOGGLE and event.value == 'PRESS':
        if state.hover_point_index == 0:
            state.start_cap_type = (state.start_cap_type + 1) % 3
            state.save_history_state()
            cap_type_name = ['None', 'Hemisphere', 'Planar'][state.start_cap_type]
            operator.report({'INFO'}, f"Start cap set to {cap_type_name}")
        elif state.hover_point_index == len(state.points_3d) - 1:
            state.end_cap_type = (state.end_cap_type + 1) % 3
            state.save_history_state()
            cap_type_name = ['None', 'Hemisphere', 'Planar'][state.end_cap_type]
            operator.report({'INFO'}, f"End cap set to {cap_type_name}")
        else:
            state.start_cap_type = (state.start_cap_type + 1) % 3
            state.end_cap_type = (state.end_cap_type + 1) % 3
            state.save_history_state()
            cap_type_name = ['None', 'Hemisphere', 'Planar'][state.start_cap_type]
            operator.report({'INFO'}, f"Both caps set to {cap_type_name}")
        
        if len(state.points_3d) >= 2 and len(state.point_radii_3d) >= 2:
            mesh_utils.update_preview_mesh(context, state.points_3d, state.point_radii_3d, 
                                          resolution=operator.resolution, segments=operator.segments)
        return {'RUNNING_MODAL'}
    
    if event.type == state.KEY_ADAPTIVE and event.value == 'PRESS':
        state.adaptive_segmentation = not state.adaptive_segmentation
        status = "ON" if state.adaptive_segmentation else "OFF"
        operator.report({'INFO'}, f"Adaptive Densification: {status}")
        state.save_history_state()
        
        if len(state.points_3d) >= 2 and len(state.point_radii_3d) >= 2:
            mesh_utils.update_preview_mesh(context, state.points_3d, state.point_radii_3d, 
                                          resolution=operator.resolution, segments=operator.segments)
        return {'RUNNING_MODAL'}
    
    if event.value == 'PRESS' and event.type in {state.KEY_PROFILE_TYPE_1, state.KEY_PROFILE_TYPE_2, state.KEY_PROFILE_TYPE_3}:
        if event.type == state.KEY_PROFILE_TYPE_1:
            state.profile_global_type = state.PROFILE_CIRCULAR
            profile_name = "Circular"
        elif event.type == state.KEY_PROFILE_TYPE_2:
            state.profile_global_type = state.PROFILE_SQUARE
            profile_name = "Square"
            operator.resolution = 8
        elif event.type == state.KEY_PROFILE_TYPE_3:
            state.profile_global_type = state.PROFILE_SQUARE_ROUNDED
            profile_name = "Rounded Square"
            operator.resolution = 12
        operator.report({'INFO'}, f"Profile Type: {profile_name}")
        state.save_history_state()
        if len(state.points_3d) >= 2 and len(state.point_radii_3d) >= 2:
            mesh_utils.update_preview_mesh(context, state.points_3d, state.point_radii_3d, 
                                          resolution=operator.resolution, segments=operator.segments)
        return {'RUNNING_MODAL'}
    
    # Custom profiles: Keys 4-9 for 6 custom profile slots
    # Alt+key: Enter draw mode for that slot, key alone: Use that slot's profile
    custom_profile_keys = {
        state.KEY_PROFILE_TYPE_4: 0,
        state.KEY_PROFILE_TYPE_5: 1,
        state.KEY_PROFILE_TYPE_6: 2,
        state.KEY_PROFILE_TYPE_7: 3,
        state.KEY_PROFILE_TYPE_8: 4,
        state.KEY_PROFILE_TYPE_9: 5,
    }
    if event.value == 'PRESS' and event.type in custom_profile_keys:
        slot_index = custom_profile_keys[event.type]
        slot_num = slot_index + 4  # Display as 4-8
        
        if event.alt:
            # Alt+key: Enter custom profile drawing mode for this slot
            state.active_custom_profile_slot = slot_index
            
            # Load existing profile from slot if available
            slot_points = state.custom_profile_slots[slot_index] if slot_index < len(state.custom_profile_slots) else []
            if slot_points:
                state.custom_profile_points = list(slot_points)
            
            # Save backup for cancel/restore
            state._custom_profile_backup = {
                'points': list(state.custom_profile_points) if state.custom_profile_points else [],
                'profile_type': state.profile_global_type,
                'curve_name': state.custom_profile_curve_name,
                'slot_index': slot_index,
            }
            
            state.custom_profile_draw_mode = True
            state.custom_profile_hover_index = -1
            state.custom_profile_active_index = -1
            state.custom_profile_hover_edge = -1
            state.custom_profile_hover_edge_point = None
            state.custom_profile_scaling = False
            state.custom_profile_rotating = False
            state.custom_profile_moving = False
            state.custom_profile_transform_start_pos = None
            
            # Restore symmetry state from slot
            slot_symmetry = state.custom_profile_slot_symmetry[slot_index] if slot_index < len(state.custom_profile_slot_symmetry) else False
            state.custom_profile_symmetry = slot_symmetry
            state.custom_profile_symmetry_angle = 0.0  # Always start with vertical axis
            state.custom_profile_symmetry_center = None  # Will be set after screen points are generated
            state.custom_profile_point_pairs = {}
            
            if state.custom_profile_points and len(state.custom_profile_points) >= 3:
                screen_points = _profile_points_to_screen(state.custom_profile_points, context)
                
                # If symmetry was enabled, filter to only right-side points
                if slot_symmetry and len(screen_points) >= 2:
                    center = _get_profile_center(screen_points)
                    state.custom_profile_symmetry_center = center
                    # Keep only right-side points (positive X relative to center after rotation)
                    right_side_points = []
                    for pt in screen_points:
                        if _is_point_on_right_side(pt, center, 0.0):
                            right_side_points.append(pt)
                    # Use right-side points only (mirror will be generated automatically)
                    if len(right_side_points) >= 1:
                        screen_points = right_side_points
                
                state._custom_profile_data['screen_points'] = screen_points
                sym_status = " (Symmetry ON)" if slot_symmetry else ""
                operator.report({'INFO'}, f"Edit Custom Profile {slot_num}{sym_status}: LMB add/move, RMB delete, Enter accept, Esc cancel")
            else:
                state._custom_profile_data['screen_points'] = []
                operator.report({'INFO'}, f"Draw Custom Profile {slot_num}: LMB add, RMB delete, Enter accept, Esc cancel")
            
            context.area.tag_redraw()
            return {'RUNNING_MODAL'}
        else:
            # Key alone: Use custom profile from this slot if one exists
            slot_points = state.custom_profile_slots[slot_index] if slot_index < len(state.custom_profile_slots) else []
            if slot_points and len(slot_points) >= 3:
                state.active_custom_profile_slot = slot_index
                state.custom_profile_points = list(slot_points)
                state.profile_global_type = state.PROFILE_CUSTOM
                n_pts = len(state.custom_profile_points)
                operator.resolution = n_pts
                operator.report({'INFO'}, f"Profile: Custom {slot_num} ({n_pts} points)")
                state.save_history_state()
                if len(state.points_3d) >= 2 and len(state.point_radii_3d) >= 2:
                    mesh_utils.update_preview_mesh(context, state.points_3d, state.point_radii_3d, 
                                                  resolution=operator.resolution, segments=operator.segments)
            else:
                operator.report({'WARNING'}, f"No custom profile in slot {slot_num}. Press Alt+{slot_num} to draw one.")
            return {'RUNNING_MODAL'}
    
    # Handle custom profile drawing mode
    if getattr(state, 'custom_profile_draw_mode', False):
        result = _handle_custom_profile_mode(operator, context, event)
        if result is not None:
            return result
    
    if event.type == state.KEY_PROFILE_ROUNDNESS and event.value == 'PRESS':
        roundness_values = [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]
        current_index = 0
        for i, val in enumerate(roundness_values):
            if abs(state.profile_roundness - val) < 0.01:
                current_index = i
                break
        
        next_index = (current_index + 1) % len(roundness_values)
        state.profile_roundness = roundness_values[next_index]
        state.profile_point_roundness = []
        
        operator.report({'INFO'}, f"Global Profile Roundness: {state.profile_roundness:.1f}")
        state.save_history_state()
        
        if len(state.points_3d) >= 2 and len(state.point_radii_3d) >= 2:
            mesh_utils.update_preview_mesh(context, state.points_3d, state.point_radii_3d, 
                                          resolution=operator.resolution, segments=operator.segments)
        return {'RUNNING_MODAL'}
    
    if event.type == 'Z' and event.value == 'PRESS' and (event.ctrl or event.oskey):
        if event.shift:
            if state.redo_action():
                if len(state.points_3d) >= 2 and len(state.point_radii_3d) >= 2:
                    mesh_utils.update_preview_mesh(context, state.points_3d, state.point_radii_3d, 
                                                  resolution=operator.resolution, segments=operator.segments)
                else:
                    if state.preview_mesh_obj is not None:
                        try:
                            if state.preview_mesh_obj.name in bpy.data.objects:
                                for collection in state.preview_mesh_obj.users_collection:
                                    collection.objects.unlink(state.preview_mesh_obj)
                                bpy.data.objects.remove(state.preview_mesh_obj)
                        except Exception as e:
                            print(f"Failed to remove preview mesh: {e}")
                        state.preview_mesh_obj = None
                operator.report({'INFO'}, "Redo")
            else:
                operator.report({'INFO'}, "Nothing to redo")
            return {'RUNNING_MODAL'}
        else:
            if state.undo_action():
                if len(state.points_3d) >= 2 and len(state.point_radii_3d) >= 2:
                    mesh_utils.update_preview_mesh(context, state.points_3d, state.point_radii_3d, 
                                                  resolution=operator.resolution, segments=operator.segments)
                else:
                    if state.preview_mesh_obj is not None:
                        try:
                            if state.preview_mesh_obj.name in bpy.data.objects:
                                for collection in state.preview_mesh_obj.users_collection:
                                    collection.objects.unlink(state.preview_mesh_obj)
                                bpy.data.objects.remove(state.preview_mesh_obj)
                        except Exception as e:
                            print(f"Failed to remove preview mesh: {e}")
                        state.preview_mesh_obj = None
                operator.report({'INFO'}, "Undo")
            else:
                operator.report({'INFO'}, "Nothing to undo")
            return {'RUNNING_MODAL'}
    
    if event.type == state.KEY_SNAPPING_MODE and event.value == 'PRESS':
        if state.snapping_mode == state.SNAPPING_OFF:
            state.snapping_mode = state.SNAPPING_FACE
            state.face_projection_enabled = True
            operator.report({'INFO'}, "Snapping: Face Projection")
        else:
            state.snapping_mode = state.SNAPPING_OFF
            state.face_projection_enabled = False
            operator.report({'INFO'}, "Snapping: Off")
        
        context.area.tag_redraw()
        return {'RUNNING_MODAL'}

    if event.type == state.KEY_MIRROR and event.value == 'PRESS':
        state.mirror_mode_active = not state.mirror_mode_active
        status = "ON" if state.mirror_mode_active else "OFF"
        operator.report({'INFO'}, f"Mirror Mode: {status}")
        if state.preview_mesh_obj is not None:
            mesh_utils.apply_mirror_modifier(state.preview_mesh_obj, state.mirror_mode_active)
            if state.mirror_mode_active:
                mesh_utils.update_mirror_flip_from_points(state.preview_mesh_obj, state.points_3d)
        context.area.tag_redraw()
        return {'RUNNING_MODAL'}

    # Group move: press G to move all points together in screen space
    if event.type == state.KEY_GROUP_MOVE and event.value == 'PRESS':
        # Skip if in profile edit mode (G is used for profile move there)
        if getattr(state, 'custom_profile_draw_mode', False):
            return {'RUNNING_MODAL'}
        # Skip if lockout is active (just exited profile edit with G held)
        if getattr(state, '_profile_exit_g_lockout', False):
            return {'RUNNING_MODAL'}
        if len(state.points_3d) > 0 and not state.group_move_active:
            region = context.region
            rv3d = context.region_data
            if rv3d:
                # Compute world-space center of all points
                world_points = []
                for p in state.points_3d:
                    pw = state.object_matrix_world @ p if state.object_matrix_world else p
                    world_points.append(pw)
                if world_points:
                    center = Vector((0.0, 0.0, 0.0))
                    for wp in world_points:
                        center += wp
                    center /= len(world_points)
                    # Save state for undo before starting the move
                    state.save_history_state()
                    state.group_move_active = True
                    state.group_move_start_point = center
                    state.group_move_start_mouse_pos = (event.mouse_region_x, event.mouse_region_y)
                    state.group_move_original_positions = [p.copy() for p in state.points_3d]
                    operator.report({'INFO'}, "Move All Points: Drag to reposition, LMB to accept, RMB to cancel")
                    context.area.tag_redraw()
        return {'RUNNING_MODAL'}
    
    # Clear G lockout on G key release
    if event.type == state.KEY_GROUP_MOVE and event.value == 'RELEASE':
        if getattr(state, '_profile_exit_g_lockout', False):
            state._profile_exit_g_lockout = False
            return {'RUNNING_MODAL'}

    # When group move is active, handle LMB/RMB to accept or cancel the move
    if state.group_move_active:
        # Accept move with LMB: simply end group move, current positions are already in state.points_3d
        if event.type == 'LEFTMOUSE' and event.value == 'PRESS':
            state.group_move_active = False
            state.group_move_start_point = None
            state.group_move_start_mouse_pos = None
            state.group_move_original_positions = []
            context.area.tag_redraw()
            return {'RUNNING_MODAL'}

        # Cancel move with RMB: restore original positions and end group move
        if event.type == 'RIGHTMOUSE' and event.value == 'PRESS':
            if state.group_move_original_positions and len(state.group_move_original_positions) == len(state.points_3d):
                state.points_3d = [p.copy() for p in state.group_move_original_positions]
                if len(state.points_3d) >= 2 and len(state.point_radii_3d) >= 2:
                    mesh_utils.update_preview_mesh(
                        context,
                        state.points_3d,
                        state.point_radii_3d,
                        resolution=operator.resolution,
                        segments=operator.segments,
                    )
            state.group_move_active = False
            state.group_move_start_point = None
            state.group_move_start_mouse_pos = None
            state.group_move_original_positions = []
            context.area.tag_redraw()
            return {'RUNNING_MODAL'}

    if event.type in {'WHEELUPMOUSE', 'WHEELDOWNMOUSE'}:
        wheel_up = (event.type == 'WHEELUPMOUSE')
        
        # Radius ramp: when radius_scale_active (RMB held in empty space), use wheel for ramp
        if getattr(state, 'radius_scale_active', False) and not getattr(state, 'profile_twist_mode', False):
            original = getattr(state, 'radius_ramp_original_radii', None) or getattr(state, 'radius_scale_original_radii', None) or list(state.point_radii_3d)
            if len(original) != len(state.point_radii_3d):
                original = list(state.point_radii_3d)
            state.radius_ramp_original_radii = original
            
            step = 0.1
            delta = step if wheel_up else -step
            current_ramp = getattr(state, 'radius_ramp_amount', 0.0)
            state.radius_ramp_amount = max(-1.0, min(1.0, current_ramp + delta))
            state.radius_ramp_active = abs(state.radius_ramp_amount) > 1e-3
            
            num_points = len(original)
            if num_points >= 2:
                for i, r0 in enumerate(original):
                    t = i / (num_points - 1)
                    amt = state.radius_ramp_amount
                    if amt >= 0.0:
                        scale = 1.0 - (t * amt)
                    else:
                        scale = 1.0 - ((1.0 - t) * abs(amt))
                    scale = max(0.1, min(1.0, scale))
                    new_r = max(state.MIN_RADIUS, min(r0 * scale, state.MAX_RADIUS))
                    if i < len(state.point_radii_3d):
                        state.point_radii_3d[i] = new_r
            
            if len(state.points_3d) >= 2 and len(state.point_radii_3d) >= 2:
                mesh_utils.update_preview_mesh(context, state.points_3d, state.point_radii_3d,
                                              resolution=operator.resolution, segments=operator.segments)
            context.area.tag_redraw()
            return {'RUNNING_MODAL'}
        
        # Twist ramp: when in twist mode, use wheel for twist ramp
        if getattr(state, 'profile_twist_mode', False):
            step = math.radians(15.0)
            delta = step if wheel_up else -step
            
            num_points = len(state.points_3d)
            if len(state.profile_point_twists) != num_points:
                state.profile_point_twists = [0.0] * num_points
            
            # Store the first point's twist as baseline when starting ramp
            if not hasattr(state, 'twist_ramp_base') or state.twist_ramp_amount == 0.0:
                state.twist_ramp_base = state.profile_point_twists[0] if num_points > 0 else 0.0
            
            state.twist_ramp_amount += delta
            
            # Apply ramped twist along the curve, preserving first point's twist
            if num_points >= 2:
                base_twist = getattr(state, 'twist_ramp_base', 0.0)
                for i in range(num_points):
                    t = i / (num_points - 1)
                    # Ramp from base_twist at start to base_twist + twist_ramp_amount at end
                    state.profile_point_twists[i] = base_twist + (t * state.twist_ramp_amount)
            
            if len(state.points_3d) >= 2 and len(state.point_radii_3d) >= 2:
                mesh_utils.update_preview_mesh(context, state.points_3d, state.point_radii_3d,
                                              resolution=operator.resolution, segments=operator.segments)
            context.area.tag_redraw()
            return {'RUNNING_MODAL'}
        
        # Normal wheel behavior: resolution/segments
        if event.shift:
            old_val = operator.resolution
            step = 2 if wheel_up else -2
            operator.resolution = max(4, min(64, operator.resolution + step))
            if operator.resolution != old_val:
                operator.report({'INFO'}, f"Circumference resolution: {operator.resolution}")
                if len(state.points_3d) >= 2 and len(state.point_radii_3d) >= 2:
                    mesh_utils.update_preview_mesh(context, state.points_3d, state.point_radii_3d, 
                                                  resolution=operator.resolution, segments=operator.segments)
        else:
            old_val = operator.segments
            step = 4 if wheel_up else -4
            operator.segments = max(8, min(128, operator.segments + step))
            if operator.segments != old_val:
                operator.report({'INFO'}, f"Length segments: {operator.segments}")
                if len(state.points_3d) >= 2 and len(state.point_radii_3d) >= 2:
                    mesh_utils.update_preview_mesh(context, state.points_3d, state.point_radii_3d, 
                                                  resolution=operator.resolution, segments=operator.segments)
        return {'RUNNING_MODAL'}

    if event.type == state.KEY_TWIST and event.value == 'PRESS':
        state.profile_twist_mode = True
        if len(state.profile_point_twists) != len(state.points_3d):
            existing = list(state.profile_point_twists) if state.profile_point_twists else []
            needed = len(state.points_3d) - len(existing)
            if needed > 0:
                existing.extend([0.0] * needed)
            state.profile_point_twists = existing[:len(state.points_3d)]
        operator.report({'INFO'}, "Twist Mode: ON")
        context.area.tag_redraw()
        return {'RUNNING_MODAL'}
    if event.type == state.KEY_TWIST and event.value == 'RELEASE':
        state.profile_twist_mode = False
        operator.report({'INFO'}, "Twist Mode: OFF")
        context.area.tag_redraw()
        return {'RUNNING_MODAL'}

    # Handle middle mouse button for radius equalize and twist reset
    if event.type == 'MIDDLEMOUSE' and event.value == 'PRESS':
        # Radius scale active: MMB equalizes all radii to average
        if getattr(state, 'radius_scale_active', False) and not getattr(state, 'profile_twist_mode', False):
            original = getattr(state, 'radius_scale_original_radii', None) or list(state.point_radii_3d)
            if original:
                avg = sum(original) / len(original)
                avg = max(state.MIN_RADIUS, min(avg, state.MAX_RADIUS))
                for i in range(len(state.point_radii_3d)):
                    state.point_radii_3d[i] = avg
                if len(state.points_3d) >= 2 and len(state.point_radii_3d) >= 2:
                    mesh_utils.update_preview_mesh(context, state.points_3d, state.point_radii_3d,
                                                  resolution=operator.resolution, segments=operator.segments)
                state.radius_equalize_active = True
                operator.report({'INFO'}, f"Radii equalized to {avg:.3f}")
                context.area.tag_redraw()
            return {'RUNNING_MODAL'}
        
        # Twist mode: MMB resets all twist values
        if getattr(state, 'profile_twist_mode', False) and not (event.alt or event.ctrl or event.shift or event.oskey):
            state.save_history_state()
            state.profile_global_twist = 0.0
            state.profile_point_twists = [0.0] * len(state.points_3d)
            state.twist_ramp_amount = 0.0
            state.twist_ramp_base = 0.0
            if len(state.points_3d) >= 2 and len(state.point_radii_3d) >= 2:
                mesh_utils.update_preview_mesh(context, state.points_3d, state.point_radii_3d,
                                              resolution=operator.resolution, segments=operator.segments)
            operator.report({'INFO'}, "Twist values reset to 0")
            context.area.tag_redraw()
            return {'RUNNING_MODAL'}
        
        # Otherwise pass through for navigation
        return {'PASS_THROUGH'}

    camera_nav_keys = {
        'MIDDLEMOUSE', 'WHEELUPMOUSE', 'WHEELDOWNMOUSE',
        'NUMPAD_2', 'NUMPAD_4', 'NUMPAD_6', 'NUMPAD_8', 'NUMPAD_1', 'NUMPAD_3', 'NUMPAD_7',
        'NUMPAD_9', 'NUMPAD_5', 'NUMPAD_0', 'NUMPAD_PERIOD', 'NUMPAD_SLASH', 'NUMPAD_ASTERIX',
        'TIMER', 'GESTURE_ZOOM', 'GESTURE_ROTATE', 'GESTURE_SWIPE',
        'TRACKPADPAN', 'TRACKPADZOOM', 'EVT_TWEAK_L', 'EVT_TWEAK_M', 'EVT_TWEAK_R',
    }
    if event.type in camera_nav_keys:
        if event.type != 'MIDDLEMOUSE':
            return {'PASS_THROUGH'}

    if not operator.is_mouse_in_region(context, event):
        return {'PASS_THROUGH'}

    allowed_tool_keys = {
        'ESC', 'RET', 'NUMPAD_ENTER', 'C', 'Z', 'F', 'LEFT_BRACKET', 'RIGHT_BRACKET', 'COMMA', 'PERIOD', 'T', 'A', 'R',
        'ONE', 'TWO', 'THREE', 'FOUR', 'FIVE', 'SIX', 'SEVEN', 'EIGHT', 'NINE', 'BACK_SPACE',
        'MOUSEMOVE', 'LEFTMOUSE', 'RIGHTMOUSE', 'INBETWEEN_MOUSEMOVE', 'SPACE', 'SPACEBAR', 'SLASH', 'S', 'X', 'B', 'H', 'G',
        'MIDDLEMOUSE', 'WHEELUPMOUSE', 'WHEELDOWNMOUSE', 'TRACKPADPAN', 'TRACKPADZOOM',
    }
    # Add the configured switch mesh key dynamically
    allowed_tool_keys.add(state.KEY_SWITCH_MESH)
    
    if event.type not in allowed_tool_keys:
        return {'RUNNING_MODAL'}
    
    # Switch to hovered flex mesh (default Alt+Q, configurable)
    if event.type == state.KEY_SWITCH_MESH and event.value == 'PRESS':
        # Check modifiers from preferences
        prefs = None
        try:
            addon_prefs = bpy.context.preferences.addons.get("super_tools")
            if addon_prefs:
                prefs = addon_prefs.preferences
        except Exception:
            pass
        
        req_alt = getattr(prefs, 'flex_key_switch_mesh_alt', True) if prefs else True
        req_ctrl = getattr(prefs, 'flex_key_switch_mesh_ctrl', False) if prefs else False
        req_shift = getattr(prefs, 'flex_key_switch_mesh_shift', False) if prefs else False
        
        # Check if all required modifiers match
        if event.alt == req_alt and event.ctrl == req_ctrl and event.shift == req_shift:
            return switch_target_flex(operator, context, event)

    if event.type == 'LEFTMOUSE':
        if event.alt or event.ctrl or event.shift or event.oskey:
            return {'PASS_THROUGH'}
        return flex_interaction_points.handle_left_mouse(operator, context, event)
    
    if event.type == 'RIGHTMOUSE':
        if event.alt or event.ctrl or event.oskey:
            return {'PASS_THROUGH'}
        return flex_interaction_points.handle_right_mouse(operator, context, event)
    
    if event.type == 'MOUSEMOVE':
        return flex_interaction_points.handle_mouse_move(operator, context, event)
    
    if event.type == 'RET' and event.value == 'PRESS':
        return handle_enter(operator, context)
    
    if event.type in {'SPACE', 'SPACEBAR'} and event.value == 'PRESS':
        return handle_accept_and_continue(operator, context)
    
    return {'PASS_THROUGH'}


def _handle_custom_profile_mode(operator, context, event):
    """Handle events while in custom profile drawing mode"""
    mouse_pos = (event.mouse_region_x, event.mouse_region_y)
    screen_points = state._custom_profile_data.get('screen_points', [])
    
    # LMB to add/drag points
    if event.type == 'LEFTMOUSE':
        if event.alt or event.ctrl or event.shift or event.oskey:
            return None  # Pass through
        
        if event.value == 'PRESS':
            closest_idx = _find_closest_custom_profile_point(mouse_pos, screen_points, threshold=15.0)
            if closest_idx >= 0:
                state.custom_profile_active_index = closest_idx
                context.area.tag_redraw()
                return {'RUNNING_MODAL'}
            
            # Check edge hover for insertion
            if state.custom_profile_hover_edge >= 0 and state.custom_profile_hover_edge_point is not None:
                insert_idx = state.custom_profile_hover_edge + 1
                insert_point = state.custom_profile_hover_edge_point
                
                # In symmetry mode, validate insertion point is on right side
                if getattr(state, 'custom_profile_symmetry', False):
                    center = state.custom_profile_symmetry_center
                    angle = state.custom_profile_symmetry_angle
                    if center and not _is_point_on_right_side(insert_point, center, angle):
                        operator.report({'WARNING'}, "Can only insert points on the right side")
                        return {'RUNNING_MODAL'}
                
                screen_points.insert(insert_idx, insert_point)
                state.custom_profile_active_index = insert_idx
                state.custom_profile_hover_edge = -1
                state.custom_profile_hover_edge_point = None
                operator.report({'INFO'}, f"Profile point inserted ({len(screen_points)} total)")
                
                # In symmetry mode, update with full symmetric profile
                if getattr(state, 'custom_profile_symmetry', False):
                    center = state.custom_profile_symmetry_center
                    angle = state.custom_profile_symmetry_angle
                    full_profile = _generate_symmetric_profile(screen_points, center, angle)
                    _update_mesh_from_profile_edit(operator, context, full_profile)
                else:
                    _update_mesh_from_profile_edit(operator, context, screen_points)
                
                context.area.tag_redraw()
                return {'RUNNING_MODAL'}
            
            # Add new point (with symmetry restrictions if enabled)
            if getattr(state, 'custom_profile_symmetry', False):
                # In symmetry mode, only allow points on right side
                # Use the fixed symmetry center
                center = state.custom_profile_symmetry_center
                angle = state.custom_profile_symmetry_angle
                
                if not _is_point_on_right_side(mouse_pos, center, angle):
                    operator.report({'WARNING'}, "Place points on the right side of symmetry line")
                    return {'RUNNING_MODAL'}
                
                # Add point to right-side collection
                screen_points.append(mouse_pos)
                state._custom_profile_data['screen_points'] = screen_points
                operator.report({'INFO'}, f"Profile point {len(screen_points)} added (right side)")
                
                # Generate full symmetric profile for mesh preview
                full_profile = _generate_symmetric_profile(screen_points, center, angle)
                _update_mesh_from_profile_edit(operator, context, full_profile)
            else:
                screen_points.append(mouse_pos)
                state._custom_profile_data['screen_points'] = screen_points
                operator.report({'INFO'}, f"Profile point {len(screen_points)} added")
                _update_mesh_from_profile_edit(operator, context, screen_points)
            
            context.area.tag_redraw()
            return {'RUNNING_MODAL'}
        
        elif event.value == 'RELEASE':
            if state.custom_profile_active_index >= 0:
                state.custom_profile_active_index = -1
                context.area.tag_redraw()
            return {'RUNNING_MODAL'}
    
    # RMB to delete points
    if event.type == 'RIGHTMOUSE' and event.value == 'PRESS':
        if event.alt or event.ctrl or event.shift or event.oskey:
            return None
        
        closest_idx = _find_closest_custom_profile_point(mouse_pos, screen_points, threshold=15.0)
        if closest_idx >= 0:
            screen_points.pop(closest_idx)
            operator.report({'INFO'}, f"Profile point deleted ({len(screen_points)} remaining)")
            state.custom_profile_hover_index = -1
            state.custom_profile_hover_edge = -1
            
            # In symmetry mode, update with full symmetric profile
            if getattr(state, 'custom_profile_symmetry', False) and len(screen_points) >= 1:
                center = state.custom_profile_symmetry_center
                angle = state.custom_profile_symmetry_angle
                full_profile = _generate_symmetric_profile(screen_points, center, angle)
                _update_mesh_from_profile_edit(operator, context, full_profile)
            else:
                _update_mesh_from_profile_edit(operator, context, screen_points)
            
            context.area.tag_redraw()
            return {'RUNNING_MODAL'}
        return {'RUNNING_MODAL'}
    
    # ESC to cancel profile edit and restore previous state
    if event.type == 'ESC' and event.value == 'PRESS':
        _cancel_profile_edit_mode(operator, context)
        return {'RUNNING_MODAL'}
    
    # Handle profile scaling (S key held)
    if event.type == 'S':
        if event.value == 'PRESS' and not state.custom_profile_scaling:
            state.custom_profile_scaling = True
            state.custom_profile_transform_start_pos = mouse_pos
            operator.report({'INFO'}, "Scaling profile (move mouse to scale)")
            return {'RUNNING_MODAL'}
        elif event.value == 'RELEASE':
            state.custom_profile_scaling = False
            state.custom_profile_transform_start_pos = None
            context.area.tag_redraw()
            return {'RUNNING_MODAL'}
    
    # Rotation disabled in profile drawing mode - causes issues with symmetry
    # R key is blocked to prevent accidental activation
    if event.type == 'R':
        return {'RUNNING_MODAL'}
    
    # Block SPACE key to prevent 'accept and continue' during profile edit
    if event.type in {'SPACE', 'SPACEBAR'}:
        return {'RUNNING_MODAL'}
    
    # Handle profile moving (G key held)
    if event.type == 'G':
        if event.value == 'PRESS' and not state.custom_profile_moving:
            state.custom_profile_moving = True
            state.custom_profile_transform_start_pos = mouse_pos
            operator.report({'INFO'}, "Moving profile (move mouse to translate)")
            return {'RUNNING_MODAL'}
        elif event.value == 'RELEASE':
            state.custom_profile_moving = False
            state.custom_profile_transform_start_pos = None
            context.area.tag_redraw()
            return {'RUNNING_MODAL'}
    
    # Handle clearing profile (Backspace key)
    if event.type == 'BACK_SPACE' and event.value == 'PRESS':
        screen_points.clear()
        state._custom_profile_data['screen_points'] = screen_points
        operator.report({'INFO'}, "Profile cleared")
        _update_mesh_from_profile_edit(operator, context, screen_points)
        context.area.tag_redraw()
        return {'RUNNING_MODAL'}
    
    # Handle symmetry toggle (X key) - block from main handler
    if event.type == 'X' and event.value == 'PRESS':
        state.custom_profile_symmetry = not state.custom_profile_symmetry
        if state.custom_profile_symmetry:
            # Lock the symmetry center when enabling
            if len(screen_points) >= 1:
                center = _get_profile_center(screen_points)
                state.custom_profile_symmetry_center = center
                angle = state.custom_profile_symmetry_angle
                
                # Extract right-side points and generate center crossing points
                new_points = _extract_right_side_with_crossings(screen_points, center, angle)
                screen_points.clear()
                screen_points.extend(new_points)
                state._custom_profile_data['screen_points'] = screen_points
                
                # Update mesh preview with symmetric profile
                full_profile = _generate_symmetric_profile(screen_points, center, angle)
                _update_mesh_from_profile_edit(operator, context, full_profile)
            else:
                # Use screen center if no points yet
                region = context.region
                state.custom_profile_symmetry_center = (region.width / 2, region.height / 2)
        else:
            # When disabling symmetry, realize mirrored points as real editable points
            if len(screen_points) >= 1 and state.custom_profile_symmetry_center:
                center = state.custom_profile_symmetry_center
                angle = state.custom_profile_symmetry_angle
                # Generate full profile with all mirrored points
                full_profile = _generate_symmetric_profile(screen_points, center, angle)
                # Replace screen_points with full realized profile
                screen_points.clear()
                screen_points.extend(full_profile)
                state._custom_profile_data['screen_points'] = screen_points
                _update_mesh_from_profile_edit(operator, context, screen_points)
            state.custom_profile_symmetry_center = None
        status = "ON" if state.custom_profile_symmetry else "OFF"
        operator.report({'INFO'}, f"Profile symmetry: {status}")
        context.area.tag_redraw()
        return {'RUNNING_MODAL'}
    
    # Mouse move for dragging, hover, and transforms
    if event.type == 'MOUSEMOVE':
        # Update last_mouse_pos so cursor HUD follows the cursor
        state.last_mouse_pos = mouse_pos
        
        # Handle scaling while S is held
        if state.custom_profile_scaling and state.custom_profile_transform_start_pos and len(screen_points) >= 2:
            start_pos = state.custom_profile_transform_start_pos
            dx = mouse_pos[0] - start_pos[0]
            dy = mouse_pos[1] - start_pos[1]
            scale_factor = 1.0 + (dx + dy) * 0.005
            scale_factor = max(0.1, min(5.0, scale_factor))
            
            # In symmetry mode, scale from the symmetry line (center point on axis)
            if getattr(state, 'custom_profile_symmetry', False) and state.custom_profile_symmetry_center:
                sym_center = state.custom_profile_symmetry_center
                angle = state.custom_profile_symmetry_angle
                new_points = []
                for pt in screen_points:
                    if _is_point_on_axis(pt, sym_center, angle):
                        # Center points scale along axis only (distance from sym_center along axis)
                        # Project to get position along axis, then scale that
                        projected = _project_point_to_axis(pt, sym_center, angle)
                        dx_axis = projected[0] - sym_center[0]
                        dy_axis = projected[1] - sym_center[1]
                        new_pos = (sym_center[0] + dx_axis * scale_factor,
                                   sym_center[1] + dy_axis * scale_factor)
                        # Keep on axis
                        new_points.append(_project_point_to_axis(new_pos, sym_center, angle))
                    else:
                        # Scale distance from symmetry center
                        dx_pt = pt[0] - sym_center[0]
                        dy_pt = pt[1] - sym_center[1]
                        new_points.append((sym_center[0] + dx_pt * scale_factor, 
                                          sym_center[1] + dy_pt * scale_factor))
            else:
                new_points = _scale_profile_points(screen_points, scale_factor)
            
            state._custom_profile_data['screen_points'] = new_points
            state.custom_profile_transform_start_pos = mouse_pos
            _update_mesh_from_profile_edit(operator, context, new_points)
            context.area.tag_redraw()
            return {'RUNNING_MODAL'}
        
        # Handle moving while G is held
        if state.custom_profile_moving and state.custom_profile_transform_start_pos and len(screen_points) >= 1:
            start_pos = state.custom_profile_transform_start_pos
            offset = (mouse_pos[0] - start_pos[0], mouse_pos[1] - start_pos[1])
            
            # In symmetry mode, center points move along axis only
            if getattr(state, 'custom_profile_symmetry', False) and state.custom_profile_symmetry_center:
                sym_center = state.custom_profile_symmetry_center
                angle = state.custom_profile_symmetry_angle
                new_points = []
                for pt in screen_points:
                    if _is_point_on_axis(pt, sym_center, angle):
                        # Center points move along axis only - project the offset onto the axis
                        moved_pt = (pt[0] + offset[0], pt[1] + offset[1])
                        new_points.append(_project_point_to_axis(moved_pt, sym_center, angle))
                    else:
                        # Move right-side points freely
                        new_points.append((pt[0] + offset[0], pt[1] + offset[1]))
            else:
                new_points = _move_profile_points(screen_points, offset)
            
            state._custom_profile_data['screen_points'] = new_points
            state.custom_profile_transform_start_pos = mouse_pos
            _update_mesh_from_profile_edit(operator, context, new_points)
            context.area.tag_redraw()
            return {'RUNNING_MODAL'}
        
        # Handle point dragging
        if state.custom_profile_active_index >= 0 and state.custom_profile_active_index < len(screen_points):
            # In symmetry mode, constrain movement
            if getattr(state, 'custom_profile_symmetry', False):
                center = state.custom_profile_symmetry_center
                angle = state.custom_profile_symmetry_angle
                current_pt = screen_points[state.custom_profile_active_index]
                
                # Check if this point is on the axis (center point)
                if center and _is_point_on_axis(current_pt, center, angle):
                    # Center point - lock to axis, only allow movement along it
                    new_pos = _project_point_to_axis(mouse_pos, center, angle)
                    screen_points[state.custom_profile_active_index] = new_pos
                    full_profile = _generate_symmetric_profile(screen_points, center, angle)
                    _update_mesh_from_profile_edit(operator, context, full_profile)
                elif center and _is_point_on_right_side(mouse_pos, center, angle):
                    # Right-side point - allow free movement on right side
                    screen_points[state.custom_profile_active_index] = mouse_pos
                    full_profile = _generate_symmetric_profile(screen_points, center, angle)
                    _update_mesh_from_profile_edit(operator, context, full_profile)
                # Else: trying to drag to left side - don't move
            else:
                screen_points[state.custom_profile_active_index] = mouse_pos
                _update_mesh_from_profile_edit(operator, context, screen_points)
            context.area.tag_redraw()
            return {'RUNNING_MODAL'}
        
        # Update hover state
        state.custom_profile_hover_index = _find_closest_custom_profile_point(mouse_pos, screen_points, threshold=15.0)
        if state.custom_profile_hover_index < 0:
            edge_idx, edge_pt = _find_closest_custom_profile_edge(mouse_pos, screen_points, threshold=10.0)
            state.custom_profile_hover_edge = edge_idx
            state.custom_profile_hover_edge_point = edge_pt
        else:
            state.custom_profile_hover_edge = -1
            state.custom_profile_hover_edge_point = None
        
        context.area.tag_redraw()
        return {'RUNNING_MODAL'}
    
    # Enter to confirm profile
    if event.type in {'RET', 'NUMPAD_ENTER'} and event.value == 'PRESS':
        # In symmetry mode, need fewer right-side points since we double them
        min_points = 2 if getattr(state, 'custom_profile_symmetry', False) else 3
        
        if len(screen_points) >= min_points:
            # In symmetry mode, generate full profile from right-side points
            if getattr(state, 'custom_profile_symmetry', False):
                center = state.custom_profile_symmetry_center
                angle = state.custom_profile_symmetry_angle
                full_profile = _generate_symmetric_profile(screen_points, center, angle)
                normalized_points = _normalize_screen_points_to_profile(full_profile)
            else:
                normalized_points = _normalize_screen_points_to_profile(screen_points)
            
            state.custom_profile_points = normalized_points
            state.custom_profile_curve_name = "Drawn"
            state.profile_global_type = state.PROFILE_CUSTOM
            n_pts = len(normalized_points)
            operator.resolution = n_pts
            
            # Save to the active slot
            slot_index = getattr(state, 'active_custom_profile_slot', 0)
            if slot_index < len(state.custom_profile_slots):
                state.custom_profile_slots[slot_index] = list(normalized_points)
                # Also save symmetry state for this slot
                state.custom_profile_slot_symmetry[slot_index] = getattr(state, 'custom_profile_symmetry', False)
            slot_num = slot_index + 4
            
            # Persist to scene data
            save_custom_profiles_to_scene()
            
            operator.report({'INFO'}, f"Custom profile {slot_num} saved ({n_pts} points)")
            
            state.save_history_state()
            if len(state.points_3d) >= 2 and len(state.point_radii_3d) >= 2:
                mesh_utils.update_preview_mesh(context, state.points_3d, state.point_radii_3d, 
                                              resolution=operator.resolution, segments=operator.segments)
        else:
            operator.report({'WARNING'}, f"Need at least {min_points} points for a profile")
        
        # Set lockout if G was being used to prevent group move trigger
        if state.custom_profile_moving:
            state._profile_exit_g_lockout = True
        
        # Clear backup (changes accepted) and exit draw mode
        state._custom_profile_backup = None
        state.custom_profile_draw_mode = False
        state._custom_profile_data['screen_points'] = []
        state.custom_profile_hover_index = -1
        state.custom_profile_active_index = -1
        state.custom_profile_hover_edge = -1
        state.custom_profile_hover_edge_point = None
        state.custom_profile_scaling = False
        state.custom_profile_rotating = False
        state.custom_profile_moving = False
        state.custom_profile_transform_start_pos = None
        state.custom_profile_symmetry = False
        state.custom_profile_symmetry_angle = 0.0
        state.custom_profile_symmetry_center = None
        state.custom_profile_point_pairs = {}
        context.area.tag_redraw()
        return {'RUNNING_MODAL'}
    
    return None


def handle_enter(operator, context):
    """Handle Enter key to finish and create flex mesh"""
    operator.finish(context)
    return {'FINISHED'}


def handle_accept_and_continue(operator, context):
    """Handle Space key to accept current mesh and continue creating another"""
    if len(state.points_3d) >= 2 and len(state.point_radii_3d) >= 2:
        # Finalize without cleanup to keep drawing handler active
        operator._finalize(context, do_cleanup=False)
        
        # Remove the preview mesh but keep the drawing handler
        state.cleanup_preview_mesh()
        
        # Force view layer update to ensure depsgraph is consistent
        context.view_layer.update()
        
        # Reset state for new curve while keeping is_running and draw_handle
        state.reset_for_new_curve()
        
        # Also reset original modifiers since we're starting fresh
        state.original_modifiers = []
        state.object_matrix_world = None
        
        # Reinitialize construction plane and depth for the next curve from current camera
        try:
            region = context.region
            rv3d = context.region_data
            depth_reference_world_point = None
            if context.active_object and context.active_object.type == 'MESH':
                if not (state.preview_mesh_obj and context.active_object == state.preview_mesh_obj):
                    depth_reference_world_point = context.active_object.matrix_world.translation.copy()
            if depth_reference_world_point is None:
                depth_reference_world_point = context.scene.cursor.location.copy()

            if rv3d:
                world_view_direction = (rv3d.view_matrix.inverted().to_3x3() @ Vector((0, 0, -1))).normalized()
                state.construction_plane_origin = depth_reference_world_point
                state.construction_plane_normal = world_view_direction

                # Compute current_depth along center view ray
                ray_origin_world = view3d_utils.region_2d_to_origin_3d(region, rv3d, (region.width / 2, region.height / 2))
                view_vector_center_world = view3d_utils.region_2d_to_vector_3d(region, rv3d, (region.width / 2, region.height / 2)).normalized()
                depth_val = (depth_reference_world_point - ray_origin_world).dot(view_vector_center_world)
                state.current_depth = depth_val if depth_val > 0.1 else 10.0
                # Store camera matrix for movement detection
                if context.space_data.region_3d:
                    state.last_camera_matrix = context.space_data.region_3d.view_matrix.copy()
            else:
                state.construction_plane_origin = None
                state.construction_plane_normal = None
                state.current_depth = 10.0
        except Exception:
            pass
        
        operator.report({'INFO'}, "Flex mesh created. Continue creating new curve.")
    else:
        operator.report({'WARNING'}, "Need at least 2 points to create a flex mesh")
    
    context.area.tag_redraw()
    return {'RUNNING_MODAL'}


def switch_target_flex(operator, context, event):
    """Accept current flex and switch to editing the flex mesh under the cursor.
    
    Behaves like accept-and-continue for the current flex, then immediately
    starts an edit session for another valid flex mesh hovered under Alt+Q.
    Only proceeds if there is a valid flex mesh under the cursor.
    """
    region = context.region
    rv3d = context.region_data
    if not rv3d:
        return {'RUNNING_MODAL'}

    mouse_pos = (event.mouse_region_x, event.mouse_region_y)

    try:
        origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, mouse_pos)
        direction = view3d_utils.region_2d_to_vector_3d(region, rv3d, mouse_pos).normalized()
    except Exception:
        return {'RUNNING_MODAL'}

    # First check if there's a valid flex mesh under the cursor BEFORE accepting current
    depsgraph = context.evaluated_depsgraph_get()
    hit, loc, normal, face_index, obj, matrix, *_rest = context.scene.ray_cast(
        depsgraph, origin, direction, distance=1.0e10
    )

    if not hit or obj is None:
        operator.report({'INFO'}, "No flex mesh under cursor to switch to")
        return {'RUNNING_MODAL'}

    # Check for flex curve data
    if "flex_curve_data" not in obj:
        operator.report({'INFO'}, "Hovered object is not a Flex mesh")
        return {'RUNNING_MODAL'}

    flex_obj = obj
    
    # Valid flex mesh found - now accept and continue the current curve
    try:
        handle_accept_and_continue(operator, context)
    except Exception as e:
        operator.report({'WARNING'}, f"Failed to accept current flex before switch: {e}")

    # Delete the original hidden flex that was being edited
    original_name = getattr(operator, '_original_muscle_obj_name', None)
    if original_name and original_name in bpy.data.objects:
        try:
            orig_obj = bpy.data.objects[original_name]
            # Clear material slots before deletion to avoid stale material references
            orig_obj.data.materials.clear()
            orig_obj.hide_viewport = False
            orig_obj.hide_set(False)
            for collection in orig_obj.users_collection:
                collection.objects.unlink(orig_obj)
            bpy.data.objects.remove(orig_obj)
        except Exception as e:
            print(f"[switch_target_flex] Failed to delete original flex: {e}")
    
    # Force view layer update after object deletion to ensure depsgraph is consistent
    context.view_layer.update()

    # Initialize state for editing the new target flex
    state.initialize()
    load_custom_profiles_from_scene()
    state.is_running = True

    state.object_matrix_world = flex_obj.matrix_world.copy()
    try:
        state.edited_object_name = flex_obj.name
    except Exception:
        state.edited_object_name = None

    # Set mirror mode based on whether this flex has a mirror modifier
    state.mirror_mode_active = False
    state.mirror_flip_x = False
    for mod in flex_obj.modifiers:
        if mod.name in ("Flex_Mirror", "SculptKit_Mirror") and mod.type == 'MIRROR':
            state.mirror_mode_active = True
            state.mirror_flip_x = mod.use_bisect_flip_axis[0]
            break

    # Load curve data from metadata
    curve_data_json = flex_obj.get("flex_curve_data")
    curve_data = None
    if curve_data_json:
        try:
            curve_data = json.loads(curve_data_json)
        except Exception as e:
            print(f"[switch_target_flex] Failed to parse curve data JSON: {e}")
            curve_data = None

    if isinstance(curve_data, dict):
        loaded_adapt = curve_data.get("adaptive_segmentation", None)
        if loaded_adapt is not None:
            state.adaptive_segmentation = bool(loaded_adapt)
        if "bspline_mode" in curve_data:
            state.bspline_mode = bool(curve_data.get("bspline_mode", False))

    # Capture original modifiers for this target
    state.original_modifiers = []
    for mod in flex_obj.modifiers:
        mod_data = {
            'name': mod.name,
            'type': mod.type,
            'properties': {},
            'object_references': {},
            'node_group': None
        }
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
                except Exception:
                    pass
        state.original_modifiers.append(mod_data)

    # Preserve hierarchy information
    operator._original_muscle_obj_name = flex_obj.name
    operator._original_world_matrix = flex_obj.matrix_world.copy()
    operator._original_parent = flex_obj.parent
    operator._original_parent_type = flex_obj.parent_type
    operator._original_parent_bone = flex_obj.parent_bone if flex_obj.parent_type == 'BONE' else ''
    operator._original_matrix_parent_inverse = flex_obj.matrix_parent_inverse.copy()
    operator._original_collections = [collection.name for collection in flex_obj.users_collection]
    
    # Store original material
    operator._original_material = None
    if len(flex_obj.data.materials) > 0 and flex_obj.data.materials[0]:
        operator._original_material = flex_obj.data.materials[0]
    
    # Store original shade smooth state
    operator._original_shade_smooth = False
    if flex_obj.data.polygons:
        operator._original_shade_smooth = flex_obj.data.polygons[0].use_smooth
    
    operator._original_children = []
    for child in flex_obj.children:
        operator._original_children.append({
            'name': child.name,
            'parent_type': child.parent_type,
            'parent_bone': child.parent_bone if child.parent_type == 'BONE' else '',
            'matrix_world': child.matrix_world.copy(),
            'matrix_parent_inverse': child.matrix_parent_inverse.copy(),
        })
    
    # Unparent children using data-API to avoid context issues
    for child_data in operator._original_children:
        child = bpy.data.objects.get(child_data['name'])
        if child:
            child_world = child.matrix_world.copy()
            child.parent = None
            try:
                child.parent_type = 'OBJECT'
            except TypeError:
                pass
            child.parent_bone = ""
            child.matrix_parent_inverse = Matrix.Identity(4)
            child.matrix_world = child_world

    # Load curve data from the flex object
    if not curve_data_json:
        operator.report({'ERROR'}, "No curve data found on the selected flex mesh")
        return {'RUNNING_MODAL'}

    try:
        curve_data = json.loads(curve_data_json)

        # Load points
        state.points_3d = []
        if "curve_points" in curve_data:
            for point_data in curve_data["curve_points"]:
                point = Vector((point_data["x"], point_data["y"], point_data["z"]))
                state.points_3d.append(point)

        # Load radii
        state.point_radii_3d = curve_data.get("radii", [])

        # Load tensions
        state.point_tensions = curve_data.get("tensions", [])

        # Load no_tangent_points
        state.no_tangent_points = set(curve_data.get("no_tangent_points", []))

        # Load caps, profile, and adaptive densification
        state.start_cap_type = curve_data.get('start_cap_type', 1)
        state.end_cap_type = curve_data.get('end_cap_type', 1)
        state.profile_aspect_ratio = curve_data.get('profile_aspect_ratio', 1.0)
        state.profile_global_twist = curve_data.get('profile_global_twist', 0.0)
        state.profile_point_twists = curve_data.get('profile_point_twists', [])
        state.profile_global_type = curve_data.get('profile_global_type', state.PROFILE_CIRCULAR)
        state.profile_roundness = curve_data.get('profile_roundness', 0.3)
        state.profile_point_roundness = curve_data.get('profile_point_roundness', [])
        
        # Load custom profile data if present
        loaded_custom_points = curve_data.get('custom_profile_points', [])
        if loaded_custom_points:
            state.custom_profile_points = [tuple(p) for p in loaded_custom_points]
        state.adaptive_segmentation = curve_data.get('adaptive_segmentation', False)
        
        if "bspline_mode" in curve_data:
            state.bspline_mode = bool(curve_data.get("bspline_mode", False))

        while len(state.profile_point_twists) < len(state.points_3d):
            state.profile_point_twists.append(0.0)

        # Load resolution and segments
        if "resolution" in curve_data:
            operator.resolution = curve_data["resolution"]
        if "segments" in curve_data:
            operator.segments = curve_data["segments"]

        # Convert to object space if data was stored in world space
        if not curve_data.get("in_object_space", True):
            matrix_world_inv = flex_obj.matrix_world.inverted_safe()
            for i, point in enumerate(state.points_3d):
                state.points_3d[i] = matrix_world_inv @ point

        state.object_matrix_world = flex_obj.matrix_world.copy()
        
        # Reinitialize construction plane/depth using current view and curve ends
        try:
            rv3d_local = context.region_data
            region_local = context.region
            if rv3d_local:
                view_inv = rv3d_local.view_matrix.inverted()
                view_dir = (view_inv.to_3x3() @ Vector((0.0, 0.0, -1.0))).normalized()
                cam_loc = view_inv.translation
                center_xy = (region_local.width / 2, region_local.height / 2)
                
                ref_world = flex_obj.matrix_world.translation.copy()
                if len(state.points_3d) > 0:
                    start_world = state.points_3d[0]
                    end_world = state.points_3d[-1]
                    if state.object_matrix_world:
                        start_world = state.object_matrix_world @ start_world
                        end_world = state.object_matrix_world @ end_world
                    start_2d = conversion.get_2d_from_3d(context, start_world, is_world_space=True)
                    end_2d = conversion.get_2d_from_3d(context, end_world, is_world_space=True)
                    if start_2d and end_2d:
                        ds = (Vector(center_xy) - Vector(start_2d)).length
                        de = (Vector(center_xy) - Vector(end_2d)).length
                        ref_world = start_world if ds <= de else end_world
                    elif start_2d:
                        ref_world = start_world
                    elif end_2d:
                        ref_world = end_world
                
                ray_origin_center = view3d_utils.region_2d_to_origin_3d(region_local, rv3d_local, center_xy)
                view_vec_center = view3d_utils.region_2d_to_vector_3d(region_local, rv3d_local, center_xy).normalized()
                depth_val = (ref_world - ray_origin_center).dot(view_vec_center)
                state.current_depth = depth_val if depth_val > 0.1 else 10.0
                state.construction_plane_normal = view_dir
                if rv3d_local.view_perspective != 'ORTHO':
                    state.construction_plane_origin = cam_loc + view_dir * state.current_depth
                else:
                    state.construction_plane_origin = ref_world
                if context.space_data.region_3d:
                    state.last_camera_matrix = context.space_data.region_3d.view_matrix.copy()
        except Exception:
            pass
    except Exception as e:
        operator.report({'ERROR'}, f"Failed to load curve data: {e}")
        return {'RUNNING_MODAL'}

    # Hide the new target flex while editing
    flex_obj.hide_viewport = True

    # Clear current selection
    for obj_sel in context.selected_objects:
        obj_sel.select_set(False)

    # Initialize history and preview for the new target
    state.save_history_state()
    if len(state.points_3d) >= 2 and len(state.point_radii_3d) >= 2:
        mesh_utils.update_preview_mesh(
            context,
            state.points_3d,
            state.point_radii_3d,
            resolution=operator.resolution,
            segments=operator.segments,
        )
        if state.preview_mesh_obj is not None:
            mesh_utils.update_preview_mesh(
                context,
                state.points_3d,
                state.point_radii_3d,
                resolution=operator.resolution,
                segments=operator.segments,
            )

    context.area.tag_redraw()
    operator.report({'INFO'}, f"Switched to flex: {flex_obj.name}")
    return {'RUNNING_MODAL'}


def register():
    pass


def unregister():
    pass
