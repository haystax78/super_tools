"""
Flex Drawing Module for Super Tools addon.
This module contains functions for drawing the curve and control points in the viewport.
"""
import bpy
import blf
import gpu
from gpu_extras.batch import batch_for_shader
import math
from mathutils import Vector
import time

from ..utils.flex_state import state
from ..utils import flex_conversion as conversion
from ..utils import flex_math as math_utils


class CursorHUD:
    """
    Unified cursor HUD system for displaying tool state info near the cursor.
    """
    enabled = True
    offset_x = 20
    offset_y = 50
    line_height = 20
    font_size = 16
    global_opacity = 1.0
    
    slot_visibility = {
        'basic_input': True,
        'spacer': True,
        'bspline': True,
        'mirror': True,
        'radii_scale': True,
        'radii_ramp': True,
        'twist': True,
        'parent': True,
        'snapping': True,
        'adaptive': True,
        'profile': True,
    }
    
    slot_opacity = {
        'basic_input': 1.0,
        'spacer': 1.0,
        'bspline': 1.0,
        'mirror': 1.0,
        'radii_scale': 1.0,
        'radii_ramp': 1.0,
        'twist': 1.0,
        'parent': 1.0,
        'snapping': 1.0,
        'adaptive': 1.0,
        'profile': 1.0,
    }
    
    @classmethod
    def get_active_slots(cls):
        """Build list of active HUD slots based on current state."""
        slots = []

        twist_mode = bool(getattr(state, 'profile_twist_mode', False))
        radius_mode = bool(getattr(state, 'radius_scale_active', False))
        parent_mode = bool(getattr(state, 'parent_mode_active', False))
        profile_draw_mode = bool(getattr(state, 'custom_profile_draw_mode', False))
        
        if profile_draw_mode:
            mode_text = "Mode: Profile Draw"
            mode_color = (0.2, 0.8, 1.0)
        elif parent_mode:
            mode_text = "Mode: Parent"
            mode_color = (1.0, 0.7, 0.2)
        elif twist_mode:
            mode_text = "Mode: Twist"
            mode_color = (1.0, 0.6, 0.2)
        elif radius_mode:
            mode_text = "Mode: Radius"
            mode_color = (0.2, 1.0, 0.6)
        else:
            mode_text = "Mode: Edit"
            mode_color = (0.9, 0.9, 0.9)
        
        slots.append({
            'id': 'active_mode',
            'text': mode_text,
            'color': mode_color,
        })
        
        hud_visible = bool(getattr(state, 'hud_help_visible', True))
        hud_key = getattr(state, 'KEY_TOGGLE_HUD', 'H')
        hud_status = 'Hide' if hud_visible else 'Show'
        slots.append({
            'id': 'hud_toggle',
            'text': f"{hud_status} Help [{hud_key}]",
            'color': (0.7, 0.7, 0.7),
        })

        if not hud_visible:
            return slots

        # Change basic input text based on active mode
        if profile_draw_mode:
            # Profile edit mode help
            slots.append({
                'id': 'basic_input',
                'text': 'LMB - Add/Move, RMB - Remove',
                'color': (0.2, 0.8, 1.0),
            })
            slots.append({
                'id': 'basic_input_2',
                'text': 'Enter - Accept, Esc - Cancel',
                'color': (0.2, 0.8, 1.0),
            })
            slots.append({
                'id': 'profile_transform',
                'text': 'S - Scale, G - Move',
                'color': (0.6, 0.9, 1.0),
            })
            symmetry_on = getattr(state, 'custom_profile_symmetry', False)
            sym_status = "ON" if symmetry_on else "OFF"
            sym_color = (1.0, 0.5, 0.5) if symmetry_on else (0.6, 0.9, 1.0)
            slots.append({
                'id': 'profile_symmetry',
                'text': f'X - Symmetry [{sym_status}]',
                'color': sym_color,
            })
            slots.append({
                'id': 'profile_clear',
                'text': 'Backspace - Clear Profile',
                'color': (0.6, 0.9, 1.0),
            })
        elif getattr(state, 'parent_mode_active', False):
            slots.append({
                'id': 'basic_input',
                'text': 'LMB - Select Parent Object',
                'color': (1.0, 0.7, 0.2),
            })
            slots.append({
                'id': 'basic_input_2',
                'text': 'Click empty space to clear parent',
                'color': (1.0, 0.7, 0.2),
            })
        else:
            slots.append({
                'id': 'basic_input',
                'text': 'LMB - Add/Move, RMB - Remove',
                'color': (0.9, 0.9, 0.9),
            })

            switch_key = getattr(state, 'KEY_SWITCH_MESH', 'Q')
            slots.append({
                'id': 'basic_input_2',
                'text': f'New [Space], Edit Other [Alt+{switch_key}], Exit [Enter]',
                'color': (0.85, 0.85, 0.85),
            })

        # In profile edit mode, return early with simplified HUD
        if profile_draw_mode:
            return slots

        slots.append({
            'id': 'spacer',
            'text': ' ',
            'color': (0.0, 0.0, 0.0),
        })
        
        bspline_on = bool(getattr(state, 'bspline_mode', False))
        spline_key = getattr(state, 'KEY_BSPLINE', 'B')
        if bspline_on:
            spline_text = f"Spline mode [{spline_key}] - B-spline"
        else:
            spline_text = f"Spline mode [{spline_key}] - Catmull-Rom"
        slots.append({
            'id': 'spline',
            'text': spline_text,
            'color': (0.85, 0.35, 1.0)
        })
        
        mirror_on = bool(getattr(state, 'mirror_mode_active', False))
        mirror_key = getattr(state, 'KEY_MIRROR', 'X')
        mirror_status = 'ON' if mirror_on else 'OFF'
        slots.append({
            'id': 'mirror',
            'text': f"Mirror Mode [{mirror_key}] - {mirror_status}",
            'color': (0.2, 0.8, 1.0)
        })
        
        has_curve = len(getattr(state, 'points_3d', [])) >= 2 and \
                    len(getattr(state, 'point_radii_3d', [])) >= 2
        if has_curve and not getattr(state, 'profile_twist_mode', False):
            if getattr(state, 'hover_point_index', -1) < 0:
                slots.append({
                    'id': 'radii_scale',
                    'text': 'Radii Adjust Mode [Hold RMB]',
                    'color': (0.4, 1.0, 0.4)
                })

            if getattr(state, 'radius_scale_active', False):
                slots.append({
                    'id': 'radii_ramp',
                    'text': 'Radii Ramp [Mouse Wheel]',
                    'color': (0.4, 0.8, 1.0)
                })
                slots.append({
                    'id': 'radii_equalize',
                    'text': 'Radii Equalize [MMB]',
                    'color': (0.8, 0.8, 1.0)
                })
        
        twist_active = bool(getattr(state, 'profile_twist_mode', False))
        twist_key = getattr(state, 'KEY_TWIST', 'T')
        if twist_active:
            slots.append({
                'id': 'twist',
                'text': f"Twist Mode [{twist_key}]",
                'color': (1.0, 0.8, 0.2)
            })
            slots.append({
                'id': 'twist_controls',
                'text': 'LMB: Point/Ramp, RMB: Global, Wheel: Ramp, MMB: Reset',
                'color': (1.0, 0.7, 0.3)
            })
        else:
            slots.append({
                'id': 'twist',
                'text': f"Twist Mode [{twist_key}]",
                'color': (1.0, 0.8, 0.2)
            })
        
        snapping_mode = getattr(state, 'snapping_mode', 0)
        snapping_key = getattr(state, 'KEY_SNAPPING_MODE', 'S')
        if snapping_mode == getattr(state, 'SNAPPING_FACE', 1):
            snapping_label = 'FACE'
        else:
            snapping_label = 'OFF'
        slots.append({
            'id': 'snapping',
            'text': f"Snapping [{snapping_key}] - {snapping_label}",
            'color': (0.8, 0.8, 0.3)
        })
        
        adaptive_on = bool(getattr(state, 'adaptive_segmentation', False))
        adaptive_key = getattr(state, 'KEY_ADAPTIVE', 'A')
        status_text = 'ON' if adaptive_on else 'OFF'
        slots.append({
            'id': 'adaptive',
            'text': f"Adaptive mode [{adaptive_key}] - {status_text}",
            'color': (0.6, 0.9, 0.6)
        })

        # Parent mode indicator
        # None = not set, "" = explicitly cleared, "ObjectName" = set to object
        parent_active = bool(getattr(state, 'parent_mode_active', False))
        parent_key = getattr(state, 'KEY_PARENT_MODE', 'TAB')
        selected_parent = getattr(state, 'selected_parent_name', None)
        if parent_active:
            parent_text = f"Parent Mode (click parent or empty to clear)"
            parent_color = (1.0, 0.8, 0.2)
        elif selected_parent is not None and selected_parent != "":
            parent_text = f"Parent [{parent_key}] - {selected_parent}"
            parent_color = (0.5, 0.9, 0.5)
        elif selected_parent == "":
            parent_text = f"Parent [{parent_key}] - Cleared"
            parent_color = (0.7, 0.7, 0.7)
        else:
            parent_text = f"Choose Parent [{parent_key}]"
            parent_color = (0.7, 0.7, 0.7)
        slots.append({
            'id': 'parent',
            'text': parent_text,
            'color': parent_color
        })

        start_cap = int(getattr(state, 'start_cap_type', 1))
        end_cap = int(getattr(state, 'end_cap_type', 1))
        if start_cap == end_cap:
            if start_cap <= 0:
                cap_label = 'None'
            elif start_cap == 1:
                cap_label = 'Hemisphere'
            elif start_cap == 2:
                cap_label = 'Planar'
            else:
                cap_label = 'Custom'
        else:
            cap_label = 'Mixed'

        cap_key = getattr(state, 'KEY_PROFILE_CAP_TOGGLE', 'C')
        slots.append({
            'id': 'caps',
            'text': f"Cap Type [{cap_key}] - {cap_label}",
            'color': (0.9, 0.75, 0.5)
        })

        profile_type = getattr(state, 'profile_global_type', 0)
        profile_names = {
            getattr(state, 'PROFILE_CIRCULAR', 0): 'Circular',
            getattr(state, 'PROFILE_SQUARE', 1): 'Square',
            getattr(state, 'PROFILE_SQUARE_ROUNDED', 2): 'Rounded Square',
            getattr(state, 'PROFILE_CUSTOM', 3): 'Custom',
        }
        profile_label = profile_names.get(profile_type, 'Circular')
        if profile_type == getattr(state, 'PROFILE_CUSTOM', 3):
            slot_index = getattr(state, 'active_custom_profile_slot', 0)
            slot_num = slot_index + 4
            n_pts = len(getattr(state, 'custom_profile_points', []))
            profile_label = f"Custom {slot_num} ({n_pts}pts)"
        slots.append({
            'id': 'profile',
            'text': f"Profile [1-3,4-9] - {profile_label}",
            'color': (0.7, 0.7, 0.9)
        })
        
        if getattr(state, 'custom_profile_draw_mode', False):
            point_count = len(state._custom_profile_data.get('screen_points', []))
            sym_status = "ON" if getattr(state, 'custom_profile_symmetry', False) else "OFF"
            slots.append({
                'id': 'custom_profile_draw',
                'text': f"Drawing Profile: {point_count} pts | LMB:add RMB:del Bksp:clear | S:scale R:rot G:move X:symmetry({sym_status}) | Enter:accept ESC:cancel",
                'color': (1.0, 0.8, 0.2)
            })

        if profile_type == getattr(state, 'PROFILE_SQUARE_ROUNDED', 2):
            roundness_value = float(getattr(state, 'profile_roundness', 0.3))
            roundness_key = getattr(state, 'KEY_PROFILE_ROUNDNESS', 'R')
            slots.append({
                'id': 'profile_roundness',
                'text': f"Roundness [{roundness_key}] - {roundness_value:.2f}",
                'color': (0.8, 0.7, 1.0)
            })
        
        return slots
    
    @classmethod
    def draw(cls, context, font_id):
        """Draw all active HUD slots near the cursor."""
        if not cls.enabled:
            return
        
        if not state.is_running:
            return
        
        if state.last_mouse_pos is None:
            return
        
        mx, my = state.last_mouse_pos
        slots = cls.get_active_slots()
        
        if not slots:
            return
        
        try:
            visible_index = 0
            for slot in slots:
                slot_id = slot['id']
                
                if not cls.slot_visibility.get(slot_id, True):
                    continue
                
                slot_alpha = cls.slot_opacity.get(slot_id, 1.0)
                final_alpha = cls.global_opacity * slot_alpha
                
                r, g, b = slot['color']
                blf.color(font_id, r, g, b, final_alpha)
                
                # Make mode line larger
                if slot_id == 'active_mode':
                    blf.size(font_id, int(cls.font_size * 1.4))
                else:
                    blf.size(font_id, cls.font_size)
                
                y_pos = my - cls.offset_y - (visible_index * cls.line_height)
                blf.position(font_id, mx + cls.offset_x, y_pos, 0)
                
                blf.draw(font_id, slot['text'])
                visible_index += 1
        
        except Exception:
            pass
    
    @classmethod
    def set_global_visibility(cls, visible):
        cls.enabled = visible
    
    @classmethod
    def set_slot_visibility(cls, slot_id, visible):
        cls.slot_visibility[slot_id] = visible
    
    @classmethod
    def set_global_opacity(cls, opacity):
        cls.global_opacity = max(0.0, min(1.0, opacity))
    
    @classmethod
    def set_slot_opacity(cls, slot_id, opacity):
        cls.slot_opacity[slot_id] = max(0.0, min(1.0, opacity))
    
    @classmethod
    def set_position(cls, offset_x=None, offset_y=None):
        if offset_x is not None:
            cls.offset_x = offset_x
        if offset_y is not None:
            cls.offset_y = offset_y
    
    @classmethod
    def set_line_height(cls, height):
        cls.line_height = height
    
    @classmethod
    def set_font_size(cls, size):
        cls.font_size = size


