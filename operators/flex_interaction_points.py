"""
Point Interaction Module for Flex tool in Super Tools addon.
Handles point creation, manipulation, radius adjustment, and deletion.
"""
import bpy
import time
import math
import json
from mathutils import Vector, Matrix
from bpy_extras import view3d_utils

from ..utils.flex_state import state
from ..utils import flex_conversion as conversion
from ..utils import flex_math as math_utils
from ..utils import flex_mesh as mesh_utils


def handle_left_mouse(operator, context, event):
    """Handle left mouse button events for point creation and manipulation"""
    mouse_pos = (event.mouse_region_x, event.mouse_region_y)
    
    if event.value == 'PRESS':
        # Check if we're in twist mode
        if state.profile_twist_mode:
            closest_index = math_utils.find_closest_point_with_screen_radius(
                context, mouse_pos, state.points_3d, state.point_radii_3d
            )
            
            if closest_index >= 0:
                # Start twisting individual point
                state.twist_dragging_point = closest_index
                if len(state.profile_point_twists) != len(state.points_3d):
                    existing = list(state.profile_point_twists) if state.profile_point_twists else []
                    needed = len(state.points_3d) - len(existing)
                    if needed > 0:
                        existing.extend([0.0] * needed)
                    state.profile_point_twists = existing[:len(state.points_3d)]
                state.twist_drag_start_mouse = (mouse_pos[0], mouse_pos[1])
                current_twist = 0.0
                if 0 <= closest_index < len(state.profile_point_twists):
                    current_twist = state.profile_point_twists[closest_index]
                state.twist_drag_start_angle = current_twist
                state.save_history_state()
                return {'RUNNING_MODAL'}
            else:
                # Start ramp twist
                state.twist_dragging_point = -3
                state.twist_drag_start_mouse = (mouse_pos[0], mouse_pos[1])
                # Store first point's twist as baseline for ramp
                first_twist = 0.0
                if state.profile_point_twists and len(state.profile_point_twists) > 0:
                    first_twist = state.profile_point_twists[0]
                state.twist_ramp_base = first_twist
                # Calculate current ramp amount (difference between last and first point)
                end_twist = 0.0
                if state.profile_point_twists and len(state.profile_point_twists) >= len(state.points_3d):
                    end_twist = state.profile_point_twists[len(state.points_3d) - 1] - first_twist
                state.twist_drag_start_angle = end_twist
                state.save_history_state()
                return {'RUNNING_MODAL'}
        
        # Check for control point interaction using 50% radius rule
        if len(state.points_3d) > 0:
            region = context.region
            rv3d = context.region_data
            active_idx = getattr(state, 'reveal_control_index', -1)
            closest_i = -1
            hit_type = None
            
            if active_idx != -1 and active_idx < len(state.points_3d) and active_idx < len(state.point_radii_3d):
                i = active_idx
                point_3d = state.points_3d[i]
                point_2d = conversion.get_2d_from_3d(context, point_3d)
                if point_2d is not None:
                    screen_radius = conversion.get_consistent_screen_radius(context, state.point_radii_3d[i], point_3d)
                    if screen_radius > 0.0:
                        dx = mouse_pos[0] - point_2d[0]
                        dy = mouse_pos[1] - point_2d[1]
                        d = math.sqrt(dx*dx + dy*dy)
                        if d <= screen_radius:
                            hit_type = 'point' if d <= 0.5 * screen_radius else 'radius'
                            closest_i = i
            else:
                # Scan all points
                closest_d = float('inf')
                for i, point_3d in enumerate(state.points_3d):
                    point_2d = conversion.get_2d_from_3d(context, point_3d)
                    if point_2d is None:
                        continue
                    screen_radius = conversion.get_consistent_screen_radius(
                        context, 
                        state.point_radii_3d[i] if i < len(state.point_radii_3d) else 0.0, 
                        point_3d
                    )
                    if screen_radius <= 0.0:
                        continue
                    dx = mouse_pos[0] - point_2d[0]
                    dy = mouse_pos[1] - point_2d[1]
                    d = math.sqrt(dx*dx + dy*dy)
                    if d <= screen_radius and d < closest_d:
                        closest_d = d
                        hit_type = 'point' if d <= 0.5 * screen_radius else 'radius'
                        closest_i = i

            if closest_i != -1:
                if hit_type == 'point':
                    # Handle double-click to toggle tangency
                    current_time = time.time()
                    if closest_i == state.last_click_point and current_time - state.last_click_time < 0.3:
                        if closest_i > 0 and closest_i < len(state.points_3d) - 1:
                            if closest_i in state.no_tangent_points:
                                state.no_tangent_points.remove(closest_i)
                            else:
                                state.no_tangent_points.add(closest_i)
                            state.save_history_state()
                            state.last_click_time = 0
                            state.last_click_point = -1
                            if len(state.points_3d) >= 2 and len(state.point_radii_3d) >= 2:
                                mesh_utils.update_preview_mesh(context, state.points_3d, state.point_radii_3d, 
                                                              resolution=operator.resolution, segments=operator.segments)
                            return {'RUNNING_MODAL'}
                    else:
                        state.last_click_time = current_time
                        state.last_click_point = closest_i
                    
                    # Start dragging this point
                    state.active_point_index = closest_i
                    if state.snapping_mode == state.SNAPPING_OFF:
                        if rv3d:
                            point_3d_world = state.points_3d[state.active_point_index]
                            if state.object_matrix_world:
                                point_3d_world = state.object_matrix_world @ point_3d_world
                            state.drag_start_world_point = point_3d_world
                            state.drag_start_depth = None
                        else:
                            state.drag_start_depth = None
                    else:
                        state.drag_start_depth = None
                        if state.snapping_mode == state.SNAPPING_FACE:
                            point_3d_world = state.points_3d[state.active_point_index]
                            if state.object_matrix_world:
                                point_3d_world = state.object_matrix_world @ point_3d_world
                            state.face_drag_ref_world = point_3d_world.copy() if hasattr(point_3d_world, 'copy') else point_3d_world
                    return {'RUNNING_MODAL'}
                    
                elif hit_type == 'radius' and active_idx != -1:
                    # Start adjusting radius
                    state.adjusting_radius_index = closest_i
                    state.save_history_state()
                    return {'RUNNING_MODAL'}
        
        # Check tension control hover (only when not in B-spline mode)
        tension_index = -1
        if (not state.bspline_mode) and state.reveal_control_index != -1 and state.reveal_control_index < len(state.points_3d) and state.reveal_control_index < len(state.point_radii_3d):
            current_tension = state.point_tensions[state.reveal_control_index] if state.reveal_control_index < len(state.point_tensions) else 0.5
            tt = math_utils.find_tension_control_hover(
                context, mouse_pos,
                [state.points_3d[state.reveal_control_index]],
                [state.point_radii_3d[state.reveal_control_index]],
                [current_tension], threshold=28
            )
            if tt == 0:
                tension_index = state.reveal_control_index
        
        if tension_index >= 0:
            state.adjusting_tension_index = tension_index
            state.reveal_control_index = tension_index
            state.save_history_state()
            point_3d = state.points_3d[tension_index]
            point_2d = conversion.get_2d_from_3d(context, point_3d)
            if point_2d is not None:
                dx = mouse_pos[0] - point_2d[0]
                dy = mouse_pos[1] - point_2d[1]
                state.tension_drag_start_angle = math.atan2(dy, dx)
                if tension_index < len(state.point_tensions):
                    state.tension_drag_start_value = state.point_tensions[tension_index]
                else:
                    state.tension_drag_start_value = 0.5
            else:
                state.tension_drag_start_angle = None
                state.tension_drag_start_value = None
            return {'RUNNING_MODAL'}
        
        # Check if clicking on curve for point insertion
        if state.hover_on_curve and state.hover_curve_point_3d is not None and state.hover_curve_segment >= 0:
            state.save_history_state()
            new_point_3d = state.hover_curve_point_3d.copy()
            closest_segment, min_dist = math_utils.find_closest_segment_to_point(state.points_3d, new_point_3d)
            
            state.points_3d.insert(closest_segment + 1, new_point_3d)
            
            if closest_segment + 1 < len(state.point_radii_3d):
                prev_r = state.point_radii_3d[closest_segment]
                next_r = state.point_radii_3d[closest_segment+1] if closest_segment+1 < len(state.point_radii_3d) else prev_r
                state.point_radii_3d.insert(closest_segment + 1, 0.5 * (prev_r + next_r))
            else:
                state.point_radii_3d.insert(closest_segment + 1, state.point_radii_3d[closest_segment] if state.point_radii_3d else state.DEFAULT_RADIUS)
            
            # Update no_tangent_points indices
            updated_no_tangent = set()
            for idx in state.no_tangent_points:
                if idx > closest_segment:
                    updated_no_tangent.add(idx + 1)
                else:
                    updated_no_tangent.add(idx)
            state.no_tangent_points = updated_no_tangent
            
            # Update twist arrays
            if len(state.profile_point_twists) == len(state.points_3d) - 1:
                if closest_segment < len(state.profile_point_twists):
                    prev_twist = state.profile_point_twists[closest_segment]
                    next_twist = state.profile_point_twists[closest_segment] if closest_segment + 1 >= len(state.profile_point_twists) else state.profile_point_twists[closest_segment + 1]
                    state.profile_point_twists.insert(closest_segment + 1, (prev_twist + next_twist) * 0.5)
                else:
                    state.profile_point_twists.insert(closest_segment + 1, 0.0)
            
            state.creating_point_index = closest_segment + 1
            state.creating_point_start_pos = new_point_3d.copy()
        else:
            # Add new point to closest end
            state.save_history_state()
            new_point_3d = operator._get_new_point_3d(context, mouse_pos)
            
            if new_point_3d is None:
                return {'PASS_THROUGH'}
            
            if len(state.points_3d) == 0:
                operator._add_first_point(new_point_3d)
            else:
                operator._add_point_to_closest_end(context, mouse_pos, new_point_3d)
        
        # Update preview mesh
        if len(state.points_3d) >= 2 and len(state.point_radii_3d) >= 2:
            mesh_utils.update_preview_mesh(context, state.points_3d, state.point_radii_3d, 
                                          resolution=operator.resolution, segments=operator.segments)
        
        return {'RUNNING_MODAL'}
    
    elif event.value == 'RELEASE':
        if state.active_point_index >= 0:
            state.save_history_state()
            state.active_point_index = -1
            state.drag_start_depth = None
        
        if state.adjusting_radius_index >= 0:
            state.save_history_state()
            state.adjusting_radius_index = -1
        
        if state.adjusting_tension_index >= 0:
            state.save_history_state()
            state.adjusting_tension_index = -1
        
        if state.creating_point_index >= 0:
            state.creating_point_index = -1
            state.creating_point_start_pos = None
            state.creating_point_threshold_crossed = False
        
        if state.twist_dragging_point != -2:
            state.save_history_state()
            state.twist_dragging_point = -2
            state.twist_drag_start_angle = None
            state.twist_drag_start_mouse = None
        
        state.face_drag_ref_world = None
        
        if getattr(state, 'mirror_mode_active', False) and state.preview_mesh_obj is not None:
            mesh_utils.update_mirror_flip_from_points(state.preview_mesh_obj, state.points_3d)
        
        return {'RUNNING_MODAL'}
    
    return {'RUNNING_MODAL'}


