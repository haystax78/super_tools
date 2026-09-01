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


def _sample_helix_profile(control_t_values, control_values, target_t):
    """Sample helix profile values using smooth cubic interpolation."""
    if not control_values:
        return 0.0
    if len(control_values) == 1:
        return float(control_values[0])
    if target_t <= control_t_values[0]:
        return float(control_values[0])
    if target_t >= control_t_values[-1]:
        return float(control_values[-1])

    last_idx = len(control_t_values) - 1
    for idx in range(1, len(control_t_values)):
        t0 = control_t_values[idx - 1]
        t1 = control_t_values[idx]
        if target_t <= t1:
            v0 = float(control_values[idx - 1])
            v1 = float(control_values[idx])
            denom = t1 - t0
            if abs(denom) <= 1e-8:
                return v1

            prev_idx = max(0, idx - 2)
            next_idx = min(last_idx, idx + 1)
            t_prev = control_t_values[prev_idx]
            t_next = control_t_values[next_idx]
            v_prev = float(control_values[prev_idx])
            v_next = float(control_values[next_idx])

            denom_prev = max(1e-8, t1 - t_prev)
            denom_next = max(1e-8, t_next - t0)
            slope0 = (v1 - v_prev) / denom_prev
            slope1 = (v_next - v0) / denom_next

            u = (target_t - t0) / denom
            u2 = u * u
            u3 = u2 * u
            h00 = (2.0 * u3) - (3.0 * u2) + 1.0
            h10 = u3 - (2.0 * u2) + u
            h01 = (-2.0 * u3) + (3.0 * u2)
            h11 = u3 - u2
            return (
                (h00 * v0)
                + (h10 * denom * slope0)
                + (h01 * v1)
                + (h11 * denom * slope1)
            )

    return float(control_values[-1])


def _compute_smooth_curve_points(
    curve_points_3d,
    radii_3d,
    segments,
    no_tangent_points,
    tensions,
    is_closed_loop,
    use_bspline,
    adaptive,
):
    """Compute the densely sampled smooth curve for the tube mesh.

    Handles both adaptive (curvature-aware) segmentation and uniform
    sampling. For adaptive mode, samples more densely in high-curvature
    regions and wraps correctly across the seam of a closed loop.
    """
    def _uniform_sample(num_points):
        if use_bspline:
            return math_utils.bspline_cubic_open_uniform(
                curve_points_3d, num_points, is_closed=is_closed_loop
            )
        return math_utils.interpolate_curve_3d(
            curve_points_3d,
            num_points=num_points,
            sharp_points=no_tangent_points,
            tensions=tensions,
            is_closed=is_closed_loop,
        )

    if not adaptive or len(curve_points_3d) < 3:
        return _uniform_sample(segments + 1)

    base_segments = segments
    arc_length = math_utils.get_polyline_arc_length(curve_points_3d)
    points_per_unit_length = 10
    min_analysis_density = base_segments * 5
    analysis_density = max(min_analysis_density, int(arc_length * points_per_unit_length))

    analysis_points = _uniform_sample(analysis_density + 1)

    curvature_values = [0.0] * len(analysis_points)
    if len(analysis_points) >= 3:
        for i in range(1, len(analysis_points) - 1):
            v_prev = (analysis_points[i] - analysis_points[i - 1]).normalized()
            v_next = (analysis_points[i + 1] - analysis_points[i]).normalized()
            dot = max(-1.0, min(1.0, v_prev.dot(v_next)))
            curvature_values[i] = math.degrees(math.acos(dot))
        if is_closed_loop:
            v_prev = (analysis_points[0] - analysis_points[-1]).normalized()
            v_next = (analysis_points[1] - analysis_points[0]).normalized()
            dot = max(-1.0, min(1.0, v_prev.dot(v_next)))
            curvature_values[0] = math.degrees(math.acos(dot))

    curvature_maxima = []
    if len(analysis_points) >= 3:
        search_range = (
            range(len(analysis_points) - 1) if is_closed_loop
            else range(1, len(analysis_points) - 1)
        )
        for i in search_range:
            if curvature_values[i] > 1:
                curvature_maxima.append((i, curvature_values[i]))
    curvature_maxima.sort(key=lambda x: x[1], reverse=True)

    density_map = [1.0] * analysis_density
    window_frac = 0.16
    window_size = int(window_frac * analysis_density)
    if not curvature_maxima:
        for i in range(1, len(analysis_points) - 1):
            if curvature_values[i] > 2:
                curvature_maxima.append((i, curvature_values[i]))

    n_density = len(density_map)
    for idx, curvature in curvature_maxima:
        min_window = max(5, int(window_size * 0.2))
        adaptive_window = max(min_window, int(window_size * min(curvature / 20.0, 1.0)))
        for offset in range(-adaptive_window, adaptive_window + 1):
            if is_closed_loop:
                pos = (idx + offset) % n_density
            else:
                pos = idx + offset
                if not (0 <= pos < n_density):
                    continue
            falloff = 1.0 - abs(offset) / adaptive_window
            falloff = falloff * falloff
            base_multiplier = 2.0
            curve_multiplier = 5.0 * min(curvature / 20.0, 1.0)
            multiplier = (base_multiplier + curve_multiplier) * falloff
            density_map[pos] = max(density_map[pos], multiplier)

    target_points = (
        base_segments
        + int(sum(dm - 1.0 for dm in density_map) * base_segments / len(density_map))
        + 1
    )

    smooth_curve_points_3d = []
    if analysis_points:
        smooth_curve_points_3d.append(analysis_points[0].copy())
        if len(analysis_points) > 1:
            total_density = sum(density_map)
            if total_density > 0:
                points_per_density = (target_points - 2) / total_density if target_points > 2 else 0
                density_factor_0 = density_map[0] if density_map else 1.0
                initial_step = 1.0 / (density_factor_0 * points_per_density) if points_per_density > 0 else 1.0
                current_pos = max(0.5, initial_step)
                # For closed loops, sample all the way around (including the wrap-around region).
                # For open curves, stop before the end so the explicit ctrl[-1] append below
                # doesn't duplicate a nearby sample.
                end_threshold = (
                    (len(analysis_points) - 0.5) if is_closed_loop
                    else (len(analysis_points) - 1.5)
                )
                target_cap = target_points if is_closed_loop else (target_points - 1)
                while current_pos < end_threshold and len(smooth_curve_points_3d) < target_cap:
                    idx = int(current_pos)
                    if idx + 1 < len(analysis_points):
                        t = current_pos - idx
                        point = (
                            analysis_points[idx].lerp(analysis_points[idx + 1], t)
                            if 0.0 < t < 1.0
                            else analysis_points[idx]
                        )
                        smooth_curve_points_3d.append(point)
                        density_factor = density_map[min(idx, len(density_map) - 1)]
                        step = 1.0 / (density_factor * points_per_density) if points_per_density > 0 else float('inf')
                        current_pos += max(0.1, step) if step != float('inf') else 1.0
                    else:
                        break
            if not is_closed_loop:
                smooth_curve_points_3d.append(curve_points_3d[-1].copy())
        elif len(analysis_points) == 1:
            if not smooth_curve_points_3d:
                smooth_curve_points_3d.append(curve_points_3d[0].copy())
    else:
        smooth_curve_points_3d = _uniform_sample(segments + 1)

    if len(smooth_curve_points_3d) < 2 and len(curve_points_3d) >= 2:
        smooth_curve_points_3d = math_utils.interpolate_curve_3d(
            curve_points_3d,
            num_points=segments + 1,
            sharp_points=no_tangent_points,
            tensions=tensions,
            is_closed=is_closed_loop,
        )

    if len(smooth_curve_points_3d) > 2 and not is_closed_loop:
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

    return smooth_curve_points_3d


