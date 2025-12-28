"""
Mesh utilities for the Flex tool in Super Tools addon.
Handles mesh generation for flex meshes and other 3D objects.
"""
import bpy
import math
from mathutils import Vector, Matrix
from .flex_state import state
from . import flex_math as math_utils
from . import flex_conversion as conversion


def _get_or_create_mirror_empty():
    """Get or create the mirror object empty at world origin."""
    empty_name = state.mirror_empty_name
    if empty_name in bpy.data.objects:
        return bpy.data.objects[empty_name]
    empty = bpy.data.objects.new(empty_name, None)
    empty.empty_display_type = 'PLAIN_AXES'
    empty.empty_display_size = 0.5
    empty.location = (0, 0, 0)
    bpy.context.collection.objects.link(empty)
    return empty


def apply_mirror_modifier(obj, enable):
    """Add or remove a mirror modifier on the given object."""
    mod_name = "Flex_Mirror"
    
    if enable:
        mirror_empty = _get_or_create_mirror_empty()
        
        if mod_name not in obj.modifiers:
            mod = obj.modifiers.new(name=mod_name, type='MIRROR')
        else:
            mod = obj.modifiers[mod_name]

        mod.use_axis[0] = True
        mod.use_axis[1] = False
        mod.use_axis[2] = False
        mod.use_bisect_axis[0] = True
        mod.use_bisect_axis[1] = False
        mod.use_bisect_axis[2] = False
        mod.use_bisect_flip_axis[0] = getattr(state, 'mirror_flip_x', False)
        mod.mirror_object = mirror_empty
        mod.use_clip = True
        mod.use_mirror_merge = True
        mod.merge_threshold = 0.001
    else:
        if mod_name in obj.modifiers:
            obj.modifiers.remove(obj.modifiers[mod_name])


def update_mirror_flip_from_points(obj, points_3d):
    """Check which side of the X axis the majority of curve points are on."""
    mod_name = "Flex_Mirror"
    if obj is None or mod_name not in obj.modifiers:
        return
    
    if not points_3d or len(points_3d) == 0:
        return
    
    mod = obj.modifiers[mod_name]
    
    negative_count = 0
    positive_count = 0
    for p in points_3d:
        x = p[0] if hasattr(p, '__getitem__') else p.x
        if x < 0.0:
            negative_count += 1
        else:
            positive_count += 1
    
    if negative_count > positive_count:
        should_flip = True
    elif positive_count > negative_count:
        should_flip = False
    else:
        should_flip = getattr(state, 'mirror_flip_x', False)
    
    mod.use_bisect_flip_axis[0] = should_flip
    state.mirror_flip_x = should_flip


def points_to_flat_list(points):
    """Convert a list of Vector objects to a flat list of floats."""
    if not points:
        return []
    flat_list = [0.0] * (len(points) * 3)
    for i, p in enumerate(points):
        idx = i * 3
        flat_list[idx] = p.x
        flat_list[idx+1] = p.y
        flat_list[idx+2] = p.z
    return flat_list


def faces_to_flat_list(faces):
    """Convert a list of face index tuples/lists to a flat list of ints."""
    if not faces or not faces[0]:
        return []
    num_verts_per_face = len(faces[0])
    flat_list = [0] * (len(faces) * num_verts_per_face)
    for i, face in enumerate(faces):
        idx_base = i * num_verts_per_face
        for j, v_idx in enumerate(face):
            flat_list[idx_base + j] = v_idx
    return flat_list


def create_circle_vertices(center, radius, direction, up, side, resolution=16, twist_angle=0.0, aspect_ratio=1.0):
    """Create vertices for a circle in 3D space."""
    vertices = []
    
    for i in range(resolution):
        angle = 2 * math.pi * i / resolution
        x = math.cos(angle) * aspect_ratio
        y = math.sin(angle)
        
        if twist_angle != 0.0:
            cos_twist = math.cos(twist_angle)
            sin_twist = math.sin(twist_angle)
            rotated_side = side * cos_twist + up * sin_twist
            rotated_up = up * cos_twist - side * sin_twist
        else:
            rotated_side = side
            rotated_up = up
        
        pos = center + (rotated_side * x + rotated_up * y) * radius
        vertices.append(pos)
    
    return vertices