def handle_right_mouse(operator, context, event):
    """Handle right mouse button for deletion and radius scaling"""
    mouse_pos = (event.mouse_region_x, event.mouse_region_y)
    
    if event.value != 'PRESS':
        # Handle release of radius scale mode
        if event.value == 'RELEASE':
            if getattr(state, 'radius_scale_active', False):
                state.radius_scale_active = False
                state.radius_scale_start_mouse = None
                state.radius_scale_original_radii = None
                state.save_history_state()
            if getattr(state, 'radius_ramp_active', False):
                state.radius_ramp_active = False
                state.radius_ramp_original_radii = None
            # Reset ramp amounts and equalize on RMB release
            state.radius_ramp_amount = 0.0
            if hasattr(state, 'radius_equalize_active'):
                state.radius_equalize_active = False
            if hasattr(state, 'twist_ramp_amount'):
                state.twist_ramp_amount = 0.0
            if hasattr(state, 'twist_ramp_base'):
                state.twist_ramp_base = 0.0
            if getattr(state, 'twist_scale_active', False):
                state.twist_scale_active = False
                state.twist_dragging_point = -2
                state.twist_drag_start_mouse = None
                state.twist_drag_start_angle = None
                state.save_history_state()
        return {'RUNNING_MODAL'}
    
    # In twist mode, RMB in empty space starts global twist drag
    if state.profile_twist_mode and state.hover_point_index < 0 and len(state.points_3d) >= 2:
        state.twist_scale_active = True
        state.twist_dragging_point = -1
        state.twist_drag_start_mouse = mouse_pos
        state.twist_drag_start_angle = state.profile_global_twist
        state.save_history_state()
        return {'RUNNING_MODAL'}
    
    # Check if hovering over a point to delete
    if state.hover_point_index >= 0:
        if len(state.points_3d) <= 2:
            operator.report({'WARNING'}, "Cannot delete point: minimum 2 points required")
            return {'RUNNING_MODAL'}
        
        state.save_history_state()
        delete_index = state.hover_point_index
        
        state.points_3d.pop(delete_index)
        if delete_index < len(state.point_radii_3d):
            state.point_radii_3d.pop(delete_index)
        if delete_index < len(state.point_tensions):
            state.point_tensions.pop(delete_index)
        if hasattr(state, 'profile_point_twists') and delete_index < len(state.profile_point_twists):
            state.profile_point_twists.pop(delete_index)
        
        updated_no_tangent = set()
        for idx in state.no_tangent_points:
            if idx == delete_index:
                pass
            elif idx > delete_index:
                updated_no_tangent.add(idx - 1)
            else:
                updated_no_tangent.add(idx)
        state.no_tangent_points = updated_no_tangent
        
        state.hover_point_index = -1
        
        if len(state.points_3d) >= 2 and len(state.point_radii_3d) >= 2:
            mesh_utils.update_preview_mesh(context, state.points_3d, state.point_radii_3d, 
                                          resolution=operator.resolution, segments=operator.segments)
        
        if getattr(state, 'mirror_mode_active', False) and state.preview_mesh_obj is not None:
            mesh_utils.update_mirror_flip_from_points(state.preview_mesh_obj, state.points_3d)
        
        operator.report({'INFO'}, f"Deleted point {delete_index}")
        return {'RUNNING_MODAL'}
    
    # No point under cursor: start radius scale mode
    if not state.profile_twist_mode and len(state.points_3d) >= 2 and len(state.point_radii_3d) >= 2:
        state.last_mouse_pos = mouse_pos
        state.save_history_state()
        state.radius_scale_active = True
        state.radius_scale_start_mouse = mouse_pos
        state.radius_scale_original_radii = list(state.point_radii_3d)
        context.area.tag_redraw()
        return {'RUNNING_MODAL'}
    
    return {'PASS_THROUGH'}