def _apply_helix_to_curve_points(curve_points, original_control_points=None):
    """Return evaluated points with non-destructive helix offset applied."""
    if len(curve_points) < 2:
        return [point.copy() for point in curve_points]

    cumulative_lengths = [0.0]
    for idx in range(1, len(curve_points)):
        seg_len = (curve_points[idx] - curve_points[idx - 1]).length
        cumulative_lengths.append(cumulative_lengths[-1] + seg_len)

    total_length = cumulative_lengths[-1]
    if total_length <= 1e-8:
        return [point.copy() for point in curve_points]

    coordinate_systems = math_utils.create_consistent_coordinate_systems(
        curve_points,
    )

    is_closed_loop = (getattr(state, 'start_cap_type', 1) == 3 or getattr(state, 'end_cap_type', 1) == 3)

    control_points = (
        original_control_points
        if original_control_points and len(original_control_points) >= 2
        else curve_points
    )
    n_ctrl = len(control_points)
    n_ctrl_segs = n_ctrl if is_closed_loop else n_ctrl - 1
    control_lengths = [0.0]
    for idx in range(n_ctrl_segs):
        next_idx = (idx + 1) % n_ctrl
        seg_len = (control_points[next_idx] - control_points[idx]).length
        control_lengths.append(control_lengths[-1] + seg_len)
    control_total = control_lengths[-1]
    if control_total > 1e-8:
        control_t_values = [length / control_total for length in control_lengths]
    else:
        count = max(1, n_ctrl_segs)
        control_t_values = [i / count for i in range(n_ctrl_segs + 1)]

    point_mags = list(getattr(state, 'helix_point_magnitudes', []) or [])
    point_freqs = list(getattr(state, 'helix_point_frequencies', []) or [])
    point_slants = list(getattr(state, 'helix_point_slants', []) or [])
    control_count = len(control_points)
    if len(point_mags) < control_count:
        point_mags.extend(
            [float(getattr(state, 'helix_magnitude', 0.0))]
            * (control_count - len(point_mags))
        )
    if len(point_freqs) < control_count:
        point_freqs.extend(
            [float(getattr(state, 'helix_frequency', 0.0))]
            * (control_count - len(point_freqs))
        )
    if len(point_slants) < control_count:
        point_slants.extend(
            [float(getattr(state, 'helix_slant', 0.0))]
            * (control_count - len(point_slants))
        )
    point_mags = point_mags[:control_count]
    point_freqs = point_freqs[:control_count]
    point_slants = point_slants[:control_count]

    if is_closed_loop:
        point_mags = point_mags + [point_mags[0]]
        point_freqs = point_freqs + [point_freqs[0]]
        point_slants = point_slants + [point_slants[0]]
        closing_seg = (curve_points[0] - curve_points[-1]).length
        if total_length > 1e-8:
            total_length = total_length + closing_seg

    if (
        all(abs(float(val)) <= 1e-8 for val in point_mags)
        or all(float(val) <= 1e-8 for val in point_freqs)
    ):
        return [point.copy() for point in curve_points]

    if is_closed_loop:
        start_taper_end = 0.0
        end_taper_start = 1.0
    elif n_ctrl > 2:
        start_taper_end = control_t_values[1]
        end_taper_start = control_t_values[-2]
    else:
        start_taper_end = 0.25
        end_taper_start = 0.75

    endpoint_mode = getattr(
        state,
        'helix_endpoint_mode',
        state.HELIX_ENDPOINT_SMOOTH_TAPER,
    )
    start_return_frequency = _sample_helix_profile(
        control_t_values,
        point_freqs,
        start_taper_end,
    )
    end_return_frequency = _sample_helix_profile(
        control_t_values,
        point_freqs,
        end_taper_start,
    )
    start_return_phase = 2.0 * math.pi * start_return_frequency * start_taper_end
    end_return_phase = 2.0 * math.pi * end_return_frequency * end_taper_start
    phase_softness = 0.35
    start_phase_transition = max(1e-8, start_taper_end * phase_softness)
    end_phase_transition = max(1e-8, (1.0 - end_taper_start) * phase_softness)
    phase_epsilon = 1e-5
    start_previous_t = max(0.0, start_taper_end - phase_epsilon)
    start_previous_frequency = _sample_helix_profile(
        control_t_values,
        point_freqs,
        start_previous_t,
    )
    start_previous_phase = 2.0 * math.pi * start_previous_frequency * start_previous_t
    start_phase_velocity = (
        (start_return_phase - start_previous_phase)
        / max(1e-8, start_taper_end - start_previous_t)
    )
    end_next_t = min(1.0, end_taper_start + phase_epsilon)
    end_next_frequency = _sample_helix_profile(
        control_t_values,
        point_freqs,
        end_next_t,
    )
    end_next_phase = 2.0 * math.pi * end_next_frequency * end_next_t
    end_phase_velocity = (
        (end_next_phase - end_return_phase)
        / max(1e-8, end_next_t - end_taper_start)
    )
    start_fixed_phase = start_return_phase - 0.5 * start_phase_velocity * start_phase_transition
    end_fixed_phase = end_return_phase + 0.5 * end_phase_velocity * end_phase_transition

    helix_points = []
    for idx, point in enumerate(curve_points):
        t = cumulative_lengths[idx] / total_length
        helix_mag = _sample_helix_profile(control_t_values, point_mags, t)
        helix_freq = _sample_helix_profile(control_t_values, point_freqs, t)
        helix_slant = _sample_helix_profile(control_t_values, point_slants, t)
        phase = (2.0 * math.pi * helix_freq) * t
        if (
            not is_closed_loop
            and endpoint_mode != state.HELIX_ENDPOINT_UNMODIFIED
        ):
            start_factor = min(1.0, t / max(1e-8, start_taper_end))
            end_factor = min(1.0, (1.0 - t) / max(1e-8, 1.0 - end_taper_start))
            taper_factor = min(start_factor, end_factor)
            taper_factor = taper_factor * taper_factor * (3.0 - 2.0 * taper_factor)
            helix_mag *= taper_factor
            helix_slant *= taper_factor
            if endpoint_mode == state.HELIX_ENDPOINT_CABLE_RETURN:
                start_transition_t = start_taper_end - start_phase_transition
                end_transition_t = end_taper_start + end_phase_transition
                if t < start_transition_t:
                    phase = start_fixed_phase
                elif t < start_taper_end:
                    phase_factor = (t - start_transition_t) / start_phase_transition
                    phase_integral = phase_factor ** 3 - 0.5 * phase_factor ** 4
                    phase = start_fixed_phase + start_phase_velocity * start_phase_transition * phase_integral
                elif t > end_transition_t:
                    phase = end_fixed_phase
                elif t > end_taper_start:
                    phase_factor = (t - end_taper_start) / end_phase_transition
                    phase_integral = phase_factor - phase_factor ** 3 + 0.5 * phase_factor ** 4
                    phase = end_return_phase + end_phase_velocity * end_phase_transition * phase_integral
        tangent, side, up = coordinate_systems[idx]
        helix_dir = (side * math.cos(phase)) + (up * math.sin(phase))
        slant_dir = tangent * (helix_slant * math.sin(phase))
        helix_points.append(point + (helix_dir * helix_mag) + slant_dir)

    return helix_points