def generate_square_profile(center, radius, side, up, resolution, aspect_ratio=1.0, twist_angle=0.0, roundness=0.0):
    """Generate vertices for a square profile with optional rounded corners."""
    vertices = []
    
    if twist_angle != 0.0:
        cos_twist = math.cos(twist_angle)
        sin_twist = math.sin(twist_angle)
        rotated_side = side * cos_twist + up * sin_twist
        rotated_up = up * cos_twist - side * sin_twist
    else:
        rotated_side = side
        rotated_up = up
    
    roundness = max(0.0, min(1.0, roundness))
    
    # Simple 4-point square when no roundness
    if roundness < 0.001:
        half_w = radius * aspect_ratio
        half_h = radius
        corners = [
            (-half_w, half_h),   # Top-left
            (half_w, half_h),    # Top-right
            (half_w, -half_h),   # Bottom-right
            (-half_w, -half_h),  # Bottom-left
        ]
        for x, y in corners:
            pos = center + (rotated_side * x + rotated_up * y)
            vertices.append(pos)
        vertices.reverse()
        return vertices
    
    # Rounded corners - use more vertices
    corner_vertex_count = max(2, resolution // 4)
    if corner_vertex_count < 2:
        corner_vertex_count = 2
    
    f = 1.0 / (corner_vertex_count - 1)
    
    # Top-left corner vertices
    for i in range(corner_vertex_count):
        s = math.sin(i * math.pi * 0.5 * f)
        c = math.cos(i * math.pi * 0.5 * f)
        v1_x = -radius * aspect_ratio + roundness * radius * aspect_ratio - c * roundness * radius * aspect_ratio
        v1_y = radius - roundness * radius + s * roundness * radius
        pos = center + (rotated_side * v1_x + rotated_up * v1_y)
        vertices.append(pos)
    
    # Top-right corner vertices
    for i in range(corner_vertex_count):
        s = math.sin(i * math.pi * 0.5 * f)
        c = math.cos(i * math.pi * 0.5 * f)
        v2_x = radius * aspect_ratio - roundness * radius * aspect_ratio + s * roundness * radius * aspect_ratio
        v2_y = radius - roundness * radius + c * roundness * radius
        pos = center + (rotated_side * v2_x + rotated_up * v2_y)
        vertices.append(pos)
    
    # Bottom-right corner vertices
    for i in range(corner_vertex_count):
        s = math.sin(i * math.pi * 0.5 * f)
        c = math.cos(i * math.pi * 0.5 * f)
        v3_x = radius * aspect_ratio - roundness * radius * aspect_ratio + c * roundness * radius * aspect_ratio
        v3_y = -radius + roundness * radius - s * roundness * radius
        pos = center + (rotated_side * v3_x + rotated_up * v3_y)
        vertices.append(pos)
    
    # Bottom-left corner vertices
    for i in range(corner_vertex_count):
        s = math.sin(i * math.pi * 0.5 * f)
        c = math.cos(i * math.pi * 0.5 * f)
        v4_x = -radius * aspect_ratio + roundness * radius * aspect_ratio - s * roundness * radius * aspect_ratio
        v4_y = -radius + roundness * radius - c * roundness * radius
        pos = center + (rotated_side * v4_x + rotated_up * v4_y)
        vertices.append(pos)
    
    vertices.reverse()
    return vertices


def generate_custom_profile(center, radius, side, up, resolution, aspect_ratio=1.0, twist_angle=0.0, custom_points=None):
    """Generate profile vertices from custom 2D profile points."""
    if not custom_points or len(custom_points) < 3:
        direction = up.cross(side).normalized()
        return create_circle_vertices(center, radius, direction, up, side, resolution, twist_angle, aspect_ratio)
    
    n_pts = len(custom_points)
    output_points = []
    
    effective_resolution = max(resolution, n_pts)
    multiplier = effective_resolution // n_pts
    if multiplier < 1:
        multiplier = 1
    subdivs_per_edge = multiplier - 1
    
    for i in range(n_pts):
        p0 = custom_points[i]
        p1 = custom_points[(i + 1) % n_pts]
        output_points.append(p0)
        
        if subdivs_per_edge > 0:
            for s in range(1, subdivs_per_edge + 1):
                t = s / (subdivs_per_edge + 1)
                px = p0[0] + t * (p1[0] - p0[0])
                py = p0[1] + t * (p1[1] - p0[1])
                output_points.append((px, py))
    
    if twist_angle != 0.0:
        direction = up.cross(side).normalized()
        cos_t = math.cos(twist_angle)
        sin_t = math.sin(twist_angle)
        rotated_side = side * cos_t + up * sin_t
        rotated_up = -side * sin_t + up * cos_t
    else:
        rotated_side = side
        rotated_up = up
    
    vertices = []
    for px, py in output_points:
        scaled_x = px * radius * aspect_ratio
        scaled_y = -py * radius
        pos = center + (rotated_side * scaled_x + rotated_up * scaled_y)
        vertices.append(pos)
    
    return vertices


def generate_profile_vertices(profile_type, center, radius, side, up, resolution, aspect_ratio=1.0, twist_angle=0.0, roundness=0.3):
    """Generate profile vertices based on the specified profile type."""
    PROFILE_CIRCULAR = state.PROFILE_CIRCULAR
    PROFILE_SQUARE = state.PROFILE_SQUARE
    PROFILE_SQUARE_ROUNDED = state.PROFILE_SQUARE_ROUNDED
    PROFILE_CUSTOM = state.PROFILE_CUSTOM
    
    if roundness >= 0.999 and profile_type != PROFILE_CUSTOM:
        direction = up.cross(side).normalized()
        return create_circle_vertices(center, radius, direction, up, side, resolution, twist_angle, aspect_ratio)
    
    if profile_type == PROFILE_CIRCULAR:
        direction = up.cross(side).normalized()
        return create_circle_vertices(center, radius, direction, up, side, resolution, twist_angle, aspect_ratio)
    elif profile_type == PROFILE_SQUARE:
        return generate_square_profile(center, radius, side, up, resolution, aspect_ratio, twist_angle, roundness=0.0)
    elif profile_type == PROFILE_SQUARE_ROUNDED:
        return generate_square_profile(center, radius, side, up, resolution, aspect_ratio, twist_angle, roundness)
    elif profile_type == PROFILE_CUSTOM:
        custom_pts = state.custom_profile_points
        if custom_pts and len(custom_pts) >= 3:
            n_pts = len(custom_pts)
            multiplier = max(1, resolution // n_pts)
            actual_resolution = n_pts * multiplier
            return generate_custom_profile(center, radius, side, up, actual_resolution, aspect_ratio, twist_angle, custom_pts)
        else:
            direction = up.cross(side).normalized()
            return create_circle_vertices(center, radius, direction, up, side, resolution, twist_angle, aspect_ratio)
    else:
        direction = up.cross(side).normalized()
        return create_circle_vertices(center, radius, direction, up, side, resolution, twist_angle, aspect_ratio)


def create_tube_mesh(curve_points, radii, resolution=16, original_control_points=None, original_radii=None, aspect_ratio=1.0, global_twist=0.0, point_twists=None):
    """Create a tube mesh following a curve with varying radius."""
    if len(curve_points) < 2 or len(radii) < 2:
        return [], [], 0
    
    if hasattr(create_tube_mesh, '_smooth_roundness_cache'):
        create_tube_mesh._smooth_roundness_cache = None
    
    coordinate_systems = math_utils.create_consistent_coordinate_systems(curve_points)
    
    all_original_control_points = original_control_points
    all_original_radii = original_radii
    num_all_original_cps = len(all_original_control_points) if all_original_control_points else 0

    smooth_twists = []
    if original_control_points and point_twists and len(point_twists) == len(original_control_points):
        smooth_twists = math_utils.calculate_smooth_twists(
            original_control_points, 
            point_twists, 
            curve_points
        )
    else:
        smooth_twists = [0.0] * len(curve_points)
    
    vertices = []
    actual_verts_per_ring = resolution
    
    for i, (eval_point, eval_radius) in enumerate(zip(curve_points, radii)):
        direction, side, up = coordinate_systems[i]
        
        twist_angle = global_twist
        if i < len(smooth_twists):
            twist_angle += smooth_twists[i]
        
        profile_type = getattr(state, 'profile_global_type', state.PROFILE_CIRCULAR)
        roundness = getattr(state, 'profile_roundness', 0.3)
        
        use_per_point_roundness = False
        if hasattr(state, 'profile_point_roundness') and len(state.profile_point_roundness) > 0:
            if len(state.profile_point_roundness) == len(all_original_control_points) and all_original_control_points:
                for point_roundness in state.profile_point_roundness:
                    if abs(point_roundness - roundness) > 0.01:
                        use_per_point_roundness = True
                        break
        
        if use_per_point_roundness:
            if not hasattr(create_tube_mesh, '_smooth_roundness_cache') or create_tube_mesh._smooth_roundness_cache is None:
                create_tube_mesh._smooth_roundness_cache = math_utils.calculate_smooth_roundness(
                    all_original_control_points,
                    state.profile_point_roundness,
                    curve_points
                )
            
            if i < len(create_tube_mesh._smooth_roundness_cache):
                interpolated_roundness = create_tube_mesh._smooth_roundness_cache[i]
                roundness = interpolated_roundness if interpolated_roundness < 0.999 else 1.0
        
        circle_verts = generate_profile_vertices(
            profile_type, eval_point, eval_radius, side, up, resolution, 
            aspect_ratio, twist_angle, roundness
        )
        
        if i == 0:
            actual_verts_per_ring = len(circle_verts)
        
        vertices.extend(circle_verts)
    
    faces = []
    
    for i in range(len(curve_points) - 1):
        current_circle_start = i * actual_verts_per_ring
        next_circle_start = (i + 1) * actual_verts_per_ring
        
        for j in range(actual_verts_per_ring):
            current_vert = current_circle_start + j
            next_vert = current_circle_start + (j + 1) % actual_verts_per_ring
            next_circle_current_vert = next_circle_start + j
            next_circle_next_vert = next_circle_start + (j + 1) % actual_verts_per_ring
            face = [current_vert, next_vert, next_circle_next_vert, next_circle_current_vert]
            faces.append(face)
    
    return vertices, faces, actual_verts_per_ring


def create_hemisphere_cap(center, radius, direction, side, up, resolution=16, segments=4, is_end_cap=False, seam_ring=None, twist_angle=0.0, aspect_ratio=1.0, roundness=None):
    """Create a hemispherical cap mesh using UV-sphere method."""
    vertices = []
    faces = []
    ring_indices = []
    
    start_lat = 1 if seam_ring is not None else 0
    if seam_ring is not None:
        ring_indices.append(0)
        vertices.extend(seam_ring)
    
    for lat in range(start_lat, segments + 1):
        theta = 0.5 * math.pi * lat / segments
        ring_radius = radius * math.cos(theta)
        ring_height = radius * math.sin(theta)
        ring_center = center + direction * ring_height
        ring_start = len(vertices)
        ring_indices.append(ring_start)
        
        if lat == segments:
            pole_pos = center + direction * radius
            vertices.append(pole_pos)
            continue
        
        profile_type = getattr(state, 'profile_global_type', state.PROFILE_CIRCULAR)
        cap_roundness = roundness if roundness is not None else getattr(state, 'profile_roundness', 0.3)
        
        ring_verts = generate_profile_vertices(
            profile_type, ring_center, ring_radius, side, up, resolution, 
            aspect_ratio, twist_angle, cap_roundness
        )
        
        vertices.extend(ring_verts)
    
    for lat in range(segments):
        curr_ring_start = ring_indices[lat]
        next_ring_start = ring_indices[lat + 1]
        
        if lat == segments - 1:
            pole_index = next_ring_start
            
            for lon in range(resolution):
                curr = curr_ring_start + lon
                next_lon = curr_ring_start + (lon + 1) % resolution
                
                if is_end_cap:
                    face = [curr, next_lon, pole_index]
                else:
                    face = [curr, pole_index, next_lon]
                
                faces.append(face)
        else:
            for lon in range(resolution):
                curr = curr_ring_start + lon
                next_lon = curr_ring_start + (lon + 1) % resolution
                next_curr = next_ring_start + lon
                next_next_lon = next_ring_start + (lon + 1) % resolution
                
                if is_end_cap:
                    face = [curr, next_lon, next_next_lon, next_curr]
                else:
                    face = [curr, next_curr, next_next_lon, next_lon]
                
                faces.append(face)
    
    return vertices, faces, ring_indices


def create_planar_cap(center, radius, direction, side, up, resolution=16, is_end_cap=False, seam_ring=None, twist_angle=0.0, aspect_ratio=1.0, roundness=None, use_fill=False):
    """Create a flat circular cap mesh."""
    vertices = []
    faces = []
    
    if seam_ring is not None:
        vertices.append(center)
        ring_start = len(vertices)
        ring_indices = [ring_start]
        if is_end_cap:
            seam = list(reversed(seam_ring))
        else:
            seam = seam_ring
        vertices.extend(seam)
    else:
        vertices.append(center)
        ring_start = len(vertices)
        ring_indices = [ring_start]
        
        profile_type = getattr(state, 'profile_global_type', state.PROFILE_CIRCULAR)
        cap_roundness = roundness if roundness is not None else getattr(state, 'profile_roundness', 0.3)
        
        edge_verts = generate_profile_vertices(
            profile_type, center, radius, side, up, resolution, 
            aspect_ratio, twist_angle, cap_roundness
        )
        
        vertices.extend(edge_verts)
    
    if use_fill:
        return vertices, faces, ring_indices
    
    for i in range(resolution):
        curr = ring_start + i
        next_vert = ring_start + (i + 1) % resolution
        if is_end_cap:
            face = [0, curr, next_vert]
        else:
            face = [0, next_vert, curr]
        faces.append(face)
    
    return vertices, faces, ring_indices


def fill_boundary_loops(mesh, fill_boundaries):
    """Fill boundary loops using bmesh for better triangulation."""
    import bmesh
    
    if not fill_boundaries:
        return
    
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bm.verts.ensure_lookup_table()
    bm.edges.ensure_lookup_table()
    
    for name, vert_indices in fill_boundaries:
        boundary_verts = [bm.verts[i] for i in vert_indices if i < len(bm.verts)]
        if len(boundary_verts) < 3:
            continue
        
        boundary_edges = []
        for i in range(len(boundary_verts)):
            v1 = boundary_verts[i]
            v2 = boundary_verts[(i + 1) % len(boundary_verts)]
            for e in v1.link_edges:
                if e.other_vert(v1) == v2:
                    boundary_edges.append(e)
                    break
        
        if len(boundary_edges) >= 3:
            try:
                bmesh.ops.triangle_fill(bm, edges=boundary_edges, use_beauty=True)
            except Exception as e:
                print(f"[WARNING] Flex: Failed to fill {name} cap boundary: {e}")
    
    bm.to_mesh(mesh)
    bm.free()


def create_flex_mesh(curve_points, radii, resolution=16, cap_segments=4, original_control_points=None, original_radii=None, aspect_ratio=1.0, global_twist=0.0, point_twists=None, start_cap_type=1, end_cap_type=1):
    """Create a flex mesh tube with configurable end caps."""
    if len(curve_points) < 2 or len(radii) < 2:
        return [], [], []
    
    tube_vertices, tube_faces, actual_resolution = create_tube_mesh(
        curve_points, 
        radii, 
        resolution,
        original_control_points=original_control_points,
        original_radii=original_radii,
        aspect_ratio=aspect_ratio,
        global_twist=global_twist,
        point_twists=point_twists
    )
    resolution = actual_resolution

    coordinate_systems = math_utils.create_consistent_coordinate_systems(curve_points)
    start_direction, start_side, start_up = coordinate_systems[0]
    end_direction, end_side, end_up = coordinate_systems[-1]
    start_direction = -start_direction
    
    vertices = []
    faces = []
    start_cap_vertices = []
    start_cap_faces = []
    start_ring_indices = []
    end_cap_vertices = []
    end_cap_faces = []
    end_ring_indices = []
    
    tube_start_ring = [tube_vertices[i] for i in range(resolution)]
    tube_end_ring = [tube_vertices[-resolution + i] for i in range(resolution)]

    if start_cap_type > 0:
        start_point = curve_points[0]
        start_radius = radii[0]
        start_twist = global_twist
        if point_twists and len(point_twists) > 0:
            start_twist += point_twists[0]
        
        start_roundness = None
        if hasattr(state, 'profile_point_roundness') and len(state.profile_point_roundness) > 0:
            if len(state.profile_point_roundness) == len(original_control_points) and original_control_points:
                start_roundness = state.profile_point_roundness[0]
        
        if start_cap_type == 1:
            start_cap_vertices, start_cap_faces, start_ring_indices = create_hemisphere_cap(
                start_point, start_radius, start_direction, start_side, start_up, 
                resolution, cap_segments, False, seam_ring=tube_start_ring, twist_angle=start_twist, aspect_ratio=aspect_ratio, roundness=start_roundness)
        elif start_cap_type == 2:
            use_fill = (state.profile_global_type == state.PROFILE_CUSTOM)
            start_cap_vertices, start_cap_faces, start_ring_indices = create_planar_cap(
                start_point, start_radius, start_direction, start_side, start_up,
                resolution, False, seam_ring=tube_start_ring, twist_angle=start_twist, aspect_ratio=aspect_ratio, roundness=start_roundness, use_fill=use_fill)

    if end_cap_type > 0:
        end_point = curve_points[-1]
        end_radius = radii[-1]
        end_twist = global_twist
        if point_twists and len(point_twists) > 0:
            end_twist += point_twists[-1]
        
        end_roundness = None
        if hasattr(state, 'profile_point_roundness') and len(state.profile_point_roundness) > 0:
            if len(state.profile_point_roundness) == len(original_control_points) and original_control_points:
                end_roundness = state.profile_point_roundness[-1]
        
        if end_cap_type == 1:
            end_cap_vertices, end_cap_faces, end_ring_indices = create_hemisphere_cap(
                end_point, end_radius, end_direction, end_side, end_up,
                resolution, cap_segments, True, seam_ring=tube_end_ring, twist_angle=end_twist, aspect_ratio=aspect_ratio, roundness=end_roundness)
        elif end_cap_type == 2:
            use_fill = (state.profile_global_type == state.PROFILE_CUSTOM)
            end_cap_vertices, end_cap_faces, end_ring_indices = create_planar_cap(
                end_point, end_radius, end_direction, end_side, end_up,
                resolution, True, seam_ring=tube_end_ring, twist_angle=end_twist, aspect_ratio=aspect_ratio, roundness=end_roundness, use_fill=use_fill)
    
    tube_offset = len(vertices)
    vertices.extend(tube_vertices)
    for face in tube_faces:
        faces.append([v + tube_offset for v in face])
    
    if state.start_cap_type > 0:
        start_cap_internal_offset = len(vertices)
        
        if state.start_cap_type == 1:
            internal_vertices = start_cap_vertices[resolution:]
            vertices.extend(internal_vertices)
            
            for face in start_cap_faces:
                remapped_face = []
                for v_idx in face:
                    if v_idx < resolution:
                        remapped_face.append(tube_offset + v_idx)
                    else:
                        internal_idx = v_idx - resolution
                        remapped_face.append(start_cap_internal_offset + internal_idx)
                faces.append(remapped_face)
        
        elif state.start_cap_type == 2:
            vertices.append(start_cap_vertices[0])
            
            for face in start_cap_faces:
                remapped_face = []
                for v_idx in face:
                    if v_idx == 0:
                        remapped_face.append(start_cap_internal_offset)
                    else:
                        border_idx = v_idx - 1
                        remapped_face.append(tube_offset + border_idx)
                faces.append(remapped_face)
    
    if state.end_cap_type > 0:
        end_cap_internal_offset = len(vertices)
        
        if state.end_cap_type == 1:
            internal_vertices = end_cap_vertices[resolution:]
            vertices.extend(internal_vertices)
            
            for face in end_cap_faces:
                remapped_face = []
                for v_idx in face:
                    if v_idx < resolution:
                        tube_end_start = len(tube_vertices) - resolution
                        remapped_face.append(tube_offset + tube_end_start + v_idx)
                    else:
                        internal_idx = v_idx - resolution
                        remapped_face.append(end_cap_internal_offset + internal_idx)
                faces.append(remapped_face)
        
        elif state.end_cap_type == 2:
            vertices.append(end_cap_vertices[0])
            
            for face in end_cap_faces:
                remapped_face = []
                for v_idx in face:
                    if v_idx == 0:
                        remapped_face.append(end_cap_internal_offset)
                    else:
                        border_idx = v_idx - 1
                        tube_end_start = len(tube_vertices) - resolution
                        remapped_face.append(tube_offset + tube_end_start + border_idx)
                faces.append(remapped_face)
    
    fill_boundaries = []
    is_custom_profile = (state.profile_global_type == state.PROFILE_CUSTOM)
    
    if is_custom_profile and state.start_cap_type == 2:
        start_boundary = list(range(tube_offset, tube_offset + resolution))
        fill_boundaries.append(('start', start_boundary))
    
    if is_custom_profile and state.end_cap_type == 2:
        tube_end_start = tube_offset + len(tube_vertices) - resolution
        end_boundary = list(range(tube_end_start, tube_end_start + resolution))
        fill_boundaries.append(('end', end_boundary))
    
    return vertices, faces, fill_boundaries


def create_flex_mesh_from_curve(context, curve_points_3d, radii_3d, resolution=16, segments=32, tensions=None, no_tangent_points=None, is_preview=False):
    """Create a flex mesh that follows the curve with varying thickness."""
    if len(curve_points_3d) < 2 or len(radii_3d) < 2:
        return None
    
    # Check if B-spline mode is enabled
    use_bspline = getattr(state, 'bspline_mode', False)
    
    # Check if adaptive segmentation is enabled
    should_run_adaptive = getattr(state, 'adaptive_segmentation', False) and len(curve_points_3d) >= 3
    
    if should_run_adaptive:
        # Adaptive segmentation logic - adds more segments in high-curvature areas
        base_segments = segments
        
        arc_length = math_utils.get_polyline_arc_length(curve_points_3d) 
        points_per_unit_length = 10
        min_analysis_density = base_segments * 5
        analysis_density = max(min_analysis_density, int(arc_length * points_per_unit_length))
        
        if use_bspline:
            analysis_points = math_utils.bspline_cubic_open_uniform(
                curve_points_3d, analysis_density + 1
            )
        else:
            analysis_points = math_utils.interpolate_curve_3d(
                curve_points_3d,
                num_points=analysis_density + 1,
                sharp_points=no_tangent_points,
                tensions=tensions
            )
        
        curvature_values = [0.0] * len(analysis_points)
        if len(analysis_points) >= 3:
            for i in range(1, len(analysis_points)-1):
                v_prev = (analysis_points[i] - analysis_points[i-1]).normalized()
                v_next = (analysis_points[i+1] - analysis_points[i]).normalized()
                dot = max(-1.0, min(1.0, v_prev.dot(v_next)))
                angle = math.degrees(math.acos(dot))
                curvature_values[i] = angle
        
        curvature_maxima = []
        if len(analysis_points) >= 3:
            for i in range(1, len(analysis_points)-1):
                if curvature_values[i] > 1:
                    curvature_maxima.append((i, curvature_values[i]))
        curvature_maxima.sort(key=lambda x: x[1], reverse=True)
        
        density_map = [1.0] * analysis_density
        window_frac = 0.16
        window_size = int(window_frac * analysis_density)
        if not curvature_maxima:
            for i in range(1, len(analysis_points)-1):
                if curvature_values[i] > 2:
                    curvature_maxima.append((i, curvature_values[i]))
        
        for idx, curvature in curvature_maxima:
            min_window = max(5, int(window_size * 0.2))
            adaptive_window = max(min_window, int(window_size * min(curvature / 20.0, 1.0)))
            for offset in range(-adaptive_window, adaptive_window + 1):
                pos = idx + offset
                if 0 <= pos < len(density_map):
                    falloff = 1.0 - abs(offset) / adaptive_window
                    falloff = falloff * falloff
                    base_multiplier = 2.0
                    curve_multiplier = 5.0 * min(curvature / 20.0, 1.0)
                    multiplier = (base_multiplier + curve_multiplier) * falloff
                    density_map[pos] = max(density_map[pos], multiplier)
        
        target_points = base_segments + int(sum(dm - 1.0 for dm in density_map) * base_segments / len(density_map)) + 1
        
        smooth_curve_points_3d = []
        if analysis_points:
            smooth_curve_points_3d.append(curve_points_3d[0].copy())
            if len(analysis_points) > 1:
                total_density = sum(density_map)
                if total_density > 0:
                    points_per_density = (target_points - 2) / total_density if target_points > 2 else 0
                    density_factor_0 = density_map[0] if density_map else 1.0
                    initial_step = 1.0 / (density_factor_0 * points_per_density) if points_per_density > 0 else 1.0
                    current_pos = max(0.5, initial_step)
                    end_threshold = len(analysis_points) - 1.5
                    while current_pos < end_threshold and len(smooth_curve_points_3d) < target_points - 1:
                        idx = int(current_pos)
                        if idx + 1 < len(analysis_points):
                            t = current_pos - idx
                            point = analysis_points[idx].lerp(analysis_points[idx+1], t) if 0.0 < t < 1.0 else analysis_points[idx]
                            smooth_curve_points_3d.append(point)
                            density_factor = density_map[min(idx, len(density_map)-1)]
                            step = 1.0 / (density_factor * points_per_density) if points_per_density > 0 else float('inf')
                            current_pos += max(0.1, step) if step != float('inf') else 1.0
                        else:
                            break
                smooth_curve_points_3d.append(curve_points_3d[-1].copy())
            elif len(analysis_points) == 1:
                if not smooth_curve_points_3d:
                    smooth_curve_points_3d.append(curve_points_3d[0].copy())
        else:
            if use_bspline:
                smooth_curve_points_3d = math_utils.bspline_cubic_open_uniform(curve_points_3d, segments + 1)
            else:
                smooth_curve_points_3d = math_utils.interpolate_curve_3d(curve_points_3d, num_points=segments + 1, sharp_points=no_tangent_points, tensions=tensions)

        if len(smooth_curve_points_3d) < 2 and len(curve_points_3d) >= 2:
            smooth_curve_points_3d = math_utils.interpolate_curve_3d(curve_points_3d, num_points=segments + 1, sharp_points=no_tangent_points, tensions=tensions)

        if len(smooth_curve_points_3d) > 2:
            start_radius = radii_3d[0]
            end_radius = radii_3d[-1]
            min_dist_start = start_radius * 0.15
            min_dist_end = end_radius * 0.15
            
            filtered_points = [smooth_curve_points_3d[0]]
            for pt in smooth_curve_points_3d[1:-1]:
                dist_to_start = (pt - smooth_curve_points_3d[0]).length
                dist_to_end = (pt - smooth_curve_points_3d[-1]).length
                if dist_to_start >= min_dist_start and dist_to_end >= min_dist_end:
                    filtered_points.append(pt)
            filtered_points.append(smooth_curve_points_3d[-1])
            smooth_curve_points_3d = filtered_points

        smooth_radii_3d = math_utils.calculate_smooth_radii(curve_points_3d, radii_3d, smooth_curve_points_3d, tensions=tensions, sharp_points=no_tangent_points)
        
        if len(smooth_radii_3d) >= 2:
            smooth_radii_3d[0] = radii_3d[0]
            smooth_radii_3d[-1] = radii_3d[-1]
    else:
        # Standard interpolation without adaptive segmentation
        if use_bspline:
            smooth_curve_points_3d = math_utils.bspline_cubic_open_uniform(
                curve_points_3d,
                segments + 1
            )
        else:
            smooth_curve_points_3d = math_utils.interpolate_curve_3d(
                curve_points_3d, 
                num_points=segments + 1,
                sharp_points=no_tangent_points,
                tensions=tensions
            )
        
        smooth_radii_3d = math_utils.calculate_smooth_radii(
            curve_points_3d,
            radii_3d,
            smooth_curve_points_3d,
            tensions=tensions,
            sharp_points=no_tangent_points
        )
    
    vertices, faces, fill_boundaries = create_flex_mesh(
        smooth_curve_points_3d,
        smooth_radii_3d,
        resolution=resolution,
        cap_segments=4,
        original_control_points=curve_points_3d,
        original_radii=radii_3d,
        aspect_ratio=getattr(state, 'profile_aspect_ratio', 1.0),
        global_twist=getattr(state, 'profile_global_twist', 0.0),
        point_twists=getattr(state, 'profile_point_twists', None),
        start_cap_type=getattr(state, 'start_cap_type', 1),
        end_cap_type=getattr(state, 'end_cap_type', 1)
    )
    
    mesh = bpy.data.meshes.new("Flex_Mesh")
    mesh.from_pydata(vertices, [], faces)
    
    if fill_boundaries:
        fill_boundary_loops(mesh, fill_boundaries)
    
    mesh.update()
    
    obj = bpy.data.objects.new("Flex", mesh)
    context.collection.objects.link(obj)
    
    if state.object_matrix_world is not None:
        obj.matrix_world = state.object_matrix_world
    
    context.view_layer.objects.active = obj
    obj.select_set(True)
    
    if is_preview:
        mat = bpy.data.materials.new("Flex_Preview_Material")
        mat.use_nodes = True
        nodes = mat.node_tree.nodes
        nodes.clear()
        
        bsdf = nodes.new(type='ShaderNodeBsdfPrincipled')
        bsdf.location = (0, 0)
        bsdf.inputs['Base Color'].default_value = (0.00127, 0.169, 0.376, 1.0)
        bsdf.inputs['Metallic'].default_value = 0.0
        bsdf.inputs['Roughness'].default_value = 0.8
        
        if 'Specular' in bsdf.inputs:
            bsdf.inputs['Specular'].default_value = 0.5
        elif 'Specular IOR Level' in bsdf.inputs:
            bsdf.inputs['Specular IOR Level'].default_value = 0.5
        
        output = nodes.new(type='ShaderNodeOutputMaterial')
        output.location = (300, 0)
        links = mat.node_tree.links
        links.new(bsdf.outputs['BSDF'], output.inputs['Surface'])
        
        if len(obj.data.materials) == 0:
            obj.data.materials.append(mat)
        else:
            obj.data.materials[0] = mat
    
    return obj


def update_preview_mesh(context, curve_points_3d, radii_3d, resolution=16, segments=32):
    """Create or update the preview mesh based on the current curve."""
    if len(curve_points_3d) < 2 or len(radii_3d) < 2:
        return
    
    if state.preview_mesh_obj is None or state.preview_mesh_obj.name not in bpy.data.objects:
        state.preview_mesh_obj = create_flex_mesh_from_curve(
            context,
            curve_points_3d,
            radii_3d,
            resolution=resolution,
            segments=segments,
            tensions=state.point_tensions,
            no_tangent_points=state.no_tangent_points,
            is_preview=True
        )
        if state.preview_mesh_obj is not None:
            state.preview_mesh_obj.display_type = 'SOLID'
            state.preview_mesh_obj.show_wire = True
            state.preview_mesh_obj.show_all_edges = True
            if hasattr(state.preview_mesh_obj, 'show_in_front'):
                state.preview_mesh_obj.show_in_front = False
            if getattr(state, 'mirror_mode_active', False):
                apply_mirror_modifier(state.preview_mesh_obj, True)
    else:
        should_run_adaptive_logic = state.adaptive_segmentation and len(curve_points_3d) >= 3

        if should_run_adaptive_logic:
            base_segments = segments
            
            arc_length = math_utils.get_polyline_arc_length(curve_points_3d) 
            points_per_unit_length = 10
            min_analysis_density = base_segments * 5
            analysis_density = max(min_analysis_density, int(arc_length * points_per_unit_length))
            
            if getattr(state, 'bspline_mode', False):
                analysis_points = math_utils.bspline_cubic_open_uniform(
                    curve_points_3d, analysis_density + 1
                )
            else:
                analysis_points = math_utils.interpolate_curve_3d(
                    curve_points_3d,
                    num_points=analysis_density + 1,
                    sharp_points=state.no_tangent_points,
                    tensions=state.point_tensions
                )
            
            curvature_values = [0.0] * len(analysis_points)
            if len(analysis_points) >= 3:
                for i in range(1, len(analysis_points)-1):
                    v_prev = (analysis_points[i] - analysis_points[i-1]).normalized()
                    v_next = (analysis_points[i+1] - analysis_points[i]).normalized()
                    dot = max(-1.0, min(1.0, v_prev.dot(v_next)))
                    angle = math.degrees(math.acos(dot))
                    curvature_values[i] = angle
            
            curvature_maxima = []
            if len(analysis_points) >= 3:
                for i in range(1, len(analysis_points)-1):
                    if curvature_values[i] > 1:
                        curvature_maxima.append((i, curvature_values[i]))
            curvature_maxima.sort(key=lambda x: x[1], reverse=True)
            
            density_map = [1.0] * analysis_density
            window_frac = 0.16
            window_size = int(window_frac * analysis_density)
            if not curvature_maxima:
                for i in range(1, len(analysis_points)-1):
                    if curvature_values[i] > 2:
                        curvature_maxima.append((i, curvature_values[i]))
            
            for idx, curvature in curvature_maxima:
                min_window = max(5, int(window_size * 0.2))
                adaptive_window = max(min_window, int(window_size * min(curvature / 20.0, 1.0)))
                for offset in range(-adaptive_window, adaptive_window + 1):
                    pos = idx + offset
                    if 0 <= pos < len(density_map):
                        falloff = 1.0 - abs(offset) / adaptive_window
                        falloff = falloff * falloff
                        base_multiplier = 2.0
                        curve_multiplier = 5.0 * min(curvature / 20.0, 1.0)
                        multiplier = (base_multiplier + curve_multiplier) * falloff
                        density_map[pos] = max(density_map[pos], multiplier)
            
            target_points = base_segments + int(sum(dm - 1.0 for dm in density_map) * base_segments / len(density_map)) + 1
            
            smooth_curve_points_3d = []
            if analysis_points:
                smooth_curve_points_3d.append(curve_points_3d[0].copy())
                if len(analysis_points) > 1:
                    total_density = sum(density_map)
                    if total_density > 0:
                        points_per_density = (target_points - 2) / total_density if target_points > 2 else 0
                        density_factor_0 = density_map[0] if density_map else 1.0
                        initial_step = 1.0 / (density_factor_0 * points_per_density) if points_per_density > 0 else 1.0
                        current_pos = max(0.5, initial_step)
                        end_threshold = len(analysis_points) - 1.5
                        while current_pos < end_threshold and len(smooth_curve_points_3d) < target_points - 1:
                            idx = int(current_pos)
                            if idx + 1 < len(analysis_points):
                                t = current_pos - idx
                                point = analysis_points[idx].lerp(analysis_points[idx+1], t) if 0.0 < t < 1.0 else analysis_points[idx]
                                smooth_curve_points_3d.append(point)
                                density_factor = density_map[min(idx, len(density_map)-1)]
                                step = 1.0 / (density_factor * points_per_density) if points_per_density > 0 else float('inf')
                                current_pos += max(0.1, step) if step != float('inf') else 1.0
                            else:
                                break
                    smooth_curve_points_3d.append(curve_points_3d[-1].copy())
                elif len(analysis_points) == 1:
                    if not smooth_curve_points_3d:
                        smooth_curve_points_3d.append(curve_points_3d[0].copy())
            else:
                if getattr(state, 'bspline_mode', False):
                    smooth_curve_points_3d = math_utils.bspline_cubic_open_uniform(curve_points_3d, segments + 1)
                else:
                    smooth_curve_points_3d = math_utils.interpolate_curve_3d(curve_points_3d, num_points=segments + 1, sharp_points=state.no_tangent_points, tensions=state.point_tensions)

            if len(smooth_curve_points_3d) < 2 and len(curve_points_3d) >= 2:
                smooth_curve_points_3d = math_utils.interpolate_curve_3d(curve_points_3d, num_points=segments + 1, sharp_points=state.no_tangent_points, tensions=state.point_tensions)

            if len(smooth_curve_points_3d) > 2:
                start_radius = radii_3d[0]
                end_radius = radii_3d[-1]
                min_dist_start = start_radius * 0.15
                min_dist_end = end_radius * 0.15
                
                filtered_points = [smooth_curve_points_3d[0]]
                for pt in smooth_curve_points_3d[1:-1]:
                    dist_to_start = (pt - smooth_curve_points_3d[0]).length
                    dist_to_end = (pt - smooth_curve_points_3d[-1]).length
                    if dist_to_start >= min_dist_start and dist_to_end >= min_dist_end:
                        filtered_points.append(pt)
                filtered_points.append(smooth_curve_points_3d[-1])
                smooth_curve_points_3d = filtered_points

            smooth_radii_3d = math_utils.calculate_smooth_radii(curve_points_3d, radii_3d, smooth_curve_points_3d, tensions=state.point_tensions, sharp_points=state.no_tangent_points)
            
            if len(smooth_radii_3d) >= 2:
                smooth_radii_3d[0] = radii_3d[0]
                smooth_radii_3d[-1] = radii_3d[-1]
            
            vertices, faces, fill_boundaries = create_flex_mesh(
                smooth_curve_points_3d, 
                smooth_radii_3d, 
                resolution=resolution, 
                cap_segments=4, 
                original_control_points=curve_points_3d, 
                original_radii=radii_3d,
                aspect_ratio=state.profile_aspect_ratio,
                global_twist=state.profile_global_twist,
                point_twists=state.profile_point_twists,
                start_cap_type=state.start_cap_type,
                end_cap_type=state.end_cap_type
            )
            
            mesh = state.preview_mesh_obj.data
            mesh.clear_geometry()
            if vertices is not None:
                mesh.from_pydata(vertices, [], faces)
                if fill_boundaries:
                    fill_boundary_loops(mesh, fill_boundaries)
                mesh.update()
            else:
                mesh.update()
        else:
            if getattr(state, 'bspline_mode', False):
                smooth_curve_points_3d = math_utils.bspline_cubic_open_uniform(
                    curve_points_3d, segments + 1
                )
            else:
                smooth_curve_points_3d = math_utils.interpolate_curve_3d(
                    curve_points_3d,
                    num_points=segments + 1,
                    sharp_points=state.no_tangent_points,
                    tensions=state.point_tensions
                )
            smooth_radii_3d = math_utils.calculate_smooth_radii(
                curve_points_3d,
                radii_3d,
                smooth_curve_points_3d,
                tensions=state.point_tensions,
                sharp_points=state.no_tangent_points
            )
            
            if len(smooth_radii_3d) >= 2:
                smooth_radii_3d[0] = radii_3d[0]
                smooth_radii_3d[-1] = radii_3d[-1]
            
            vertices, faces, fill_boundaries = create_flex_mesh(
                smooth_curve_points_3d,
                smooth_radii_3d,
                resolution=resolution,
                cap_segments=4,
                original_control_points=curve_points_3d,
                original_radii=radii_3d,
                aspect_ratio=state.profile_aspect_ratio,
                global_twist=state.profile_global_twist,
                point_twists=state.profile_point_twists,
                start_cap_type=state.start_cap_type,
                end_cap_type=state.end_cap_type
            )
            mesh = state.preview_mesh_obj.data
            mesh.clear_geometry()
            if vertices is not None:
                mesh.from_pydata(vertices, [], faces)
                if fill_boundaries:
                    fill_boundary_loops(mesh, fill_boundaries)
                mesh.update()
            else:
                mesh.update()


def register():
    pass


def unregister():
    pass