def handle_mouse_move(operator, context, event):
    """Handle mouse movement for dragging, adjusting, and hovering"""
    mouse_pos = (event.mouse_region_x, event.mouse_region_y)
    state.last_mouse_pos = mouse_pos
    
    # Handle group move (move all points together in screen space)
    if state.group_move_active and state.group_move_start_mouse_pos is not None:
        region = context.region
        rv3d = context.region_data
        if not rv3d:
            return {'RUNNING_MODAL'}

        start_mx, start_my = state.group_move_start_mouse_pos
        start_mouse = (start_mx, start_my)

        # Use the stored world-space center as depth reference for screen-space move
        center_world = state.group_move_start_point
        if center_world is None:
            return {'RUNNING_MODAL'}

        # Map start and current mouse positions to world space at the same depth
        start_world = view3d_utils.region_2d_to_location_3d(region, rv3d, start_mouse, center_world)
        current_world = view3d_utils.region_2d_to_location_3d(region, rv3d, mouse_pos, center_world)
        offset_world = current_world - start_world

        # Apply offset to all original positions
        new_points = []
        for orig in state.group_move_original_positions:
            pw = state.object_matrix_world @ orig if state.object_matrix_world else orig
            pw_new = pw + offset_world
            if state.object_matrix_world:
                new_points.append(state.object_matrix_world.inverted() @ pw_new)
            else:
                new_points.append(pw_new)

        if len(new_points) == len(state.points_3d):
            state.points_3d = new_points
            if len(state.points_3d) >= 2 and len(state.point_radii_3d) >= 2:
                mesh_utils.update_preview_mesh(
                    context,
                    state.points_3d,
                    state.point_radii_3d,
                    resolution=operator.resolution,
                    segments=operator.segments,
                )
            context.area.tag_redraw()
        return {'RUNNING_MODAL'}
    
    # Handle radius scale mode (RMB drag)
    # If radius ramp or equalize is active, ignore drag-based uniform scaling
    if (
        getattr(state, 'radius_scale_active', False)
        and not getattr(state, 'radius_ramp_active', False)
        and not getattr(state, 'radius_equalize_active', False)
        and state.radius_scale_start_mouse is not None
    ):
        start_x, start_y = state.radius_scale_start_mouse
        dx = mouse_pos[0] - start_x
        dy = mouse_pos[1] - start_y
        combined_delta = (dx + dy) * 0.5
        scale_factor = max(0.1, min(4.0, 1.0 + combined_delta / 300.0))
        original = state.radius_scale_original_radii or list(state.point_radii_3d)
        
        for i, r0 in enumerate(original):
            new_r = max(state.MIN_RADIUS, min(r0 * scale_factor, state.MAX_RADIUS))
            if i < len(state.point_radii_3d):
                state.point_radii_3d[i] = new_r
        
        if len(state.points_3d) >= 2 and len(state.point_radii_3d) >= 2:
            mesh_utils.update_preview_mesh(context, state.points_3d, state.point_radii_3d,
                                          resolution=operator.resolution, segments=operator.segments)
        context.area.tag_redraw()
        return {'RUNNING_MODAL'}
    
    # Handle twist scale mode (RMB drag in twist mode)
    if getattr(state, 'twist_scale_active', False) and state.twist_drag_start_mouse is not None:
        start_x, start_y = state.twist_drag_start_mouse
        dx = mouse_pos[0] - start_x
        twist_delta = dx * 0.01
        state.profile_global_twist = state.twist_drag_start_angle + twist_delta
        
        if len(state.points_3d) >= 2 and len(state.point_radii_3d) >= 2:
            mesh_utils.update_preview_mesh(context, state.points_3d, state.point_radii_3d,
                                          resolution=operator.resolution, segments=operator.segments)
        context.area.tag_redraw()
        return {'RUNNING_MODAL'}
    
    # Handle twist dragging (individual, global, or ramp)
    if state.twist_dragging_point != -2 and state.twist_drag_start_angle is not None and state.twist_drag_start_mouse is not None:
        start_x, start_y = state.twist_drag_start_mouse
        dx = mouse_pos[0] - start_x
        dy = mouse_pos[1] - start_y
        combined_delta = (dx + dy) * 0.5
        twist_value = state.twist_drag_start_angle + (combined_delta / 300.0)
        
        if state.twist_dragging_point >= 0:
            # Individual point twist
            if len(state.profile_point_twists) != len(state.points_3d):
                existing = list(state.profile_point_twists) if state.profile_point_twists else []
                needed = len(state.points_3d) - len(existing)
                if needed > 0:
                    existing.extend([0.0] * needed)
                state.profile_point_twists = existing[:len(state.points_3d)]
            state.profile_point_twists[state.twist_dragging_point] = twist_value
        elif state.twist_dragging_point == -1:
            # Global twist
            state.profile_global_twist = twist_value
        elif state.twist_dragging_point == -3:
            # Ramp twist - preserve first point's twist and ramp from there
            if len(state.points_3d) >= 2:
                count = len(state.points_3d)
                existing = list(state.profile_point_twists) if state.profile_point_twists else []
                if len(existing) != count:
                    needed = count - len(existing)
                    if needed > 0:
                        existing.extend([0.0] * needed)
                    state.profile_point_twists = existing[:count]
                base_twist = getattr(state, 'twist_ramp_base', 0.0)
                for idx in range(count):
                    t = idx / (count - 1) if count > 1 else 0
                    state.profile_point_twists[idx] = base_twist + (twist_value * t)
        
        if len(state.points_3d) >= 2 and len(state.point_radii_3d) >= 2:
            mesh_utils.update_preview_mesh(context, state.points_3d, state.point_radii_3d, 
                                          resolution=operator.resolution, segments=operator.segments)
        context.area.tag_redraw()
        return {'RUNNING_MODAL'}
    
    # Handle point dragging
    if state.active_point_index >= 0:
        new_point_3d = _get_dragged_point(operator, context, mouse_pos)
        if new_point_3d is not None:
            state.points_3d[state.active_point_index] = new_point_3d
            if len(state.points_3d) >= 2 and len(state.point_radii_3d) >= 2:
                mesh_utils.update_preview_mesh(context, state.points_3d, state.point_radii_3d, 
                                              resolution=operator.resolution, segments=operator.segments)
        context.area.tag_redraw()
        return {'RUNNING_MODAL'}
    
    # Handle radius adjustment
    if state.adjusting_radius_index >= 0 and state.adjusting_radius_index < len(state.points_3d):
        point_3d = state.points_3d[state.adjusting_radius_index]
        point_2d = conversion.get_2d_from_3d(context, point_3d)
        
        if point_2d is not None:
            distance_2d = math.sqrt((mouse_pos[0] - point_2d[0])**2 + (mouse_pos[1] - point_2d[1])**2)
            distance_3d = conversion.get_world_distance(context, distance_2d, point_3d)
            clamped = max(state.MIN_RADIUS, min(distance_3d, state.MAX_RADIUS))
            state.point_radii_3d[state.adjusting_radius_index] = clamped
            
            if len(state.points_3d) >= 2 and len(state.point_radii_3d) >= 2:
                mesh_utils.update_preview_mesh(context, state.points_3d, state.point_radii_3d, 
                                              resolution=operator.resolution, segments=operator.segments)
        context.area.tag_redraw()
        return {'RUNNING_MODAL'}
    
    # Handle tension adjustment
    if state.adjusting_tension_index >= 0 and state.adjusting_tension_index < len(state.points_3d):
        if state.adjusting_tension_index >= len(state.point_tensions):
            while len(state.point_tensions) <= state.adjusting_tension_index:
                state.point_tensions.append(0.5)
        
        point_3d = state.points_3d[state.adjusting_tension_index]
        point_2d = conversion.get_2d_from_3d(context, point_3d)
        
        if point_2d is not None and state.tension_drag_start_angle is not None:
            dx = mouse_pos[0] - point_2d[0]
            dy = mouse_pos[1] - point_2d[1]
            angle = math.atan2(dy, dx)
            if angle < 0.0:
                angle += 2.0 * math.pi
            margin = math.radians(18.0)
            angle_span = max(1e-4, 2.0 * math.pi - 2.0 * margin)
            clamped_angle = min(2.0 * math.pi - margin, max(margin, angle))
            new_tension = (clamped_angle - margin) / angle_span
            state.point_tensions[state.adjusting_tension_index] = new_tension
            
            if len(state.points_3d) >= 2 and len(state.point_radii_3d) >= 2:
                mesh_utils.update_preview_mesh(context, state.points_3d, state.point_radii_3d, 
                                              resolution=operator.resolution, segments=operator.segments)
        context.area.tag_redraw()
        return {'RUNNING_MODAL'}
    
    # Handle creating point radius adjustment
    if state.creating_point_index >= 0 and state.creating_point_start_pos is not None:
        point_3d = state.creating_point_start_pos
        point_2d = conversion.get_2d_from_3d(context, point_3d)
        
        if point_2d is not None:
            distance_2d = math.sqrt((mouse_pos[0] - point_2d[0])**2 + (mouse_pos[1] - point_2d[1])**2)
            # Resolution-independent threshold: ~7% of region height (300px at 4K ~2160px height)
            region_height = context.region.height if context.region else 2160
            min_drag_pixels = region_height * 0.14
            
            # Once threshold is crossed, ignore it for subsequent adjustments
            if state.creating_point_threshold_crossed or distance_2d >= min_drag_pixels:
                if not state.creating_point_threshold_crossed:
                    state.creating_point_threshold_crossed = True
                
                distance_3d = conversion.get_world_distance(context, distance_2d, point_3d)
                clamped = max(state.MIN_RADIUS, min(distance_3d, state.MAX_RADIUS))
                if state.creating_point_index < len(state.point_radii_3d):
                    state.point_radii_3d[state.creating_point_index] = clamped
                
                if len(state.points_3d) >= 2 and len(state.point_radii_3d) >= 2:
                    mesh_utils.update_preview_mesh(context, state.points_3d, state.point_radii_3d, 
                                                  resolution=operator.resolution, segments=operator.segments)
        context.area.tag_redraw()
        return {'RUNNING_MODAL'}
    
    # Update hover states
    _update_hover_states(context, mouse_pos)
    context.area.tag_redraw()
    return {'RUNNING_MODAL'}