def _helix_is_active():
    magnitudes = list(getattr(state, 'helix_point_magnitudes', []) or [])
    frequencies = list(getattr(state, 'helix_point_frequencies', []) or [])
    if not magnitudes:
        magnitudes = [float(getattr(state, 'helix_magnitude', 0.0))]
    if not frequencies:
        frequencies = [float(getattr(state, 'helix_frequency', 0.0))]
    return (
        any(abs(float(value)) > 1e-8 for value in magnitudes)
        and any(float(value) > 1e-8 for value in frequencies)
    )


def _adaptive_resample_deformed_curve(curve_points, values, base_segments, is_closed):
    if len(curve_points) < 2:
        return list(curve_points), list(values)

    path_points = list(curve_points)
    path_values = list(values)
    if len(path_values) < len(path_points):
        fill_value = path_values[-1] if path_values else 0.0
        path_values.extend([fill_value] * (len(path_points) - len(path_values)))
    if is_closed:
        path_points.append(curve_points[0])
        path_values.append(path_values[0])

    total_length = sum(
        (path_points[index] - path_points[index - 1]).length
        for index in range(1, len(path_points))
    )
    if total_length <= 1e-8:
        return list(curve_points), list(values)

    target_spacing = total_length / max(1, int(base_segments))
    max_turn = math.radians(3.0)
    output_points = [path_points[0]]
    output_values = [path_values[0]]
    accumulated_distance = 0.0
    accumulated_turn = 0.0

    for index in range(1, len(path_points) - 1):
        previous_segment = path_points[index] - path_points[index - 1]
        next_segment = path_points[index + 1] - path_points[index]
        accumulated_distance += previous_segment.length
        if previous_segment.length > 1e-8 and next_segment.length > 1e-8:
            dot = max(-1.0, min(1.0, previous_segment.normalized().dot(next_segment.normalized())))
            accumulated_turn += math.acos(dot)

        if accumulated_distance >= target_spacing or accumulated_turn >= max_turn:
            output_points.append(path_points[index])
            output_values.append(path_values[index])
            accumulated_distance = 0.0
            accumulated_turn = 0.0

    if not is_closed:
        output_points.append(path_points[-1])
        output_values.append(path_values[-1])
    elif len(output_points) < 3:
        return list(curve_points), list(values)
    return output_points, output_values


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