def create_circle_vertices(center_x, center_y, radius, segments=32):
    """Create vertices for a 2D circle"""
    vertices = []
    for i in range(segments + 1):
        angle = 2 * math.pi * i / segments
        x = center_x + math.cos(angle) * radius
        y = center_y + math.sin(angle) * radius
        vertices.append((x, y, 0.0))
    return vertices


def draw_callback_px(operator, context):
    """Draw the curve points and lines in the viewport"""
    if not state.is_running:
        return
    
    font_id = 0
    
    if getattr(state, 'custom_profile_draw_mode', False):
        screen_points = state._custom_profile_data['screen_points']
        num_points = len(screen_points) if screen_points else 0
        
        shader_fill = gpu.shader.from_builtin('UNIFORM_COLOR')
        shader_line = gpu.shader.from_builtin('POLYLINE_SMOOTH_COLOR')
        
        # Draw symmetry line if enabled
        if getattr(state, 'custom_profile_symmetry', False):
            region = bpy.context.region
            # Use the fixed symmetry center
            sym_center = getattr(state, 'custom_profile_symmetry_center', None)
            if sym_center:
                center_x, center_y = sym_center
            else:
                center_x = region.width / 2
                center_y = region.height / 2
            
            # Draw symmetry line through center at the tracked angle
            angle = getattr(state, 'custom_profile_symmetry_angle', 0.0)
            line_length = max(region.width, region.height)
            # Line direction perpendicular to mirror axis (along the axis)
            dx = math.sin(angle) * line_length
            dy = math.cos(angle) * line_length
            
            sym_line_verts = [
                (float(center_x - dx), float(center_y - dy), 0.0),
                (float(center_x + dx), float(center_y + dy), 0.0)
            ]
            sym_line_colors = [(1.0, 0.2, 0.2, 0.8), (1.0, 0.2, 0.2, 0.8)]
            
            batch_sym = batch_for_shader(shader_line, 'LINE_STRIP',
                {"pos": sym_line_verts, "color": sym_line_colors})
            gpu.state.blend_set('ALPHA')
            shader_line.bind()
            shader_line.uniform_float("lineWidth", 2.0)
            shader_line.uniform_float("viewportSize", (region.width, region.height))
            batch_sym.draw(shader_line)
        
        if num_points > 0:
            # In symmetry mode, generate full profile for line drawing
            symmetry_enabled = getattr(state, 'custom_profile_symmetry', False)
            if symmetry_enabled and num_points >= 1:
                # Use the fixed symmetry center
                sym_center = getattr(state, 'custom_profile_symmetry_center', None)
                if sym_center:
                    center = sym_center
                else:
                    center_x = sum(pt[0] for pt in screen_points) / num_points
                    center_y = sum(pt[1] for pt in screen_points) / num_points
                    center = (center_x, center_y)
                angle = getattr(state, 'custom_profile_symmetry_angle', 0.0)
                
                # Generate mirrored points for drawing
                mirrored_points = []
                for pt in reversed(screen_points):
                    cx, cy = center
                    px, py = pt[0] - cx, pt[1] - cy
                    cos_a = math.cos(-angle)
                    sin_a = math.sin(-angle)
                    rx = px * cos_a - py * sin_a
                    ry = px * sin_a + py * cos_a
                    rx = -rx
                    cos_a = math.cos(angle)
                    sin_a = math.sin(angle)
                    mx = rx * cos_a - ry * sin_a
                    my = rx * sin_a + ry * cos_a
                    mirrored_points.append((mx + cx, my + cy))
                
                draw_points = mirrored_points + list(screen_points)
            else:
                draw_points = screen_points
            
            draw_num_points = len(draw_points)
            
            if draw_num_points >= 2:
                hover_edge = getattr(state, 'custom_profile_hover_edge', -1)
                hover_edge_pt = getattr(state, 'custom_profile_hover_edge_point', None)
                
                line_color = (0.2, 0.8, 1.0, 0.8)
                mirror_line_color = (0.5, 0.5, 0.8, 0.6)  # Dimmer for mirrored side
                highlight_color = (1.0, 0.5, 0.0, 1.0)
                
                line_verts = []
                line_colors = []
                for i, pt in enumerate(draw_points):
                    line_verts.append((float(pt[0]), float(pt[1]), 0.0))
                    # Use dimmer color for mirrored points (first half in symmetry mode)
                    if symmetry_enabled and i < len(mirrored_points):
                        line_colors.append(mirror_line_color)
                    elif i == hover_edge:
                        line_colors.append(highlight_color)
                    else:
                        line_colors.append(line_color)
                line_verts.append((float(draw_points[0][0]), float(draw_points[0][1]), 0.0))
                if symmetry_enabled:
                    line_colors.append(mirror_line_color)
                elif hover_edge == draw_num_points - 1:
                    line_colors.append(highlight_color)
                else:
                    line_colors.append(line_color)
                
                batch_lines = batch_for_shader(shader_line, 'LINE_STRIP', 
                    {"pos": line_verts, "color": line_colors})
                gpu.state.blend_set('ALPHA')
                shader_line.bind()
                shader_line.uniform_float("lineWidth", 2.0)
                shader_line.uniform_float("viewportSize", (bpy.context.region.width, bpy.context.region.height))
                batch_lines.draw(shader_line)
                
                if hover_edge >= 0 and hover_edge_pt is not None:
                    insert_verts = create_circle_vertices(float(hover_edge_pt[0]), float(hover_edge_pt[1]), 5.0, segments=16)
                    batch_insert = batch_for_shader(shader_fill, 'TRI_FAN', {"pos": insert_verts})
                    shader_fill.bind()
                    shader_fill.uniform_float("color", (1.0, 0.5, 0.0, 0.8))
                    batch_insert.draw(shader_fill)
            
            hover_idx = getattr(state, 'custom_profile_hover_index', -1)
            active_idx = getattr(state, 'custom_profile_active_index', -1)
            
            # Check for center points (on axis) in symmetry mode
            def is_center_point(pt):
                if not symmetry_enabled:
                    return False
                sym_center = getattr(state, 'custom_profile_symmetry_center', None)
                if sym_center is None:
                    return False
                sym_angle = getattr(state, 'custom_profile_symmetry_angle', 0.0)
                # Check distance to axis
                cx, cy = sym_center
                px, py = pt[0] - cx, pt[1] - cy
                cos_a = math.cos(-sym_angle)
                sin_a = math.sin(-sym_angle)
                rx = px * cos_a - py * sin_a
                return abs(rx) < 5.0
            
            # Only draw editable points (right-side in symmetry mode)
            for i, pt in enumerate(screen_points):
                px, py = float(pt[0]), float(pt[1])
                
                is_active = (i == active_idx)
                is_hover = (i == hover_idx)
                is_on_axis = is_center_point(pt)
                
                if is_active:
                    fill_color = (1.0, 0.5, 0.0, 1.0)
                    radius = 8.0
                elif is_hover:
                    fill_color = (1.0, 0.7, 0.3, 1.0)
                    radius = 7.0
                elif is_on_axis:
                    # Center points (on axis) - draw in red to indicate locked
                    fill_color = (1.0, 0.3, 0.3, 1.0)
                    radius = 7.0
                else:
                    fill_color = (1.0, 0.8, 0.2, 1.0)
                    radius = 6.0
                
                outline_color = (0.0, 0.0, 0.0, 1.0)
                
                circle_verts = create_circle_vertices(px, py, radius, segments=16)
                
                batch_fill = batch_for_shader(shader_fill, 'TRI_FAN', {"pos": circle_verts})
                shader_fill.bind()
                shader_fill.uniform_float("color", fill_color)
                batch_fill.draw(shader_fill)
                
                outline_verts = [(v[0], v[1], v[2], *outline_color) for v in circle_verts]
                batch_outline = batch_for_shader(shader_line, 'LINE_STRIP',
                    {"pos": [v[0:3] for v in outline_verts], "color": [v[3:7] for v in outline_verts]})
                shader_line.bind()
                shader_line.uniform_float("lineWidth", 1.5)
                shader_line.uniform_float("viewportSize", (bpy.context.region.width, bpy.context.region.height))
                batch_outline.draw(shader_line)
    
    inside_any_radius_circle = False
    if state.last_mouse_pos is not None and len(state.points_3d) > 0 and len(state.point_radii_3d) > 0:
        mx, my = state.last_mouse_pos
        for i, p3d in enumerate(state.points_3d):
            if i >= len(state.point_radii_3d):
                break
            p2d = conversion.get_2d_from_3d(context, p3d)
            if p2d is None:
                continue
            sr = conversion.get_consistent_screen_radius(context, state.point_radii_3d[i], p3d)
            if sr <= 0.0:
                continue
            dx = mx - p2d[0]
            dy = my - p2d[1]
            if (dx*dx + dy*dy) <= (sr*sr):
                inside_any_radius_circle = True
                break

    # Skip preview circle and dashed line during profile edit mode
    profile_draw_active = getattr(state, 'custom_profile_draw_mode', False)
    
    if (
        state.is_running and state.last_mouse_pos is not None
        and not state.hover_on_curve
        and state.hover_point_index == -1
        and state.hover_radius_index == -1
        and state.hover_tension_index == -1
        and state.active_point_index == -1
        and state.adjusting_radius_index == -1
        and state.creating_point_index == -1
        and not inside_any_radius_circle
        and not profile_draw_active
    ):
        try:
            mx, my = state.last_mouse_pos
            candidate_point = None
            try:
                candidate_point = operator._get_new_point_3d(context, state.last_mouse_pos)
            except Exception:
                candidate_point = None
            base_radius_3d = state.DEFAULT_RADIUS
            if len(state.points_3d) == 0:
                if getattr(state, 'last_drag_radius', None) is not None and state.last_drag_radius >= 0.02:
                    base_radius_3d = state.last_drag_radius
            else:
                start_2d = conversion.get_2d_from_3d(context, state.points_3d[0])
                end_2d = conversion.get_2d_from_3d(context, state.points_3d[-1])
                add_to_start = False
                if start_2d and end_2d:
                    mv = Vector((mx, my))
                    ds = (mv - Vector(start_2d)).length
                    de = (mv - Vector(end_2d)).length
                    add_to_start = ds < de
                elif start_2d:
                    add_to_start = True
                if getattr(state, 'last_drag_radius', None) is not None and state.last_drag_radius >= 0.02:
                    base_radius_3d = state.last_drag_radius
                else:
                    base_radius_3d = state.point_radii_3d[0] if add_to_start else state.point_radii_3d[-1]
            if candidate_point is None:
                ref_point = state.points_3d[0] if len(state.points_3d) > 0 else Vector((0.0, 0.0, 0.0))
                screen_radius = conversion.get_consistent_screen_radius(context, base_radius_3d, ref_point)
            else:
                screen_radius = conversion.get_consistent_screen_radius(context, base_radius_3d, candidate_point)
            
            if state.parent_mode_active:
                # Draw orange crosshair instead of preview circle when in parent mode
                shader_line = gpu.shader.from_builtin('POLYLINE_SMOOTH_COLOR')
                size = max(8.0, min(32.0, screen_radius))
                color = (1.0, 0.7, 0.2, 0.9)
                verts = [
                    (mx - size, my, 0.0, *color), (mx + size, my, 0.0, *color),
                    (mx, my - size, 0.0, *color), (mx, my + size, 0.0, *color),
                ]
                pos_data = [v[0:3] for v in verts]
                cols = [v[3:7] for v in verts]
                batch_h = batch_for_shader(shader_line, 'LINES', {"pos": pos_data, "color": cols})
                gpu.state.blend_set('ALPHA')
                shader_line.bind()
                shader_line.uniform_float("lineWidth", 2.0)
                shader_line.uniform_float("viewportSize", (bpy.context.region.width, bpy.context.region.height))
                batch_h.draw(shader_line)
            elif not state.profile_twist_mode:
                shader_outline = gpu.shader.from_builtin('POLYLINE_SMOOTH_COLOR')
                circle_verts = create_circle_vertices(mx, my, screen_radius, segments=64)
                outline_vertices = []
                for v in circle_verts:
                    outline_vertices.append((v[0], v[1], v[2], 1.0, 0.0, 0.0, 0.5))
                batch_outline = batch_for_shader(
                    shader_outline, 'LINE_STRIP',
                    {
                        "pos": [v[0:3] for v in outline_vertices],
                        "color": [v[3:7] for v in outline_vertices]
                    }
                )
                gpu.state.blend_set('ALPHA')
                gpu.state.depth_test_set('NONE')
                shader_outline.bind()
                shader_outline.uniform_float("lineWidth", 2.0)
                shader_outline.uniform_float("viewportSize", (bpy.context.region.width, bpy.context.region.height))
                batch_outline.draw(shader_outline)
                
                if len(state.points_3d) > 0:
                    try:
                        start_2d_tmp = conversion.get_2d_from_3d(context, state.points_3d[0])
                        end_2d_tmp = conversion.get_2d_from_3d(context, state.points_3d[-1])
                        target_idx = 0
                        if start_2d_tmp and end_2d_tmp:
                            mv_tmp = Vector((mx, my))
                            ds_tmp = (mv_tmp - Vector(start_2d_tmp)).length
                            de_tmp = (mv_tmp - Vector(end_2d_tmp)).length
                            target_idx = 0 if ds_tmp < de_tmp else (len(state.points_3d) - 1)
                        elif start_2d_tmp:
                            target_idx = 0
                        else:
                            target_idx = len(state.points_3d) - 1
                        target_2d = conversion.get_2d_from_3d(context, state.points_3d[target_idx])
                        if target_2d is not None:
                            x0, y0 = mx, my
                            x1, y1 = target_2d[0], target_2d[1]
                            dx = x1 - x0
                            dy = y1 - y0
                            dist = math.hypot(dx, dy)
                            if dist > 1.0:
                                ux = dx / dist
                                uy = dy / dist
                                dash_length = 12.0
                                gap_length = 8.0
                                line_vertices = []
                                pos = 0.0
                                while pos < dist:
                                    seg_start = pos
                                    seg_end = min(pos + dash_length, dist)
                                    sx = x0 + ux * seg_start
                                    sy = y0 + uy * seg_start
                                    ex = x0 + ux * seg_end
                                    ey = y0 + uy * seg_end
                                    line_vertices.append((sx, sy, 0.0, 1.0, 0.0, 0.0, 0.5))
                                    line_vertices.append((ex, ey, 0.0, 1.0, 0.0, 0.0, 0.5))
                                    pos += dash_length + gap_length
                                if line_vertices:
                                    shader_line2 = gpu.shader.from_builtin('POLYLINE_SMOOTH_COLOR')
                                    batch_dashed = batch_for_shader(
                                        shader_line2, 'LINES',
                                        {
                                            "pos": [v[0:3] for v in line_vertices],
                                            "color": [v[3:7] for v in line_vertices]
                                        }
                                    )
                                    gpu.state.blend_set('ALPHA')
                                    shader_line2.bind()
                                    shader_line2.uniform_float("lineWidth", 2.0)
                                    shader_line2.uniform_float("viewportSize", (bpy.context.region.width, bpy.context.region.height))
                                    batch_dashed.draw(shader_line2)
                    except Exception:
                        pass
        except Exception:
            pass

    CursorHUD.draw(context, font_id)

    if state.is_running and state.last_mouse_pos is not None and state.profile_twist_mode:
        try:
            mx, my = state.last_mouse_pos
            shader_line = gpu.shader.from_builtin('POLYLINE_SMOOTH_COLOR')
            size = 20.0
            color = (1.0, 0.8, 0.2, 0.95)
            left_x = mx - size
            right_x = mx + size
            y = my
            arrow_offset = size * 0.4
            verts = [
                (left_x, y, 0.0, *color), (left_x + arrow_offset, y + arrow_offset * 0.5, 0.0, *color),
                (left_x, y, 0.0, *color), (left_x + arrow_offset, y - arrow_offset * 0.5, 0.0, *color),
                (right_x, y, 0.0, *color), (right_x - arrow_offset, y + arrow_offset * 0.5, 0.0, *color),
                (right_x, y, 0.0, *color), (right_x - arrow_offset, y - arrow_offset * 0.5, 0.0, *color),
            ]
            pos = [v[0:3] for v in verts]
            cols = [v[3:7] for v in verts]
            batch_arrows = batch_for_shader(shader_line, 'LINES', {"pos": pos, "color": cols})
            gpu.state.blend_set('ALPHA')
            gpu.state.depth_test_set('NONE')
            shader_line.bind()
            shader_line.uniform_float("lineWidth", 2.0)
            shader_line.uniform_float("viewportSize", (bpy.context.region.width, bpy.context.region.height))
            batch_arrows.draw(shader_line)
        except Exception:
            pass
    
    if len(state.points_3d) > 0:
        gpu.state.blend_set('ALPHA')
        gpu.state.depth_test_set('NONE')
        gpu.state.depth_mask_set(False)
        
        points_2d = []
        for point_3d in state.points_3d:
            point_2d = conversion.get_2d_from_3d(context, point_3d)
            if point_2d is not None:
                points_2d.append(point_2d)
        
        screen_radii = []
        for i, (point_3d, radius_3d) in enumerate(zip(state.points_3d, state.point_radii_3d)):
            if i < len(points_2d):
                screen_radius = conversion.get_consistent_screen_radius(context, radius_3d, point_3d)
                screen_radii.append(screen_radius)
        
        if len(points_2d) > 1 and len(state.points_3d) > 1:
            if getattr(state, 'bspline_mode', False):
                smooth_curve_points_3d = math_utils.bspline_cubic_open_uniform(
                    state.points_3d,
                    300
                )
            else:
                smooth_curve_points_3d = math_utils.interpolate_curve_3d(
                    state.points_3d, 
                    num_points=300,
                    sharp_points=state.no_tangent_points,
                    tensions=state.point_tensions
                )
            
            curve_points_2d = []
            for point_3d in smooth_curve_points_3d:
                point_2d = conversion.get_2d_from_3d(context, point_3d)
                if point_2d is not None:
                    curve_points_2d.append((point_2d[0], point_2d[1], 0))
            
            line_width = 4.0 if state.hover_on_curve else 3.0
            line_color = (0.2, 0.8, 1.0, 1.0) if state.hover_on_curve else (1.0, 1.0, 1.0, 1.0)
            
            shader_line = gpu.shader.from_builtin('POLYLINE_SMOOTH_COLOR')
            
            line_vertices = []
            for point in curve_points_2d:
                line_vertices.append((point[0], point[1], point[2], *line_color))
            
            batch_line = batch_for_shader(
                shader_line, 'LINE_STRIP',
                {
                    "pos": [v[0:3] for v in line_vertices],
                    "color": [v[3:7] for v in line_vertices]
                }
            )
            
            gpu.state.line_width_set(line_width)
            shader_line.bind()
            shader_line.uniform_float("lineWidth", line_width)
            shader_line.uniform_float("viewportSize", (bpy.context.region.width, bpy.context.region.height))
            batch_line.draw(shader_line)

            if getattr(state, 'bspline_mode', False) and len(points_2d) >= 2:
                try:
                    shader_ctrl = gpu.shader.from_builtin('POLYLINE_SMOOTH_COLOR')
                    ctrl_color = (0.85, 0.35, 1.0, 0.5)
                    ctrl_vertices = []
                    for p in points_2d:
                        ctrl_vertices.append((p[0], p[1], 0.0, *ctrl_color))
                    batch_ctrl = batch_for_shader(
                        shader_ctrl, 'LINE_STRIP',
                        {
                            "pos": [v[0:3] for v in ctrl_vertices],
                            "color": [v[3:7] for v in ctrl_vertices]
                        }
                    )
                    shader_ctrl.bind()
                    shader_ctrl.uniform_float("lineWidth", 2.0)
                    shader_ctrl.uniform_float("viewportSize", (bpy.context.region.width, bpy.context.region.height))
                    batch_ctrl.draw(shader_ctrl)
                except Exception:
                    pass
            
            if state.hover_on_curve and state.hover_curve_point_3d is not None:
                hover_point_2d = conversion.get_2d_from_3d(context, state.hover_curve_point_3d)
                if hover_point_2d is not None:
                    segments = 32
                    radius = 8.0
                    
                    circle_vertices = []
                    for i in range(segments):
                        angle = 2.0 * math.pi * i / segments
                        x = hover_point_2d[0] + radius * math.cos(angle)
                        y = hover_point_2d[1] + radius * math.sin(angle)
                        circle_vertices.append((x, y, 0.0, 0.2, 0.8, 1.0, 0.8))
                    
                    circle_vertices.append(circle_vertices[0])
                    
                    batch_circle = batch_for_shader(
                        shader_line, 'LINE_STRIP',
                        {
                            "pos": [v[0:3] for v in circle_vertices],
                            "color": [v[3:7] for v in circle_vertices]
                        }
                    )
                    
                    shader_line.bind()
                    shader_line.uniform_float("lineWidth", 2.0)
                    shader_line.uniform_float("viewportSize", (bpy.context.region.width, bpy.context.region.height))
                    batch_circle.draw(shader_line)

        shader_circle = gpu.shader.from_builtin('UNIFORM_COLOR')
        shader_outline = gpu.shader.from_builtin('POLYLINE_SMOOTH_COLOR')
        
        for i, point_2d in enumerate(points_2d):
            if i >= len(state.points_3d):
                continue
                
            is_active = (i == state.active_point_index)
            is_hover = (i == state.hover_point_index)
            is_adjusting_radius = (i == state.adjusting_radius_index)
            is_hovering_radius = (i == state.hover_radius_index)
            has_no_tangent = (i in state.no_tangent_points)
            
            radius = 7.0 if is_active or is_hover else 5.0
            
            if is_adjusting_radius:
                fill_color = (0.2, 0.6, 1.0, 1.0)
            elif is_hover or is_active:
                fill_color = (1.0, 0.5, 0.0, 1.0)
            elif has_no_tangent:
                fill_color = (0.0, 0.0, 0.0, 1.0)
            else:
                fill_color = (1.0, 1.0, 1.0, 1.0)
                
            outline_color = (1.0, 1.0, 1.0, 1.0) if has_no_tangent else (0.0, 0.0, 0.0, 1.0)
            
            circle_verts = create_circle_vertices(point_2d[0], point_2d[1], radius, segments=32)
            
            batch_filled = batch_for_shader(
                shader_circle, 'TRI_FAN',
                {"pos": circle_verts}
            )
            
            shader_circle.bind()
            shader_circle.uniform_float("color", fill_color)
            batch_filled.draw(shader_circle)
            
            outline_vertices = []
            for v in circle_verts:
                outline_vertices.append((v[0], v[1], v[2], outline_color[0], outline_color[1], outline_color[2], outline_color[3]))
            
            batch_outline = batch_for_shader(
                shader_outline, 'LINE_STRIP',
                {
                    "pos": [v[0:3] for v in outline_vertices],
                    "color": [v[3:7] for v in outline_vertices]
                }
            )
            
            shader_outline.bind()
            shader_outline.uniform_float("lineWidth", 1.0)
            shader_outline.uniform_float("viewportSize", (bpy.context.region.width, bpy.context.region.height))
            batch_outline.draw(shader_outline)
            
            should_show_controls = (
                (i == getattr(state, 'reveal_control_index', -1)) or
                (i == state.adjusting_radius_index) or
                (i == state.adjusting_tension_index) or
                (i == getattr(state, 'creating_point_index', -1))
            )
            # Skip radius circles during profile edit mode
            if should_show_controls and i < len(state.point_radii_3d) and i < len(screen_radii) and not profile_draw_active:
                radius_value = screen_radii[i]
                
                radius_circle_verts = create_circle_vertices(point_2d[0], point_2d[1], radius_value, segments=48)
                
                if is_adjusting_radius:
                    radius_color = (0.2, 0.8, 1.0, 0.9)
                    line_width = 4.0
                elif is_hovering_radius:
                    radius_color = (1.0, 0.5, 0.0, 0.8)
                    line_width = 4.0
                else:
                    radius_color = (0.7, 0.7, 0.7, 0.6)
                    line_width = 3.0
                
                radius_vertices = []
                for v in radius_circle_verts:
                    radius_vertices.append((v[0], v[1], v[2], radius_color[0], radius_color[1], radius_color[2], radius_color[3]))
                
                batch_radius = batch_for_shader(
                    shader_outline, 'LINE_STRIP',
                    {
                        "pos": [v[0:3] for v in radius_vertices],
                        "color": [v[3:7] for v in radius_vertices]
                    }
                )
                
                shader_outline.bind()
                shader_outline.uniform_float("lineWidth", line_width)
                shader_outline.uniform_float("viewportSize", (bpy.context.region.width, bpy.context.region.height))
                batch_radius.draw(shader_outline)
                
                if (not getattr(state, 'bspline_mode', False)) and (i == getattr(state, 'reveal_control_index', -1)):
                    if i >= len(state.point_tensions):
                        while len(state.point_tensions) <= i:
                            state.point_tensions.append(0.5)
                    tension = state.point_tensions[i]
                    margin = math.radians(18.0)
                    angle_span = max(1e-4, 2.0 * math.pi - 2.0 * margin)
                    angle = margin + tension * angle_span
                    handle_offset_px = 20.0
                    handle_radius = radius_value + handle_offset_px
                    tx = point_2d[0] + handle_radius * math.cos(angle)
                    ty = point_2d[1] + handle_radius * math.sin(angle)
                    scale = 0.7
                    size = 12.0 * scale
                    if tension <= 0.5:
                        tcol = max(0.0, min(1.0, tension / 0.5))
                        r, g, b = 1.0, tcol, 0.0
                    else:
                        tcol = max(0.0, min(1.0, (tension - 0.5) / 0.5))
                        r, g, b = 1.0 - tcol, 1.0, 0.0
                    a = 1.0
                    dot_verts = create_circle_vertices(tx, ty, size, segments=24)
                    batch_dot = batch_for_shader(
                        shader_circle, 'TRI_FAN',
                        {"pos": dot_verts}
                    )
                    shader_circle.bind()
                    shader_circle.uniform_float("color", (r, g, b, a))
                    batch_dot.draw(shader_circle)

    # Draw dashed link from first point to chosen parent when set (not None and not empty string)
    selected_parent_for_line = getattr(state, 'selected_parent_name', None)
    if selected_parent_for_line is not None and selected_parent_for_line != "" and len(state.points_3d) >= 1:
        try:
            parent_obj = bpy.data.objects.get(state.selected_parent_name)
            if parent_obj is not None and len(state.points_3d) >= 1:
                # get_2d_from_3d automatically transforms from object space to world space
                p0_2d = conversion.get_2d_from_3d(context, state.points_3d[0])
                # Parent position is already in world space
                parent_2d = conversion.get_2d_from_3d(context, parent_obj.matrix_world.translation, is_world_space=True)
                if p0_2d is not None and parent_2d is not None:
                    x0, y0 = p0_2d[0], p0_2d[1]
                    x1, y1 = parent_2d[0], parent_2d[1]
                    dx = x1 - x0
                    dy = y1 - y0
                    dist = math.hypot(dx, dy)
                    if dist > 1.0:
                        ux = dx / dist
                        uy = dy / dist
                        dash_length = 14.0
                        gap_length = 10.0
                        line_vertices = []
                        pos_val = 0.0
                        while pos_val < dist:
                            seg_start = pos_val
                            seg_end = min(pos_val + dash_length, dist)
                            sx = x0 + ux * seg_start
                            sy = y0 + uy * seg_start
                            ex = x0 + ux * seg_end
                            ey = y0 + uy * seg_end
                            line_vertices.append((sx, sy, 0.0, 1.0, 0.7, 0.2, 0.35))
                            line_vertices.append((ex, ey, 0.0, 1.0, 0.7, 0.2, 0.35))
                            pos_val += dash_length + gap_length
                        if line_vertices:
                            shader_link = gpu.shader.from_builtin('POLYLINE_SMOOTH_COLOR')
                            batch_link = batch_for_shader(
                                shader_link, 'LINES',
                                {
                                    "pos": [v[0:3] for v in line_vertices],
                                    "color": [v[3:7] for v in line_vertices]
                                }
                            )
                            gpu.state.blend_set('ALPHA')
                            shader_link.bind()
                            shader_link.uniform_float("lineWidth", 2.0)
                            shader_link.uniform_float("viewportSize", (bpy.context.region.width, bpy.context.region.height))
                            batch_link.draw(shader_link)
        except Exception:
            pass


def register():
    pass


def unregister():
    pass