def _get_dragged_point(operator, context, mouse_pos):
    """Get the new position for a dragged point with proper depth handling"""
    region = context.region
    rv3d = context.region_data
    
    if not rv3d:
        return state.points_3d[state.active_point_index]
    
    new_point_3d = None
    
    # Screen-space drag if snapping is OFF and drag_start_world_point is set
    if state.snapping_mode == state.SNAPPING_OFF and state.drag_start_world_point is not None:
        world_point_on_plane = view3d_utils.region_2d_to_location_3d(region, rv3d, mouse_pos, state.drag_start_world_point)
        if state.object_matrix_world:
            new_point_3d = state.object_matrix_world.inverted() @ world_point_on_plane
        else:
            new_point_3d = world_point_on_plane
        return new_point_3d
    
    # Face projection
    if state.snapping_mode == state.SNAPPING_FACE:
        attempted_point = conversion.get_3d_from_mouse(context, mouse_pos, require_face_hit=True)
        if attempted_point:
            if state.object_matrix_world:
                try:
                    state.face_drag_ref_world = state.object_matrix_world @ attempted_point
                except Exception:
                    state.face_drag_ref_world = None
            else:
                state.face_drag_ref_world = attempted_point.copy() if hasattr(attempted_point, 'copy') else attempted_point
            return attempted_point
        else:
            # Maintain depth on miss
            if state.face_drag_ref_world is None:
                current_world = state.points_3d[state.active_point_index]
                if state.object_matrix_world:
                    current_world = state.object_matrix_world @ current_world
                state.face_drag_ref_world = current_world.copy() if hasattr(current_world, 'copy') else current_world
            
            world_ray_origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, mouse_pos)
            world_ray_direction = view3d_utils.region_2d_to_vector_3d(region, rv3d, mouse_pos).normalized()
            
            if rv3d.view_perspective != 'ORTHO':
                cam_loc = rv3d.view_matrix.inverted().translation
                t = max((state.face_drag_ref_world - cam_loc).length, 0.001)
                world_point = cam_loc + world_ray_direction * t
            else:
                view_normal = (rv3d.view_rotation @ Vector((0.0, 0.0, -1.0))).normalized()
                denom = world_ray_direction.dot(view_normal)
                if abs(denom) < 1e-6:
                    denom = 1e-6 if denom >= 0 else -1e-6
                t = (state.face_drag_ref_world - world_ray_origin).dot(view_normal) / denom
                t = max(t, 0.001)
                world_point = world_ray_origin + world_ray_direction * t
            
            if state.object_matrix_world:
                new_point_3d = state.object_matrix_world.inverted() @ world_point
            else:
                new_point_3d = world_point
            return new_point_3d
    
    # Construction plane / grid snap fallback
    world_ray_origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, mouse_pos)
    world_ray_direction = view3d_utils.region_2d_to_vector_3d(region, rv3d, mouse_pos).normalized()
    
    ray_origin_for_intersect = world_ray_origin
    ray_direction_for_intersect = world_ray_direction
    
    if state.object_matrix_world:
        mat_inv = state.object_matrix_world.inverted()
        ray_origin_for_intersect = mat_inv @ world_ray_origin
        ray_direction_for_intersect = mat_inv.to_3x3() @ world_ray_direction
    
    if state.construction_plane_origin and state.construction_plane_normal:
        denom = ray_direction_for_intersect.dot(state.construction_plane_normal)
        if abs(denom) > 1e-6:
            t = (state.construction_plane_origin - ray_origin_for_intersect).dot(state.construction_plane_normal) / denom
            if t > 0:
                world_intersection = world_ray_origin + t * world_ray_direction
                
                if state.object_matrix_world:
                    new_point_3d = state.object_matrix_world.inverted() @ world_intersection
                else:
                    new_point_3d = world_intersection
                return new_point_3d
    
    # Final fallback: maintain original depth
    current_point = state.points_3d[state.active_point_index]
    world_point_orig = current_point.copy()
    if state.object_matrix_world:
        world_point_orig = state.object_matrix_world @ current_point
    
    depth = (world_point_orig - world_ray_origin).dot(world_ray_direction)
    new_point_3d = conversion.get_3d_from_mouse(context, mouse_pos, depth=depth)
    
    return new_point_3d if new_point_3d else state.points_3d[state.active_point_index]