def create_tube_mesh(curve_points, radii, resolution=16, original_control_points=None, original_radii=None, aspect_ratio=1.0, global_twist=0.0, point_twists=None, is_closed=False):
    """Create a tube mesh following a curve with varying radius."""
    if len(curve_points) < 2 or len(radii) < 2:
        return [], [], 0

    if hasattr(create_tube_mesh, '_smooth_roundness_cache'):
        create_tube_mesh._smooth_roundness_cache = None

    coordinate_systems = math_utils.create_consistent_coordinate_systems(curve_points, is_closed=is_closed)
    
    all_original_control_points = original_control_points
    all_original_radii = original_radii
    num_all_original_cps = len(all_original_control_points) if all_original_control_points else 0

    smooth_twists = []
    if original_control_points and point_twists and len(point_twists) == len(original_control_points):
        smooth_twists = math_utils.calculate_smooth_twists(
            original_control_points, 
            point_twists, 
            curve_points,
            is_closed=is_closed
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
                    curve_points,
                    is_closed=is_closed
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


def apply_tube_grid_uvs(
    mesh,
    tube_face_count,
    tube_resolution,
    tube_ring_count,
    u_offset=0.0,
    u_scale=1.0,
):
    """Assign a grid UV layout to tube faces from start to end of curve.

    The tube unwrap is deterministic:
    - U runs around the profile ring.
    - V runs along length segments from start (0.0, bottom) to end (1.0).
    """
    if (
        mesh is None
        or tube_face_count <= 0
        or tube_resolution <= 0
        or tube_ring_count < 2
    ):
        return

    uv_layer = mesh.uv_layers.get("UVMap")
    if uv_layer is None:
        uv_layer = mesh.uv_layers.new(name="UVMap")
    uv_data = uv_layer.data

    max_faces = min(tube_face_count, len(mesh.polygons))
    denom_v = float(tube_ring_count - 1)

    for face_index in range(max_faces):
        poly = mesh.polygons[face_index]
        if len(poly.loop_indices) != 4:
            continue

        ring_index = face_index // tube_resolution
        ring_col = face_index % tube_resolution

        u0 = u_offset + (u_scale * ring_col / float(tube_resolution))
        u1 = u_offset + (u_scale * (ring_col + 1) / float(tube_resolution))
        v0 = ring_index / denom_v
        v1 = (ring_index + 1) / denom_v

        loop_indices = poly.loop_indices
        uv_data[loop_indices[0]].uv = (u0, v0)
        uv_data[loop_indices[1]].uv = (u1, v0)
        uv_data[loop_indices[2]].uv = (u1, v1)
        uv_data[loop_indices[3]].uv = (u0, v1)


def apply_cap_island_uvs(
    mesh,
    face_start,
    face_count,
    center,
    axis_u,
    axis_v,
    radius,
    island_u_offset,
    island_u_scale,
):
    """Map cap faces into a separate UV island using projected disc coords."""
    if mesh is None or face_count <= 0:
        return

    uv_layer = mesh.uv_layers.get("UVMap")
    if uv_layer is None:
        return
    uv_data = uv_layer.data

    safe_radius = radius if abs(radius) > 1e-8 else 1.0
    axis_u = axis_u.normalized()
    axis_v = axis_v.normalized()

    max_face = min(face_start + face_count, len(mesh.polygons))
    for face_index in range(max(0, face_start), max_face):
        poly = mesh.polygons[face_index]
        for loop_idx, vert_idx in zip(poly.loop_indices, poly.vertices):
            vert_co = mesh.vertices[vert_idx].co
            delta = vert_co - center
            local_u = 0.5 + (0.5 * delta.dot(axis_u) / safe_radius)
            local_v = 0.5 + (0.5 * delta.dot(axis_v) / safe_radius)
            local_u = max(0.0, min(1.0, local_u))
            local_v = max(0.0, min(1.0, local_v))
            uv_data[loop_idx].uv = (
                island_u_offset + (local_u * island_u_scale),
                local_v,
            )


def apply_cap_island_uvs_by_proximity(
    mesh,
    face_start,
    start_center,
    start_axis_u,
    start_axis_v,
    start_radius,
    start_island_u_offset,
    start_island_u_scale,
    end_center,
    end_axis_u,
    end_axis_v,
    end_radius,
    end_island_u_offset,
    end_island_u_scale,
):
    """Map cap-region faces by assigning each face to nearest cap center."""
    if mesh is None:
        return

    uv_layer = mesh.uv_layers.get("UVMap")
    if uv_layer is None:
        return
    uv_data = uv_layer.data

    start_axis_u = start_axis_u.normalized()
    start_axis_v = start_axis_v.normalized()
    end_axis_u = end_axis_u.normalized()
    end_axis_v = end_axis_v.normalized()
    safe_start_radius = start_radius if abs(start_radius) > 1e-8 else 1.0
    safe_end_radius = end_radius if abs(end_radius) > 1e-8 else 1.0

    for face_index in range(max(0, face_start), len(mesh.polygons)):
        poly = mesh.polygons[face_index]
        if not poly.vertices:
            continue

        centroid = Vector((0.0, 0.0, 0.0))
        for vert_idx in poly.vertices:
            centroid += mesh.vertices[vert_idx].co
        centroid /= float(len(poly.vertices))

        is_start = (centroid - start_center).length <= (centroid - end_center).length
        if is_start:
            center = start_center
            axis_u = start_axis_u
            axis_v = start_axis_v
            radius = safe_start_radius
            island_u_offset = start_island_u_offset
            island_u_scale = start_island_u_scale
        else:
            center = end_center
            axis_u = end_axis_u
            axis_v = end_axis_v
            radius = safe_end_radius
            island_u_offset = end_island_u_offset
            island_u_scale = end_island_u_scale

        for loop_idx, vert_idx in zip(poly.loop_indices, poly.vertices):
            vert_co = mesh.vertices[vert_idx].co
            delta = vert_co - center
            local_u = 0.5 + (0.5 * delta.dot(axis_u) / radius)
            local_v = 0.5 + (0.5 * delta.dot(axis_v) / radius)
            local_u = max(0.0, min(1.0, local_u))
            local_v = max(0.0, min(1.0, local_v))
            uv_data[loop_idx].uv = (
                island_u_offset + (local_u * island_u_scale),
                local_v,
            )


def create_flex_mesh(curve_points, radii, resolution=16, cap_segments=4, original_control_points=None, original_radii=None, aspect_ratio=1.0, global_twist=0.0, point_twists=None, start_cap_type=1, end_cap_type=1):
    """Create a flex mesh tube with configurable end caps."""
    if len(curve_points) < 2 or len(radii) < 2:
        return [], [], [], {}

    is_closed_loop = (start_cap_type == 3 or end_cap_type == 3)

    tube_vertices, tube_faces, actual_resolution = create_tube_mesh(
        curve_points,
        radii,
        resolution,
        original_control_points=original_control_points,
        original_radii=original_radii,
        aspect_ratio=aspect_ratio,
        global_twist=global_twist,
        point_twists=point_twists,
        is_closed=is_closed_loop
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

    start_point = curve_points[0]
    end_point = curve_points[-1]
    start_radius = radii[0]
    end_radius = radii[-1]

    if start_cap_type > 0 and not is_closed_loop:
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

    if end_cap_type > 0 and not is_closed_loop:
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

    if is_closed_loop:
        tube_end_start = len(tube_vertices) - resolution
        for j in range(resolution):
            e0 = tube_offset + tube_end_start + j
            e1 = tube_offset + tube_end_start + (j + 1) % resolution
            s0 = tube_offset + j
            s1 = tube_offset + (j + 1) % resolution
            faces.append([e0, e1, s1, s0])

    start_cap_face_start = -1
    start_cap_face_count = 0
    if state.start_cap_type > 0 and not is_closed_loop:
        start_cap_face_start = len(faces)
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

        start_cap_face_count = len(faces) - start_cap_face_start

    end_cap_face_start = -1
    end_cap_face_count = 0
    if state.end_cap_type > 0 and not is_closed_loop:
        end_cap_face_start = len(faces)
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
    
        end_cap_face_count = len(faces) - end_cap_face_start

    fill_boundaries = []
    is_custom_profile = (state.profile_global_type == state.PROFILE_CUSTOM)
    
    if is_custom_profile and state.start_cap_type == 2:
        start_boundary = list(range(tube_offset, tube_offset + resolution))
        fill_boundaries.append(('start', start_boundary))
    
    if is_custom_profile and state.end_cap_type == 2:
        tube_end_start = tube_offset + len(tube_vertices) - resolution
        end_boundary = list(range(tube_end_start, tube_end_start + resolution))
        fill_boundaries.append(('end', end_boundary))
    
    mesh_info = {
        "tube_face_count": len(tube_faces),
        "tube_resolution": resolution,
        "tube_ring_count": len(curve_points),
        "start_cap_face_start": start_cap_face_start,
        "start_cap_face_count": start_cap_face_count,
        "end_cap_face_start": end_cap_face_start,
        "end_cap_face_count": end_cap_face_count,
        "start_cap_center": start_point.copy(),
        "start_cap_side": start_side.copy(),
        "start_cap_up": start_up.copy(),
        "start_cap_radius": float(start_radius),
        "end_cap_center": end_point.copy(),
        "end_cap_side": end_side.copy(),
        "end_cap_up": end_up.copy(),
        "end_cap_radius": float(end_radius),
        "start_cap_enabled": int(start_cap_type > 0),
        "end_cap_enabled": int(end_cap_type > 0),
    }
    return vertices, faces, fill_boundaries, mesh_info


def create_flex_mesh_from_curve(context, curve_points_3d, radii_3d, resolution=16, segments=32, generate_uv=False, tensions=None, no_tangent_points=None, is_preview=False):
    """Create a flex mesh that follows the curve with varying thickness."""
    if len(curve_points_3d) < 2 or len(radii_3d) < 2:
        return None

    is_closed_loop = (getattr(state, 'start_cap_type', 1) == 3 or getattr(state, 'end_cap_type', 1) == 3)

    # Check if B-spline mode is enabled
    use_bspline = getattr(state, 'bspline_mode', False)

    # Check if adaptive segmentation is enabled
    should_run_adaptive = getattr(state, 'adaptive_segmentation', False) and len(curve_points_3d) >= 3

    post_helix_adaptive = should_run_adaptive and _helix_is_active()
    source_segments = int(segments)
    if post_helix_adaptive:
        source_segments = min(2048, max(256, source_segments * 4))

    smooth_curve_points_3d = _compute_smooth_curve_points(
        curve_points_3d,
        radii_3d,
        source_segments,
        no_tangent_points=no_tangent_points,
        tensions=tensions,
        is_closed_loop=is_closed_loop,
        use_bspline=use_bspline,
        adaptive=should_run_adaptive and not post_helix_adaptive,
    )

    smooth_radii_3d = math_utils.calculate_smooth_radii(
        curve_points_3d,
        radii_3d,
        smooth_curve_points_3d,
        tensions=tensions,
        sharp_points=no_tangent_points,
        is_closed=is_closed_loop,
    )

    if len(smooth_radii_3d) >= 2 and not is_closed_loop:
        smooth_radii_3d[0] = radii_3d[0]
        smooth_radii_3d[-1] = radii_3d[-1]
    
    helix_curve_points = _apply_helix_to_curve_points(
        smooth_curve_points_3d,
        original_control_points=curve_points_3d,
    )
    if post_helix_adaptive:
        helix_curve_points, smooth_radii_3d = _adaptive_resample_deformed_curve(
            helix_curve_points,
            smooth_radii_3d,
            segments,
            is_closed_loop,
        )

    vertices, faces, fill_boundaries, mesh_info = create_flex_mesh(
        helix_curve_points,
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

    if generate_uv and not is_preview:
        has_cap_mesh = bool(
            mesh_info.get("start_cap_enabled", 0)
            or mesh_info.get("end_cap_enabled", 0)
        )
        if has_cap_mesh:
            tube_u_scale = 0.75
            start_cap_u_offset = 0.75
            start_cap_u_scale = 0.125
            end_cap_u_offset = 0.875
            end_cap_u_scale = 0.125
        else:
            tube_u_scale = 1.0
            start_cap_u_offset = 0.0
            start_cap_u_scale = 0.0
            end_cap_u_offset = 0.0
            end_cap_u_scale = 0.0

        apply_tube_grid_uvs(
            mesh,
            tube_face_count=mesh_info.get("tube_face_count", 0),
            tube_resolution=mesh_info.get("tube_resolution", 0),
            tube_ring_count=mesh_info.get("tube_ring_count", 0),
            u_offset=0.0,
            u_scale=tube_u_scale,
        )

        if mesh_info.get("start_cap_face_count", 0) > 0:
            apply_cap_island_uvs(
                mesh,
                face_start=mesh_info.get("start_cap_face_start", -1),
                face_count=mesh_info.get("start_cap_face_count", 0),
                center=mesh_info.get("start_cap_center", Vector((0, 0, 0))),
                axis_u=mesh_info.get("start_cap_side", Vector((1, 0, 0))),
                axis_v=mesh_info.get("start_cap_up", Vector((0, 1, 0))),
                radius=mesh_info.get("start_cap_radius", 1.0),
                island_u_offset=start_cap_u_offset,
                island_u_scale=start_cap_u_scale,
            )

        if mesh_info.get("end_cap_face_count", 0) > 0:
            apply_cap_island_uvs(
                mesh,
                face_start=mesh_info.get("end_cap_face_start", -1),
                face_count=mesh_info.get("end_cap_face_count", 0),
                center=mesh_info.get("end_cap_center", Vector((0, 0, 0))),
                axis_u=mesh_info.get("end_cap_side", Vector((1, 0, 0))),
                axis_v=mesh_info.get("end_cap_up", Vector((0, 1, 0))),
                radius=mesh_info.get("end_cap_radius", 1.0),
                island_u_offset=end_cap_u_offset,
                island_u_scale=end_cap_u_scale,
            )

            apply_cap_island_uvs_by_proximity(
                mesh,
                face_start=mesh_info.get("tube_face_count", 0),
                start_center=mesh_info.get(
                    "start_cap_center",
                    Vector((0.0, 0.0, 0.0)),
                ),
                start_axis_u=mesh_info.get(
                    "start_cap_side",
                    Vector((1.0, 0.0, 0.0)),
                ),
                start_axis_v=mesh_info.get(
                    "start_cap_up",
                    Vector((0.0, 1.0, 0.0)),
                ),
                start_radius=mesh_info.get("start_cap_radius", 1.0),
                start_island_u_offset=start_cap_u_offset,
                start_island_u_scale=start_cap_u_scale,
                end_center=mesh_info.get(
                    "end_cap_center",
                    Vector((0.0, 0.0, 0.0)),
                ),
                end_axis_u=mesh_info.get(
                    "end_cap_side",
                    Vector((1.0, 0.0, 0.0)),
                ),
                end_axis_v=mesh_info.get(
                    "end_cap_up",
                    Vector((0.0, 1.0, 0.0)),
                ),
                end_radius=mesh_info.get("end_cap_radius", 1.0),
                end_island_u_offset=end_cap_u_offset,
                end_island_u_scale=end_cap_u_scale,
            )
    
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


def _get_preview_material():
    mat = bpy.data.materials.get("Flex_Preview_Material")
    if mat is not None:
        return mat

    mat = bpy.data.materials.new("Flex_Preview_Material")
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    nodes.clear()
    bsdf = nodes.new(type='ShaderNodeBsdfPrincipled')
    bsdf.inputs['Base Color'].default_value = (0.00127, 0.169, 0.376, 1.0)
    bsdf.inputs['Metallic'].default_value = 0.0
    bsdf.inputs['Roughness'].default_value = 0.8
    if 'Specular' in bsdf.inputs:
        bsdf.inputs['Specular'].default_value = 0.5
    elif 'Specular IOR Level' in bsdf.inputs:
        bsdf.inputs['Specular IOR Level'].default_value = 0.5
    output = nodes.new(type='ShaderNodeOutputMaterial')
    mat.node_tree.links.new(bsdf.outputs['BSDF'], output.inputs['Surface'])
    return mat


def _update_poly_curve(curve_data, points, radii=None, tilts=None, cyclic=False):
    curve_data.splines.clear()
    spline = curve_data.splines.new('POLY')
    spline.points.add(len(points) - 1)
    for index, point in enumerate(points):
        spline.points[index].co = (point.x, point.y, point.z, 1.0)
        if radii and index < len(radii):
            spline.points[index].radius = max(0.000001, float(radii[index]))
        if tilts and index < len(tilts):
            spline.points[index].tilt = float(tilts[index])
    spline.use_cyclic_u = cyclic
    curve_data.update_tag()


def _update_control_curve(curve_data, points, radii, tilts, cyclic, use_bspline, sharp_points):
    curve_data.splines.clear()
    if use_bspline:
        spline = curve_data.splines.new('NURBS')
        spline.points.add(len(points) - 1)
        for index, point in enumerate(points):
            spline.points[index].co = (point.x, point.y, point.z, 1.0)
            spline.points[index].radius = max(0.000001, float(radii[index]))
            spline.points[index].tilt = float(tilts[index])
        spline.order_u = min(4, len(points))
        spline.use_endpoint_u = not cyclic
    else:
        spline = curve_data.splines.new('BEZIER')
        spline.bezier_points.add(len(points) - 1)
        for index, point in enumerate(points):
            bezier_point = spline.bezier_points[index]
            bezier_point.co = point
            bezier_point.radius = max(0.000001, float(radii[index]))
            bezier_point.tilt = float(tilts[index])
        for index, bezier_point in enumerate(spline.bezier_points):
            handle_type = 'VECTOR' if index in sharp_points else 'AUTO'
            bezier_point.handle_left_type = handle_type
            bezier_point.handle_right_type = handle_type
        handles = [
            (point.handle_left.copy(), point.handle_right.copy())
            for point in spline.bezier_points
        ]
        for bezier_point, (handle_left, handle_right) in zip(spline.bezier_points, handles):
            bezier_point.handle_left_type = 'FREE'
            bezier_point.handle_right_type = 'FREE'
            bezier_point.handle_left = handle_left
            bezier_point.handle_right = handle_right
    spline.use_cyclic_u = cyclic
    curve_data.update_tag()


def _add_preview_rounded_caps(points, radii, tilts, start_cap_type, end_cap_type, cap_segments=4):
    if len(points) < 2:
        return list(points), list(radii), list(tilts), 0

    output_points = list(points)
    output_radii = list(radii)
    output_tilts = list(tilts)
    added_count = 0

    if start_cap_type == 1:
        outward = points[0] - points[1]
        if outward.length > 1e-8:
            outward.normalize()
            cap_points = []
            cap_radii = []
            for index in range(cap_segments, 0, -1):
                angle = 0.5 * math.pi * index / cap_segments
                cap_points.append(points[0] + outward * (math.sin(angle) * radii[0]))
                cap_radii.append(max(0.000001, math.cos(angle) * radii[0]))
            output_points = cap_points + output_points
            output_radii = cap_radii + output_radii
            output_tilts = [tilts[0]] * cap_segments + output_tilts
            added_count += cap_segments

    if end_cap_type == 1:
        outward = points[-1] - points[-2]
        if outward.length > 1e-8:
            outward.normalize()
            for index in range(1, cap_segments + 1):
                angle = 0.5 * math.pi * index / cap_segments
                output_points.append(points[-1] + outward * (math.sin(angle) * radii[-1]))
                output_radii.append(max(0.000001, math.cos(angle) * radii[-1]))
                output_tilts.append(tilts[-1])
            added_count += cap_segments

    return output_points, output_radii, output_tilts, added_count


def _preview_profile_points(resolution):
    return generate_profile_vertices(
        getattr(state, 'profile_global_type', state.PROFILE_CIRCULAR),
        Vector((0.0, 0.0, 0.0)),
        1.0,
        Vector((1.0, 0.0, 0.0)),
        Vector((0.0, 1.0, 0.0)),
        resolution,
        aspect_ratio=getattr(state, 'profile_aspect_ratio', 1.0),
        twist_angle=0.0,
        roundness=getattr(state, 'profile_roundness', 0.3),
    )


def _create_geometry_nodes_preview(context):
    centerline_data = bpy.data.curves.new("Flex_Preview_Centerline", 'CURVE')
    centerline_data.dimensions = '3D'
    centerline_data.resolution_u = 32
    preview_obj = bpy.data.objects.new("Flex_Preview", centerline_data)
    context.collection.objects.link(preview_obj)

    profile_data = bpy.data.curves.new("Flex_Preview_Profile", 'CURVE')
    profile_data.dimensions = '2D'
    profile_data.resolution_u = 1
    profile_obj = bpy.data.objects.new("Flex_Preview_Profile", profile_data)
    context.collection.objects.link(profile_obj)
    profile_obj.hide_render = True
    profile_obj.hide_set(True)

    node_group = bpy.data.node_groups.new("Flex_Preview_Geometry", 'GeometryNodeTree')
    node_group.is_modifier = True
    node_group.interface.new_socket(name="Geometry", in_out='INPUT', socket_type='NodeSocketGeometry')
    node_group.interface.new_socket(name="Geometry", in_out='OUTPUT', socket_type='NodeSocketGeometry')

    nodes = node_group.nodes
    links = node_group.links
    group_input = nodes.new('NodeGroupInput')
    group_output = nodes.new('NodeGroupOutput')
    object_info = nodes.new('GeometryNodeObjectInfo')
    object_info.inputs['Object'].default_value = profile_obj
    resample_curve = nodes.new('GeometryNodeResampleCurve')
    resample_curve.name = "Flex Resample Curve"
    projection_resample = nodes.new('GeometryNodeResampleCurve')
    projection_resample.name = "Flex Projection Resample"
    resample_switch = nodes.new('GeometryNodeSwitch')
    resample_switch.name = "Flex Resample Switch"
    resample_switch.input_type = 'GEOMETRY'
    spline_parameter = nodes.new('GeometryNodeSplineParameter')
    store_factor = nodes.new('GeometryNodeStoreNamedAttribute')
    store_factor.data_type = 'FLOAT'
    store_factor.domain = 'POINT'
    store_factor.inputs['Name'].default_value = "_flex_curve_factor"
    subdivide_curve = nodes.new('GeometryNodeSubdivideCurve')
    curve_factor = nodes.new('GeometryNodeInputNamedAttribute')
    curve_factor.data_type = 'FLOAT'
    curve_factor.inputs['Name'].default_value = "_flex_curve_factor"
    sample_curve = nodes.new('GeometryNodeSampleCurve')
    sample_curve.data_type = 'FLOAT'
    sample_curve.mode = 'FACTOR'
    set_position = nodes.new('GeometryNodeSetPosition')
    curve_switch = nodes.new('GeometryNodeSwitch')
    curve_switch.name = "Flex Adaptive Switch"
    curve_switch.input_type = 'GEOMETRY'
    domain_size = nodes.new('GeometryNodeAttributeDomainSize')
    domain_size.component = 'CURVE'
    index = nodes.new('GeometryNodeInputIndex')
    next_index = nodes.new('FunctionNodeIntegerMath')
    next_index.operation = 'ADD'
    next_index.inputs[1].default_value = 1
    wrap_index = nodes.new('FunctionNodeIntegerMath')
    wrap_index.operation = 'MODULO'
    tangent = nodes.new('GeometryNodeInputTangent')
    next_tangent = nodes.new('GeometryNodeFieldAtIndex')
    next_tangent.data_type = 'FLOAT_VECTOR'
    next_tangent.domain = 'POINT'
    tangent_dot = nodes.new('ShaderNodeVectorMath')
    tangent_dot.operation = 'DOT_PRODUCT'
    curvature_to_cuts = nodes.new('ShaderNodeMapRange')
    curvature_to_cuts.clamp = True
    curvature_to_cuts.inputs['From Min'].default_value = math.cos(math.radians(20.0))
    curvature_to_cuts.inputs['From Max'].default_value = math.cos(math.radians(1.0))
    curvature_to_cuts.inputs['To Min'].default_value = 5.0
    curvature_to_cuts.inputs['To Max'].default_value = 0.0
    cuts_to_integer = nodes.new('FunctionNodeFloatToInt')
    cuts_to_integer.rounding_mode = 'ROUND'
    last_index = nodes.new('FunctionNodeIntegerMath')
    last_index.operation = 'SUBTRACT'
    last_index.inputs[1].default_value = 1
    is_last_point = nodes.new('FunctionNodeCompare')
    is_last_point.data_type = 'INT'
    is_last_point.operation = 'EQUAL'
    seam_cut_switch = nodes.new('GeometryNodeSwitch')
    seam_cut_switch.input_type = 'INT'
    seam_cut_switch.inputs['True'].default_value = 0
    closed_domain_size = nodes.new('GeometryNodeAttributeDomainSize')
    closed_domain_size.component = 'CURVE'
    closed_last_index = nodes.new('FunctionNodeIntegerMath')
    closed_last_index.operation = 'SUBTRACT'
    closed_last_index.inputs[1].default_value = 1
    is_closed_last_point = nodes.new('FunctionNodeCompare')
    is_closed_last_point.data_type = 'INT'
    is_closed_last_point.operation = 'EQUAL'
    delete_duplicate_endpoint = nodes.new('GeometryNodeDeleteGeometry')
    delete_duplicate_endpoint.domain = 'POINT'
    set_spline_cyclic = nodes.new('GeometryNodeSetSplineCyclic')
    set_spline_cyclic.inputs['Selection'].default_value = True
    set_spline_cyclic.inputs['Cyclic'].default_value = True
    closed_curve_switch = nodes.new('GeometryNodeSwitch')
    closed_curve_switch.name = "Flex Closed Curve Switch"
    closed_curve_switch.input_type = 'GEOMETRY'
    curve_radius = nodes.new('GeometryNodeInputRadius')
    next_radius = nodes.new('GeometryNodeFieldAtIndex')
    next_radius.data_type = 'FLOAT'
    next_radius.domain = 'POINT'
    radius_difference = nodes.new('ShaderNodeMath')
    radius_difference.operation = 'SUBTRACT'
    absolute_radius_difference = nodes.new('ShaderNodeMath')
    absolute_radius_difference.operation = 'ABSOLUTE'
    maximum_radius = nodes.new('ShaderNodeMath')
    maximum_radius.operation = 'MAXIMUM'
    safe_radius = nodes.new('ShaderNodeMath')
    safe_radius.operation = 'MAXIMUM'
    safe_radius.inputs[1].default_value = 0.000001
    relative_radius_change = nodes.new('ShaderNodeMath')
    relative_radius_change.operation = 'DIVIDE'
    radius_change_to_cuts = nodes.new('ShaderNodeMapRange')
    radius_change_to_cuts.clamp = True
    radius_change_to_cuts.inputs['From Min'].default_value = 0.05
    radius_change_to_cuts.inputs['From Max'].default_value = 0.35
    radius_change_to_cuts.inputs['To Min'].default_value = 0.0
    radius_change_to_cuts.inputs['To Max'].default_value = 5.0
    maximum_cuts = nodes.new('ShaderNodeMath')
    maximum_cuts.operation = 'MAXIMUM'
    set_curve_radius = nodes.new('GeometryNodeSetCurveRadius')
    curve_to_mesh = nodes.new('GeometryNodeCurveToMesh')
    curve_to_mesh.name = "Flex Curve to Mesh"
    set_material = nodes.new('GeometryNodeSetMaterial')
    set_material.inputs['Material'].default_value = _get_preview_material()

    links.new(group_input.outputs['Geometry'], resample_curve.inputs['Curve'])
    links.new(group_input.outputs['Geometry'], projection_resample.inputs['Curve'])
    links.new(group_input.outputs['Geometry'], resample_switch.inputs['False'])
    links.new(resample_curve.outputs['Curve'], resample_switch.inputs['True'])
    links.new(resample_switch.outputs['Output'], store_factor.inputs['Geometry'])
    links.new(spline_parameter.outputs['Factor'], store_factor.inputs['Value'])
    links.new(store_factor.outputs['Geometry'], subdivide_curve.inputs['Curve'])
    links.new(store_factor.outputs['Geometry'], curve_switch.inputs['False'])
    links.new(subdivide_curve.outputs['Curve'], set_position.inputs['Geometry'])
    links.new(projection_resample.outputs['Curve'], sample_curve.inputs['Curves'])
    links.new(curve_radius.outputs['Radius'], sample_curve.inputs['Value'])
    links.new(curve_factor.outputs['Attribute'], sample_curve.inputs['Factor'])
    links.new(sample_curve.outputs['Position'], set_position.inputs['Position'])
    links.new(set_position.outputs['Geometry'], set_curve_radius.inputs['Curve'])
    links.new(sample_curve.outputs['Value'], set_curve_radius.inputs['Radius'])
    links.new(set_curve_radius.outputs['Curve'], curve_switch.inputs['True'])
    links.new(store_factor.outputs['Geometry'], domain_size.inputs['Geometry'])
    links.new(index.outputs['Index'], next_index.inputs[0])
    links.new(next_index.outputs['Value'], wrap_index.inputs[0])
    links.new(domain_size.outputs['Point Count'], wrap_index.inputs[1])
    links.new(tangent.outputs['Tangent'], next_tangent.inputs['Value'])
    links.new(wrap_index.outputs['Value'], next_tangent.inputs['Index'])
    links.new(tangent.outputs['Tangent'], tangent_dot.inputs[0])
    links.new(next_tangent.outputs['Value'], tangent_dot.inputs[1])
    links.new(tangent_dot.outputs['Value'], curvature_to_cuts.inputs['Value'])
    links.new(curve_radius.outputs['Radius'], next_radius.inputs['Value'])
    links.new(wrap_index.outputs['Value'], next_radius.inputs['Index'])
    links.new(curve_radius.outputs['Radius'], radius_difference.inputs[0])
    links.new(next_radius.outputs['Value'], radius_difference.inputs[1])
    links.new(radius_difference.outputs['Value'], absolute_radius_difference.inputs[0])
    links.new(curve_radius.outputs['Radius'], maximum_radius.inputs[0])
    links.new(next_radius.outputs['Value'], maximum_radius.inputs[1])
    links.new(maximum_radius.outputs['Value'], safe_radius.inputs[0])
    links.new(absolute_radius_difference.outputs['Value'], relative_radius_change.inputs[0])
    links.new(safe_radius.outputs['Value'], relative_radius_change.inputs[1])
    links.new(relative_radius_change.outputs['Value'], radius_change_to_cuts.inputs['Value'])
    links.new(curvature_to_cuts.outputs['Result'], maximum_cuts.inputs[0])
    links.new(radius_change_to_cuts.outputs['Result'], maximum_cuts.inputs[1])
    links.new(maximum_cuts.outputs['Value'], cuts_to_integer.inputs['Float'])
    links.new(domain_size.outputs['Point Count'], last_index.inputs[0])
    links.new(index.outputs['Index'], is_last_point.inputs['A'])
    links.new(last_index.outputs['Value'], is_last_point.inputs['B'])
    links.new(is_last_point.outputs['Result'], seam_cut_switch.inputs['Switch'])
    links.new(cuts_to_integer.outputs['Integer'], seam_cut_switch.inputs['False'])
    links.new(seam_cut_switch.outputs['Output'], subdivide_curve.inputs['Cuts'])
    links.new(curve_switch.outputs['Output'], closed_domain_size.inputs['Geometry'])
    links.new(closed_domain_size.outputs['Point Count'], closed_last_index.inputs[0])
    links.new(index.outputs['Index'], is_closed_last_point.inputs['A'])
    links.new(closed_last_index.outputs['Value'], is_closed_last_point.inputs['B'])
    links.new(curve_switch.outputs['Output'], delete_duplicate_endpoint.inputs['Geometry'])
    links.new(is_closed_last_point.outputs['Result'], delete_duplicate_endpoint.inputs['Selection'])
    links.new(delete_duplicate_endpoint.outputs['Geometry'], set_spline_cyclic.inputs['Curve'])
    links.new(curve_switch.outputs['Output'], closed_curve_switch.inputs['False'])
    links.new(set_spline_cyclic.outputs['Curve'], closed_curve_switch.inputs['True'])
    links.new(closed_curve_switch.outputs['Output'], curve_to_mesh.inputs['Curve'])
    links.new(object_info.outputs['Geometry'], curve_to_mesh.inputs['Profile Curve'])
    links.new(curve_radius.outputs['Radius'], curve_to_mesh.inputs['Scale'])
    links.new(curve_to_mesh.outputs['Mesh'], set_material.inputs['Geometry'])
    links.new(set_material.outputs['Geometry'], group_output.inputs['Geometry'])

    modifier = preview_obj.modifiers.new(name="Flex Preview Geometry", type='NODES')
    modifier.node_group = node_group
    preview_obj.display_type = 'SOLID'
    preview_obj.show_wire = True
    preview_obj.show_all_edges = True
    preview_obj.show_in_front = False
    preview_obj.select_set(True)
    context.view_layer.objects.active = preview_obj

    state.preview_mesh_obj = preview_obj
    state.preview_profile_obj = profile_obj
    state.preview_node_group = node_group
    return preview_obj


def _update_geometry_nodes_preview(context, curve_points_3d, radii_3d, resolution, segments):
    start_cap_type = getattr(state, 'start_cap_type', 1)
    end_cap_type = getattr(state, 'end_cap_type', 1)
    is_closed_loop = start_cap_type == 3 or end_cap_type == 3
    rounded_caps = not is_closed_loop and (start_cap_type == 1 or end_cap_type == 1)
    adaptive_requested = (
        getattr(state, 'adaptive_segmentation', False)
        and len(curve_points_3d) >= 3
    )
    helix_active = _helix_is_active()
    use_bspline = getattr(state, 'bspline_mode', False)
    python_centerline = helix_active or not use_bspline or is_closed_loop or rounded_caps
    global_twist = float(getattr(state, 'profile_global_twist', 0.0))

    if python_centerline:
        source_segments = int(segments)
        if adaptive_requested:
            source_segments = min(2048, max(256, source_segments * 4))
        centerline_points = _compute_smooth_curve_points(
            curve_points_3d,
            radii_3d,
            source_segments,
            no_tangent_points=state.no_tangent_points,
            tensions=state.point_tensions,
            is_closed_loop=is_closed_loop,
            use_bspline=getattr(state, 'bspline_mode', False),
            adaptive=False,
        )
        centerline_radii = math_utils.calculate_smooth_radii(
            curve_points_3d,
            radii_3d,
            centerline_points,
            tensions=state.point_tensions,
            sharp_points=state.no_tangent_points,
            is_closed=is_closed_loop,
        )
        if len(centerline_radii) >= 2 and not is_closed_loop:
            centerline_radii[0] = radii_3d[0]
            centerline_radii[-1] = radii_3d[-1]
        centerline_twists = math_utils.calculate_smooth_twists(
            curve_points_3d,
            getattr(state, 'profile_point_twists', []),
            centerline_points,
            is_closed=is_closed_loop,
        )
        centerline_points = _apply_helix_to_curve_points(
            centerline_points,
            original_control_points=curve_points_3d,
        )
    else:
        centerline_points = curve_points_3d
        centerline_radii = radii_3d
        point_twists = list(getattr(state, 'profile_point_twists', []))
        point_twists.extend([0.0] * max(0, len(curve_points_3d) - len(point_twists)))
        centerline_twists = point_twists[:len(curve_points_3d)]

    centerline_twists = [global_twist + twist for twist in centerline_twists]
    deformed_adaptive_baked = adaptive_requested and (rounded_caps or helix_active)
    if deformed_adaptive_baked:
        adaptive_source_points = centerline_points
        centerline_points, centerline_radii = _adaptive_resample_deformed_curve(
            adaptive_source_points,
            centerline_radii,
            segments,
            False,
        )
        _, centerline_twists = _adaptive_resample_deformed_curve(
            adaptive_source_points,
            centerline_twists,
            segments,
            False,
        )

    source_cyclic = is_closed_loop
    rounded_cap_point_count = 0
    if is_closed_loop and python_centerline and centerline_points:
        centerline_points = list(centerline_points) + [centerline_points[0].copy()]
        centerline_radii = list(centerline_radii) + [centerline_radii[0]]
        centerline_twists = list(centerline_twists) + [centerline_twists[0]]
        source_cyclic = False
    elif rounded_caps:
        centerline_points, centerline_radii, centerline_twists, rounded_cap_point_count = (
            _add_preview_rounded_caps(
                centerline_points,
                centerline_radii,
                centerline_twists,
                start_cap_type,
                end_cap_type,
            )
        )

    preview_obj = state.preview_mesh_obj
    if (
        preview_obj is None
        or preview_obj.name not in bpy.data.objects
        or preview_obj.type != 'CURVE'
        or not preview_obj.get("flex_gn_preview", False)
    ):
        state.cleanup_preview_mesh()
        preview_obj = _create_geometry_nodes_preview(context)
        preview_obj["flex_gn_preview"] = True

    if python_centerline:
        _update_poly_curve(
            preview_obj.data,
            centerline_points,
            radii=centerline_radii,
            tilts=centerline_twists,
            cyclic=source_cyclic,
        )
    else:
        _update_control_curve(
            preview_obj.data,
            centerline_points,
            centerline_radii,
            centerline_twists,
            source_cyclic,
            getattr(state, 'bspline_mode', False),
            state.no_tangent_points,
        )
    _update_poly_curve(
        state.preview_profile_obj.data,
        _preview_profile_points(resolution),
        cyclic=True,
    )

    adaptive_active = adaptive_requested and not deformed_adaptive_baked
    resample_curve = state.preview_node_group.nodes.get("Flex Resample Curve")
    if resample_curve is not None:
        sample_count = int(segments) + 1 + rounded_cap_point_count
        if python_centerline and not adaptive_active:
            sample_count = len(centerline_points)
        resample_curve.inputs['Count'].default_value = max(2, sample_count)

    projection_resample = state.preview_node_group.nodes.get("Flex Projection Resample")
    if projection_resample is not None:
        projection_resample.inputs['Count'].default_value = max(64, int(segments) * 8 + 1)

    resample_switch = state.preview_node_group.nodes.get("Flex Resample Switch")
    if resample_switch is not None:
        resample_switch.inputs['Switch'].default_value = not python_centerline or adaptive_active

    adaptive_switch = state.preview_node_group.nodes.get("Flex Adaptive Switch")
    if adaptive_switch is not None:
        adaptive_switch.inputs['Switch'].default_value = adaptive_active

    closed_curve_switch = state.preview_node_group.nodes.get("Flex Closed Curve Switch")
    if closed_curve_switch is not None:
        closed_curve_switch.inputs['Switch'].default_value = is_closed_loop

    curve_to_mesh = state.preview_node_group.nodes.get("Flex Curve to Mesh")
    if curve_to_mesh is not None:
        curve_to_mesh.inputs['Fill Caps'].default_value = (
            not is_closed_loop
            and getattr(state, 'start_cap_type', 1) > 0
            and getattr(state, 'end_cap_type', 1) > 0
        )

    if state.object_matrix_world is not None:
        preview_obj.matrix_world = state.object_matrix_world
    if getattr(state, 'mirror_mode_active', False):
        apply_mirror_modifier(preview_obj, True)
    return preview_obj


def _update_preview_mesh_python(context, curve_points_3d, radii_3d, resolution=16, segments=32):
    """Create or update the preview mesh based on the current curve."""
    if len(curve_points_3d) < 2 or len(radii_3d) < 2:
        return
    if state.preview_mesh_obj is not None and state.preview_mesh_obj.type != 'MESH':
        state.cleanup_preview_mesh()

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
        is_closed_loop = (getattr(state, 'start_cap_type', 1) == 3 or getattr(state, 'end_cap_type', 1) == 3)
        use_bspline = getattr(state, 'bspline_mode', False)
        should_run_adaptive_logic = state.adaptive_segmentation and len(curve_points_3d) >= 3

        smooth_curve_points_3d = _compute_smooth_curve_points(
            curve_points_3d,
            radii_3d,
            segments,
            no_tangent_points=state.no_tangent_points,
            tensions=state.point_tensions,
            is_closed_loop=is_closed_loop,
            use_bspline=use_bspline,
            adaptive=should_run_adaptive_logic,
        )

        smooth_radii_3d = math_utils.calculate_smooth_radii(
            curve_points_3d,
            radii_3d,
            smooth_curve_points_3d,
            tensions=state.point_tensions,
            sharp_points=state.no_tangent_points,
            is_closed=is_closed_loop,
        )

        if len(smooth_radii_3d) >= 2 and not is_closed_loop:
            smooth_radii_3d[0] = radii_3d[0]
            smooth_radii_3d[-1] = radii_3d[-1]

        helix_curve_points = _apply_helix_to_curve_points(
            smooth_curve_points_3d,
            original_control_points=curve_points_3d,
        )

        vertices, faces, fill_boundaries, _mesh_info = create_flex_mesh(
            helix_curve_points,
            smooth_radii_3d,
            resolution=resolution,
            cap_segments=4,
            original_control_points=curve_points_3d,
            original_radii=radii_3d,
            aspect_ratio=state.profile_aspect_ratio,
            global_twist=state.profile_global_twist,
            point_twists=state.profile_point_twists,
            start_cap_type=state.start_cap_type,
            end_cap_type=state.end_cap_type,
        )

        mesh = state.preview_mesh_obj.data
        mesh.clear_geometry()
        if vertices is not None:
            mesh.from_pydata(vertices, [], faces)
            if fill_boundaries:
                fill_boundary_loops(mesh, fill_boundaries)
        mesh.update()

    return state.preview_mesh_obj


def update_preview_mesh(context, curve_points_3d, radii_3d, resolution=16, segments=32):
    """Update the modal preview through Geometry Nodes with a Python fallback."""
    if len(curve_points_3d) < 2 or len(radii_3d) < 2:
        return
    if getattr(state, 'preview_geometry_nodes_failed', False):
        return _update_preview_mesh_python(
            context,
            curve_points_3d,
            radii_3d,
            resolution,
            segments,
        )
    try:
        return _update_geometry_nodes_preview(
            context,
            curve_points_3d,
            radii_3d,
            resolution,
            segments,
        )
    except Exception as exc:
        print(f"Flex: Geometry Nodes preview unavailable, using Python preview: {exc}")
        state.preview_geometry_nodes_failed = True
        state.cleanup_preview_mesh()
        return _update_preview_mesh_python(
            context,
            curve_points_3d,
            radii_3d,
            resolution,
            segments,
        )


def register():
    pass


def unregister():
    pass