def _update_hover_states(context, mouse_pos):
    """Update hover states for points, radius, tension, and curve"""
    # Default hover detection
    state.hover_point_index = math_utils.find_closest_point_with_screen_radius(
        context, mouse_pos, state.points_3d, state.point_radii_3d
    )
    state.hover_radius_index = -1
    state.hover_tension_index = -1
    
    active_idx = getattr(state, 'reveal_control_index', -1)
    inside_active_envelope = False
    
    if active_idx != -1 and active_idx < len(state.points_3d) and active_idx < len(state.point_radii_3d):
        center_2d = conversion.get_2d_from_3d(context, state.points_3d[active_idx])
        if center_2d is not None:
            screen_radius = conversion.get_consistent_screen_radius(context, state.point_radii_3d[active_idx], state.points_3d[active_idx])
            handle_offset_px = 20.0
            handle_visual_radius = 14.0
            envelope_radius = screen_radius + handle_offset_px + handle_visual_radius
            
            dx = mouse_pos[0] - center_2d[0]
            dy = mouse_pos[1] - center_2d[1]
            dist = math.sqrt(dx*dx + dy*dy)
            
            if dist <= screen_radius:
                if dist <= 0.5 * screen_radius:
                    state.hover_point_index = active_idx
                    state.hover_radius_index = -1
                else:
                    state.hover_radius_index = active_idx
                    state.hover_point_index = -1
            
            inside_active_envelope = (dist <= envelope_radius)
            
            # Check tension hover
            if not state.bspline_mode:
                current_tension = state.point_tensions[active_idx] if active_idx < len(state.point_tensions) else 0.5
                tt = math_utils.find_tension_control_hover(
                    context, mouse_pos,
                    [state.points_3d[active_idx]],
                    [state.point_radii_3d[active_idx]],
                    [current_tension], threshold=24
                )
                state.hover_tension_index = active_idx if tt == 0 else -1
    
    # Update reveal control - when a point is hovered, always reveal its controls
    if state.hover_point_index != -1:
        state.reveal_control_index = state.hover_point_index
    else:
        if not inside_active_envelope:
            state.reveal_control_index = -1
    
    # Update curve hover
    state.hover_on_curve = False
    state.hover_curve_point_3d = None
    state.hover_curve_segment = -1
    
    if len(state.points_3d) >= 2 and not inside_active_envelope:
        hover_on_curve, hover_point_3d, hover_segment = math_utils.find_closest_point_on_curve(
            context, mouse_pos, state.points_3d, threshold=20
        )
        if hover_on_curve:
            state.hover_on_curve = True
            state.hover_curve_point_3d = hover_point_3d
            state.hover_curve_segment = hover_segment


def register():
    pass


def unregister():
    pass
