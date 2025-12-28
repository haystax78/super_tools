"""
Mathematical utilities for the Flex tool in Super Tools addon.
Handles curve interpolation, coordinate system calculations, and other math functions.
"""
import math
from mathutils import Vector, Matrix
from .flex_state import state
from . import flex_conversion as conversion


def detect_apex_indices(points_3d, angle_threshold_degrees=45):
    """
    Return indices of points that are apexes (sharp turns) based on the angle between adjacent segments.
    """
    apex_indices = set()
    if len(points_3d) < 3:
        return apex_indices
    for i in range(1, len(points_3d)-1):
        v_prev = (points_3d[i] - points_3d[i-1]).normalized()
        v_next = (points_3d[i+1] - points_3d[i]).normalized()
        dot = max(-1.0, min(1.0, v_prev.dot(v_next)))
        angle = math.degrees(math.acos(dot))
        if angle > angle_threshold_degrees:
            apex_indices.add(i)
    return apex_indices


def get_polyline_arc_length(points_3d):
    """Calculate the total arc length of a polyline defined by a list of 3D points."""
    if not points_3d or len(points_3d) < 2:
        return 0.0
    total_length = 0.0
    for i in range(len(points_3d) - 1):
        total_length += (points_3d[i+1] - points_3d[i]).length
    return total_length


def get_curve_tangent(points_3d, index):
    """Return the tangent vector at a given index in a polyline."""
    n = len(points_3d)
    if n < 2:
        return Vector((1, 0, 0))
    if index == 0:
        return (points_3d[1] - points_3d[0]).normalized()
    elif index == n-1:
        return (points_3d[-1] - points_3d[-2]).normalized()
    else:
        v1 = (points_3d[index] - points_3d[index-1]).normalized()
        v2 = (points_3d[index+1] - points_3d[index]).normalized()
        return (v1 + v2).normalized() if (v1 + v2).length > 1e-6 else v2


def find_closest_segment_to_point(points_3d, point_3d):
    """Find the segment index whose line is closest to the given 3D point."""
    min_dist = float('inf')
    best_index = -1
    for i in range(len(points_3d) - 1):
        a = points_3d[i]
        b = points_3d[i+1]
        ab = b - a
        ab_len_sq = ab.length_squared
        if ab_len_sq == 0:
            continue
        t = max(0.0, min(1.0, (point_3d - a).dot(ab) / ab_len_sq))
        closest = a + t * ab
        dist = (point_3d - closest).length
        if dist < min_dist:
            min_dist = dist
            best_index = i
    return best_index, min_dist


def interpolate_curve_3d(points_3d, num_points=100, sharp_points=None, tensions=None):
    """Create a smooth curve through the given 3D points that passes through all control points."""
    if sharp_points is None:
        sharp_points = set()
    
    if tensions is None:
        tensions = [0.5] * len(points_3d)
    
    while len(tensions) < len(points_3d):
        tensions.append(0.5)
    
    if len(points_3d) < 2:
        return points_3d.copy()
    
    if len(points_3d) == 2:
        result = []
        p0 = points_3d[0]
        p1 = points_3d[1]
        for i in range(num_points):
            t = i / (num_points - 1)
            point = p0.lerp(p1, t)
            result.append(point.copy())
        return result
    
    result = []
    
    total_length = 0
    segment_lengths = []
    for i in range(len(points_3d) - 1):
        length = (points_3d[i+1] - points_3d[i]).length
        segment_lengths.append(length)
        total_length += length
    
    params = [0]
    current_length = 0
    
    for segment_length in segment_lengths:
        current_length += segment_length
        params.append(current_length / total_length if total_length > 0 else 0)
    
    for i in range(num_points):
        t = i / (num_points - 1)
        
        segment = 0
        while segment < len(params) - 1 and t > params[segment + 1]:
            segment += 1
        
        if segment >= len(params) - 1:
            result.append(points_3d[-1].copy())
            continue
        
        segment_t = 0
        if params[segment + 1] > params[segment]:
            segment_t = (t - params[segment]) / (params[segment + 1] - params[segment])
        
        p0 = points_3d[max(0, segment - 1)]
        p1 = points_3d[segment]
        p2 = points_3d[segment + 1]
        p3 = points_3d[min(len(points_3d) - 1, segment + 2)]
        
        is_sharp_0 = segment in sharp_points
        is_sharp_1 = (segment + 1) in sharp_points
        
        if is_sharp_0 and is_sharp_1:
            point = p1.lerp(p2, segment_t)
        elif not is_sharp_0 and not is_sharp_1:
            tension1 = tensions[segment]
            tension2 = tensions[segment + 1]
            m1 = (1 - tension1) * (p2 - p0)
            m2 = (1 - tension2) * (p3 - p1)
            h1 = 2*segment_t**3 - 3*segment_t**2 + 1
            h2 = -2*segment_t**3 + 3*segment_t**2
            h3 = segment_t**3 - 2*segment_t**2 + segment_t
            h4 = segment_t**3 - segment_t**2
            point = h1*p1 + h2*p2 + h3*m1 + h4*m2
        else:
            blend = 3*segment_t**2 - 2*segment_t**3
            tension1 = tensions[segment]
            tension2 = tensions[segment + 1]
            if is_sharp_0:
                m1 = Vector((0, 0, 0))
                m2 = (1 - tension2) * (p3 - p1)
            elif is_sharp_1:
                m1 = (1 - tension1) * (p2 - p0)
                m2 = Vector((0, 0, 0))
            else:
                m1 = (1 - tension1) * (p2 - p0)
                m2 = (1 - tension2) * (p3 - p1)
            h1 = 2*segment_t**3 - 3*segment_t**2 + 1
            h2 = -2*segment_t**3 + 3*segment_t**2
            h3 = segment_t**3 - 2*segment_t**2 + segment_t
            h4 = segment_t**3 - segment_t**2
            hermite = h1*p1 + h2*p2 + h3*m1 + h4*m2
            linear = p1.lerp(p2, segment_t)
            if is_sharp_0:
                point = linear.lerp(hermite, blend)
            else:
                point = hermite.lerp(linear, blend)
        result.append(point.copy())
    
    return result


def _de_boor_cubic(knot, ctrl, t):
    """Evaluate clamped cubic B-spline at parameter t using De Boor."""
    p = 3
    n = len(ctrl) - 1
    i = p
    found = False
    for s in range(p, len(knot) - p - 1):
        if knot[s] <= t < knot[s + 1]:
            i = s
            found = True
            break
    if not found:
        i = len(knot) - p - 2
    d = [ctrl[j].copy() for j in range(i - p, i + 1)]
    for r in range(1, p + 1):
        for j in range(p, r - 1, -1):
            idx = i - p + j
            denom = knot[idx + p + 1 - r] - knot[idx]
            a = 0.0 if abs(denom) < 1e-9 else (t - knot[idx]) / denom
            d[j] = (1.0 - a) * d[j - 1] + a * d[j]
    return d[p]


def bspline_cubic_open_uniform(points_3d, num_points):
    """Sample a clamped (open) uniform cubic B-spline through control points."""
    n_ctrl = len(points_3d)
    if n_ctrl == 0:
        return []
    if n_ctrl == 1:
        return [points_3d[0].copy() for _ in range(max(1, num_points))]
    if n_ctrl == 2:
        return [points_3d[0].lerp(points_3d[1], i / (num_points - 1)) for i in range(num_points)]
    if n_ctrl < 4:
        return interpolate_curve_3d(points_3d, num_points=num_points)
    
    p = 3
    m = n_ctrl + p + 1
    knot = [0.0] * (p + 1)
    inner_count = m - 2 * (p + 1)
    if inner_count > 0:
        step = 1.0 / (inner_count + 1)
        for j in range(1, inner_count + 1):
            knot.append(step * j)
    knot += [1.0] * (p + 1)
    t0 = knot[p]
    t1 = knot[-p - 1]
    samples = []
    for i in range(num_points):
        if num_points == 1:
            u = t0
        else:
            u = t0 + (t1 - t0) * (i / (num_points - 1))
            if i == num_points - 1:
                u = min(max(u, t0), t1 - 1e-9)
        samples.append(_de_boor_cubic(knot, points_3d, u))
    samples[0] = points_3d[0].copy()
    samples[-1] = points_3d[-1].copy()
    return samples


def calculate_smooth_radii(curve_points_3d, radii_3d, smooth_curve_points_3d, tensions=None, sharp_points=None):
    """Calculate smoothly interpolated radii for the given curve points."""
    use_bspline_path = getattr(state, 'bspline_mode', False)

    if use_bspline_path and len(curve_points_3d) >= 2:
        dense_count = max(512, len(curve_points_3d) * 64)
        dense_curve = bspline_cubic_open_uniform(curve_points_3d, dense_count)
        if len(dense_curve) < 2:
            dense_curve = curve_points_3d[:]

        cumlen = [0.0]
        for i in range(len(dense_curve) - 1):
            cumlen.append(cumlen[-1] + (dense_curve[i+1] - dense_curve[i]).length)
        total_len = cumlen[-1]
        if total_len < 1e-6:
            return [radii_3d[0]] * len(smooth_curve_points_3d)

        def seq_nearest_indices(query_points, start_idx=0):
            result_params = []
            last_idx = start_idx
            n_samples = len(dense_curve)
            for qp in query_points:
                best_i = last_idx
                best_d = float('inf')
                end_i = min(n_samples - 1, last_idx + 256)
                for s in range(last_idx, end_i + 1):
                    d = (qp - dense_curve[s]).length
                    if d < best_d:
                        best_d = d
                        best_i = s
                    else:
                        if s > last_idx + 8:
                            break
                last_idx = best_i
                result_params.append(cumlen[best_i] / total_len)
            return result_params

        control_params = [0.0]
        if len(curve_points_3d) > 2:
            interior = curve_points_3d[1:-1]
            interior_params = seq_nearest_indices(interior, start_idx=0)
            control_params += interior_params
        control_params.append(1.0)

        smooth_params = seq_nearest_indices(smooth_curve_points_3d, start_idx=0)
        params = control_params
    else:
        control_point_arc_lengths = [0.0]
        for i in range(len(curve_points_3d) - 1):
            length = (curve_points_3d[i+1] - curve_points_3d[i]).length
            control_point_arc_lengths.append(control_point_arc_lengths[-1] + length)
        total_length = control_point_arc_lengths[-1]
        if total_length < 1e-6:
            return [radii_3d[0]] * len(smooth_curve_points_3d)
        params = [l / total_length for l in control_point_arc_lengths]

        smooth_params = []
        current_segment_idx = 0
        for point in smooth_curve_points_3d:
            while current_segment_idx < len(curve_points_3d) - 2:
                p1 = curve_points_3d[current_segment_idx]
                p2 = curve_points_3d[current_segment_idx + 1]
                p3 = curve_points_3d[current_segment_idx + 2]
                v_seg1 = p2 - p1
                len_seg1 = v_seg1.length
                v_seg2 = p3 - p2
                len_seg2 = v_seg2.length
                if len_seg1 < 1e-6 or len_seg2 < 1e-6:
                    break
                dir_seg1 = v_seg1.normalized()
                t1 = (point - p1).dot(dir_seg1)
                closest1 = p1 + dir_seg1 * max(0, min(t1, len_seg1))
                dist1 = (point - closest1).length
                dir_seg2 = v_seg2.normalized()
                t2 = (point - p2).dot(dir_seg2)
                closest2 = p2 + dir_seg2 * max(0, min(t2, len_seg2))
                dist2 = (point - closest2).length
                if dist2 < dist1:
                    current_segment_idx += 1
                else:
                    break
            p1 = curve_points_3d[current_segment_idx]
            p2 = curve_points_3d[current_segment_idx + 1]
            segment_vec = p2 - p1
            segment_len = segment_vec.length
            t = 0.0
            if segment_len > 1e-6:
                segment_dir = segment_vec.normalized()
                t = (point - p1).dot(segment_dir)
                t = max(0, min(t, segment_len))
            param = (control_point_arc_lengths[current_segment_idx] + t) / total_length
            smooth_params.append(param)

    if tensions is None:
        tensions = [0.5] * len(curve_points_3d)
    
    while len(tensions) < len(curve_points_3d):
        tensions.append(0.5)

    smooth_radii = []
    if sharp_points is None:
        sharp_points = set()
    
    for i, param in enumerate(smooth_params):
        segment = 0
        while segment < len(params) - 1 and param > params[segment + 1]:
            segment += 1
        if segment >= len(params) - 1:
            radius = radii_3d[-1]
        else:
            segment_t = 0
            if params[segment + 1] > params[segment]:
                segment_t = (param - params[segment]) / (params[segment + 1] - params[segment])
            r1 = radii_3d[segment]
            r2 = radii_3d[segment + 1]
            if segment > 0:
                r0 = radii_3d[segment - 1]
            else:
                r0 = r1 - (r2 - r1)
            if segment + 2 < len(radii_3d):
                r3 = radii_3d[segment + 2]
            else:
                r3 = r2 + (r2 - r1)
            tension1 = tensions[segment]
            tension2 = tensions[segment + 1]

            is_sharp_0 = segment in sharp_points
            is_sharp_1 = (segment + 1) in sharp_points
            
            def clamp_monotonic_tangent(r_prev, r_curr, r_next, m):
                delta1 = r_next - r_curr
                delta0 = r_curr - r_prev
                if (delta0 == 0 or delta1 == 0):
                    return 0.0
                if (delta1 > 0 and m < 0) or (delta1 < 0 and m > 0):
                    return 0.0
                max_m = 3 * min(abs(delta0), abs(delta1))
                return max(-max_m, min(m, max_m))
            
            if is_sharp_0 and is_sharp_1:
                radius = r1 + segment_t * (r2 - r1)
            elif not is_sharp_0 and not is_sharp_1:
                raw_m1 = (1 - tension1) * (r2 - r0)
                raw_m2 = (1 - tension2) * (r3 - r1)
                m1 = clamp_monotonic_tangent(r0, r1, r2, raw_m1)
                m2 = clamp_monotonic_tangent(r1, r2, r3, raw_m2)
                h1 = 2*segment_t**3 - 3*segment_t**2 + 1
                h2 = -2*segment_t**3 + 3*segment_t**2
                h3 = segment_t**3 - 2*segment_t**2 + segment_t
                h4 = segment_t**3 - segment_t**2
                radius = h1*r1 + h2*r2 + h3*m1 + h4*m2
            else:
                blend = 3*segment_t**2 - 2*segment_t**3
                h1 = 2*segment_t**3 - 3*segment_t**2 + 1
                h2 = -2*segment_t**3 + 3*segment_t**2
                h3 = segment_t**3 - 2*segment_t**2 + segment_t
                h4 = segment_t**3 - segment_t**2
                if is_sharp_0:
                    m1 = 0
                    m2 = (1 - tension2) * (r3 - r1)
                    radius = (1 - blend) * (r1 + segment_t * (r2 - r1)) + blend * (h1*r1 + h2*r2 + h3*m1 + h4*m2)
                elif is_sharp_1:
                    m1 = (1 - tension1) * (r2 - r0)
                    m2 = 0
                    radius = (1 - blend) * (r1 + segment_t * (r2 - r1)) + blend * (h1*r1 + h2*r2 + h3*m1 + h4*m2)
        radius = max(state.MIN_RADIUS, radius)
        smooth_radii.append(radius)
    
    if len(smooth_radii) > 3:
        smoothed = [smooth_radii[0]]
        for i in range(1, len(smooth_radii)-1):
            avg = (smooth_radii[i-1] + smooth_radii[i+1]) * 0.5
            if smooth_radii[i] > avg:
                smoothed.append(avg)
            else:
                smoothed.append(smooth_radii[i])
        smoothed.append(smooth_radii[-1])
        smooth_radii = smoothed
    return smooth_radii


def resample_curve(curve_points, segments):
    """Resample a curve to have a specific number of segments."""
    if len(curve_points) < 2:
        return curve_points.copy()
    
    total_length = 0
    segment_lengths = []
    
    for i in range(len(curve_points) - 1):
        length = (curve_points[i+1] - curve_points[i]).length
        segment_lengths.append(length)
        total_length += length
    
    resampled_points = []
    
    for i in range(segments + 1):
        t = i / segments
        current_length = 0
        segment = 0
        
        while segment < len(segment_lengths) and current_length + segment_lengths[segment] < t * total_length:
            current_length += segment_lengths[segment]
            segment += 1
        
        if segment >= len(segment_lengths):
            resampled_points.append(curve_points[-1].copy())
        else:
            segment_t = 0
            if segment_lengths[segment] > 0:
                segment_t = (t * total_length - current_length) / segment_lengths[segment]
            p1 = curve_points[segment]
            p2 = curve_points[segment + 1]
            resampled_points.append(p1.lerp(p2, segment_t))
    
    return resampled_points


def resample_radii(radii, segments):
    """Resample radius values to match a specific number of segments."""
    if len(radii) < 2:
        return radii.copy()
    
    resampled_radii = []
    
    for i in range(segments + 1):
        t = i / segments
        segment = int(t * (len(radii) - 1))
        segment = max(0, min(segment, len(radii) - 2))
        segment_t = (t * (len(radii) - 1)) - segment
        r1 = radii[segment]
        r2 = radii[segment + 1]
        resampled_radii.append(r1 + segment_t * (r2 - r1))
    
    return resampled_radii


def create_coordinate_system(direction):
    """Create a consistent coordinate system from a direction vector."""
    direction = direction.normalized()
    
    x_alignment = abs(direction.dot(Vector((1, 0, 0))))
    y_alignment = abs(direction.dot(Vector((0, 1, 0))))
    z_alignment = abs(direction.dot(Vector((0, 0, 1))))
    
    if x_alignment <= y_alignment and x_alignment <= z_alignment:
        side = Vector((1, 0, 0)).cross(direction)
    elif y_alignment <= x_alignment and y_alignment <= z_alignment:
        side = Vector((0, 1, 0)).cross(direction)
    else:
        side = Vector((0, 0, 1)).cross(direction)
    
    if side.length < 0.001:
        side = Vector((0, 1, 0)).cross(direction)
        if side.length < 0.001:
            side = Vector((0, 0, 1)).cross(direction)
    
    side = side.normalized()
    up = direction.cross(side)
    
    return direction, side, up


def create_consistent_coordinate_systems(curve_points):
    """Create consistent coordinate systems along a curve to prevent twisting."""
    if len(curve_points) < 2:
        return []
    
    dir_vec = curve_points[1] - curve_points[0]
    direction_normalized = Vector((0, 0, 0))

    if dir_vec.length >= 0.0001:
        direction_normalized = dir_vec.normalized()
    elif len(curve_points) > 2:
        dir_vec_fallback1 = curve_points[2] - curve_points[0]
        if dir_vec_fallback1.length >= 0.0001:
            direction_normalized = dir_vec_fallback1.normalized()
        else:
            dir_vec_fallback2 = curve_points[2] - curve_points[1]
            if dir_vec_fallback2.length >= 0.0001:
                direction_normalized = dir_vec_fallback2.normalized()
            else:
                direction_normalized = Vector((0, 0, 1))
    else:
        direction_normalized = Vector((0, 0, 1))
    
    direction, side, up = create_coordinate_system(direction_normalized)
    coordinate_systems = [(direction, side, up)]
    
    for i in range(1, len(curve_points) - 1):
        prev_point = curve_points[i - 1]
        current_point = curve_points[i]
        next_point = curve_points[i + 1]
        
        incoming = (current_point - prev_point).normalized()
        outgoing = (next_point - current_point).normalized()
        
        if incoming.dot(outgoing) < -0.99:
            direction = coordinate_systems[-1][0]
        else:
            direction = (incoming + outgoing).normalized()
        
        prev_direction, prev_side, prev_up = coordinate_systems[-1]
        projected_side = prev_side - prev_side.dot(direction) * direction
        
        if projected_side.length < 0.001:
            direction, side, up = create_coordinate_system(direction)
        else:
            side = projected_side.normalized()
            up = direction.cross(side)
        
        coordinate_systems.append((direction, side, up))
    
    if len(curve_points) > 1:
        dir_vec = curve_points[-1] - curve_points[-2]
        direction_normalized = Vector((0, 0, 0))

        if dir_vec.length >= 0.0001:
            direction_normalized = dir_vec.normalized()
        elif len(curve_points) > 2:
            dir_vec_fallback1 = curve_points[-1] - curve_points[-3]
            if dir_vec_fallback1.length >= 0.0001:
                direction_normalized = dir_vec_fallback1.normalized()
            else:
                dir_vec_fallback2 = curve_points[-2] - curve_points[-3]
                if dir_vec_fallback2.length >= 0.0001:
                    direction_normalized = dir_vec_fallback2.normalized()
                else:
                    if coordinate_systems and coordinate_systems[-1][0].length >= 0.0001:
                        direction_normalized = coordinate_systems[-1][0]
                    else:
                        direction_normalized = Vector((0, 0, 1))
        else:
            if coordinate_systems and coordinate_systems[-1][0].length >= 0.0001:
                direction_normalized = coordinate_systems[-1][0]
            else:
                direction_normalized = Vector((0, 0, 1))
        
        direction = direction_normalized
        prev_direction, prev_side, prev_up = coordinate_systems[-1]
        projected_side = prev_side - prev_side.dot(direction) * direction
        
        if projected_side.length < 0.001:
            direction, side, up = create_coordinate_system(direction)
        else:
            side = projected_side.normalized()
            up = direction.cross(side)
        
        coordinate_systems.append((direction, side, up))
    
    return coordinate_systems


def find_closest_point(context, mouse_pos, points_3d, threshold=20):
    """Find the closest point to the mouse position using a fixed threshold."""
    closest_index = -1
    closest_distance = threshold

    for i, point_3d in enumerate(points_3d):
        point_2d = conversion.get_2d_from_3d(context, point_3d)

        if point_2d is not None:
            distance = math.sqrt(
                (mouse_pos[0] - point_2d[0]) ** 2
                + (mouse_pos[1] - point_2d[1]) ** 2
            )

            if distance < closest_distance:
                closest_distance = distance
                closest_index = i

    return closest_index


def find_closest_point_with_screen_radius(
    context,
    mouse_pos,
    points_3d,
    radii_3d,
    radius_factor=1.0,
    min_threshold=6.0,
    max_threshold=40.0,
):
    """Find closest point using a threshold derived from screen-space radius."""
    closest_index = -1
    closest_distance = float("inf")

    for i, point_3d in enumerate(points_3d):
        if i >= len(radii_3d):
            break

        radius_3d = radii_3d[i]
        point_2d = conversion.get_2d_from_3d(context, point_3d)

        if point_2d is None:
            continue

        screen_radius = conversion.get_consistent_screen_radius(
            context, radius_3d, point_3d
        )
        if screen_radius <= 0.0:
            continue

        threshold = max(
            min_threshold,
            min(max_threshold, screen_radius * radius_factor),
        )

        distance = math.sqrt(
            (mouse_pos[0] - point_2d[0]) ** 2 + (mouse_pos[1] - point_2d[1]) ** 2
        )

        if distance <= threshold and distance < closest_distance:
            closest_distance = distance
            closest_index = i

    return closest_index


def find_radius_circle_hover(context, mouse_pos, points_3d, radii_3d, threshold=15):
    """Find if the mouse is hovering near any radius circle."""
    closest_index = -1
    closest_distance = threshold
    
    for i, (point_3d, radius_3d) in enumerate(zip(points_3d, radii_3d)):
        point_2d = conversion.get_2d_from_3d(context, point_3d)
        
        if point_2d is not None:
            screen_radius = conversion.get_consistent_screen_radius(context, radius_3d, point_3d)
            center_distance = math.sqrt((mouse_pos[0] - point_2d[0])**2 + (mouse_pos[1] - point_2d[1])**2)
            circle_distance = abs(center_distance - screen_radius)
            
            if circle_distance < closest_distance:
                closest_distance = circle_distance
                closest_index = i
    
    return closest_index


def find_tension_control_hover(context, mouse_pos, points_3d, radii_3d, tensions, threshold=20):
    """Find if the mouse is hovering near any tension control dot."""
    closest_index = -1
    closest_distance = threshold
    
    while len(tensions) < len(points_3d):
        tensions.append(0.5)
    
    for i, (point_3d, radius_3d, tension) in enumerate(zip(points_3d, radii_3d, tensions)):
        point_2d = conversion.get_2d_from_3d(context, point_3d)
        
        if point_2d is not None:
            screen_radius = conversion.get_consistent_screen_radius(context, radius_3d, point_3d)
            margin = math.radians(18.0)
            angle_span = max(1e-4, 2.0 * math.pi - 2.0 * margin)
            angle = margin + tension * angle_span
            
            fixed_offset = 20.0
            dot_x = point_2d[0] + math.cos(angle) * (screen_radius + fixed_offset)
            dot_y = point_2d[1] + math.sin(angle) * (screen_radius + fixed_offset)
            
            distance = math.sqrt((mouse_pos[0] - dot_x)**2 + (mouse_pos[1] - dot_y)**2)
            
            if distance < closest_distance:
                closest_distance = distance
                closest_index = i
    
    return closest_index


def find_closest_point_on_curve(context, mouse_pos, curve_points_3d, threshold=15):
    """Find the closest point on the curve to the mouse position."""
    if len(curve_points_3d) < 2:
        return False, None, -1
    
    tensions = getattr(state, 'point_tensions', None)
    sharp_points = getattr(state, 'no_tangent_points', set())
    dense_count = max(400, len(curve_points_3d) * 40)
    
    if getattr(state, 'bspline_mode', False):
        dense_curve = bspline_cubic_open_uniform(curve_points_3d, dense_count)
    else:
        dense_curve = interpolate_curve_3d(curve_points_3d, num_points=dense_count, sharp_points=sharp_points, tensions=tensions)
    
    dense_curve_2d = []
    dense_curve_valid = []
    for p in dense_curve:
        p2d = conversion.get_2d_from_3d(context, p)
        if p2d is not None:
            dense_curve_2d.append(p2d)
            dense_curve_valid.append(p)
    
    if len(dense_curve_2d) < 2:
        smooth_curve = dense_curve_valid
    else:
        smooth_curve = [dense_curve_valid[0]]
        accum = 0.0
        last = dense_curve_2d[0]
        for i in range(1, len(dense_curve_2d)):
            seg = math.sqrt((dense_curve_2d[i][0]-last[0])**2 + (dense_curve_2d[i][1]-last[1])**2)
            accum += seg
            if accum >= 0.75:
                smooth_curve.append(dense_curve_valid[i])
                accum = 0.0
                last = dense_curve_2d[i]
        if smooth_curve[-1] is not dense_curve_valid[-1]:
            smooth_curve.append(dense_curve_valid[-1])
    
    min_dist = float('inf')
    closest_point_3d = None
    closest_smooth_index = -1
    for i, point_3d in enumerate(smooth_curve):
        point_2d = conversion.get_2d_from_3d(context, point_3d)
        if point_2d is None:
            continue
        dist = math.sqrt((mouse_pos[0] - point_2d[0]) ** 2 + (mouse_pos[1] - point_2d[1]) ** 2)
        if dist < min_dist:
            min_dist = dist
            closest_point_3d = point_3d
            closest_smooth_index = i
    
    if min_dist > threshold or closest_point_3d is None:
        return False, None, -1
    
    t = closest_smooth_index / (len(smooth_curve) - 1)
    segment_index = min(int(t * (len(curve_points_3d) - 1)), len(curve_points_3d) - 2)
    
    return True, closest_point_3d, segment_index


def calculate_tension_from_mouse(context, point_3d, mouse_pos):
    """Calculate a tension value (0.0 to 1.0) based on angle between projected 3D point and mouse position."""
    point_2d = conversion.get_2d_from_3d(context, point_3d)
    
    if point_2d is None:
        return 0.5
    
    dx = mouse_pos[0] - point_2d[0]
    dy = mouse_pos[1] - point_2d[1]
    angle = math.atan2(dy, dx)
    tension = (angle + math.pi) / (2 * math.pi)
    
    return tension


def normalize_angle(angle):
    """Normalize an angle to the range [-π, π]."""
    while angle > math.pi:
        angle -= 2 * math.pi
    while angle < -math.pi:
        angle += 2 * math.pi
    return angle


def angle_lerp(a1, a2, t):
    """Interpolate between two angles, taking the shortest path."""
    a1 = normalize_angle(a1)
    a2 = normalize_angle(a2)
    
    diff = a2 - a1
    
    if diff > math.pi:
        diff -= 2 * math.pi
    elif diff < -math.pi:
        diff += 2 * math.pi
    
    result = a1 + diff * t
    return normalize_angle(result)


def smooth_falloff(distance, falloff_radius):
    """Calculate a smooth falloff value based on distance."""
    if distance >= falloff_radius:
        return 0.0
    
    t = distance / falloff_radius
    smooth_t = 3 * t * t - 2 * t * t * t
    return 1.0 - smooth_t


def calculate_smooth_twists(curve_points_3d, twists, smooth_curve_points_3d):
    """Calculate smoothly interpolated twist values using segment-based interpolation."""
    if len(curve_points_3d) < 2 or len(twists) < 2:
        return [0.0] * len(smooth_curve_points_3d)
    
    while len(twists) < len(curve_points_3d):
        twists.append(0.0)
    
    use_bspline_path = getattr(state, 'bspline_mode', False)

    if use_bspline_path and len(curve_points_3d) >= 2:
        dense_count = max(512, len(curve_points_3d) * 64)
        dense_curve = bspline_cubic_open_uniform(curve_points_3d, dense_count)
        if len(dense_curve) < 2:
            dense_curve = curve_points_3d[:]

        cumlen = [0.0]
        for i in range(len(dense_curve) - 1):
            cumlen.append(cumlen[-1] + (dense_curve[i+1] - dense_curve[i]).length)
        total_len = cumlen[-1]
        if total_len < 1e-6:
            return [twists[0]] * len(smooth_curve_points_3d)

        def seq_nearest_indices(query_points, start_idx=0):
            result_params = []
            last_idx = start_idx
            n_samples = len(dense_curve)
            for qp in query_points:
                best_i = last_idx
                best_d = float('inf')
                end_i = min(n_samples - 1, last_idx + 256)
                for s in range(last_idx, end_i + 1):
                    d = (qp - dense_curve[s]).length
                    if d < best_d:
                        best_d = d
                        best_i = s
                    else:
                        if s > last_idx + 8:
                            break
                last_idx = best_i
                result_params.append(cumlen[best_i] / total_len)
            return result_params

        control_params = [0.0]
        if len(curve_points_3d) > 2:
            interior = curve_points_3d[1:-1]
            control_params += seq_nearest_indices(interior, start_idx=0)
        control_params.append(1.0)
        params = control_params
        smooth_params = seq_nearest_indices(smooth_curve_points_3d, start_idx=0)
    else:
        dense_count = max(512, len(curve_points_3d) * 64)
        sharp_pts = getattr(state, 'no_tangent_points', set())
        tensions = getattr(state, 'point_tensions', None)

        dense_curve = interpolate_curve_3d(
            curve_points_3d,
            num_points=dense_count,
            sharp_points=sharp_pts,
            tensions=tensions,
        )
        if len(dense_curve) < 2:
            dense_curve = curve_points_3d[:]

        cumlen = [0.0]
        for i in range(len(dense_curve) - 1):
            cumlen.append(cumlen[-1] + (dense_curve[i+1] - dense_curve[i]).length)
        total_len = cumlen[-1]
        if total_len < 1e-6:
            return [twists[0]] * len(smooth_curve_points_3d)

        def seq_nearest_indices(query_points, start_idx=0):
            result_params = []
            last_idx = start_idx
            n_samples = len(dense_curve)
            for qp in query_points:
                best_i = last_idx
                best_d = float('inf')
                end_i = min(n_samples - 1, last_idx + 256)
                for s in range(last_idx, end_i + 1):
                    d = (qp - dense_curve[s]).length
                    if d < best_d:
                        best_d = d
                        best_i = s
                    else:
                        if s > last_idx + 8:
                            break
                last_idx = best_i
                result_params.append(cumlen[best_i] / total_len)
            return result_params

        control_params = [0.0]
        if len(curve_points_3d) > 2:
            interior = curve_points_3d[1:-1]
            control_params += seq_nearest_indices(interior, start_idx=0)
        control_params.append(1.0)
        params = control_params
        smooth_params = seq_nearest_indices(smooth_curve_points_3d, start_idx=0)
    
    unwrapped = [twists[0]]
    for i in range(1, len(twists)):
        prev = unwrapped[-1]
        cur = twists[i]
        diff = cur - prev
        while diff > math.pi:
            cur -= 2 * math.pi
            diff = cur - prev
        while diff < -math.pi:
            cur += 2 * math.pi
            diff = cur - prev
        unwrapped.append(cur)

    n = len(unwrapped)
    m = [0.0] * n
    if n >= 2:
        denom0 = max(1e-9, (params[1] - params[0]))
        m[0] = (unwrapped[1] - unwrapped[0]) / denom0
        denomN = max(1e-9, (params[-1] - params[-2]))
        m[-1] = (unwrapped[-1] - unwrapped[-2]) / denomN
    if n >= 3:
        for i in range(1, n - 1):
            denom = max(1e-9, (params[i + 1] - params[i - 1]))
            m[i] = (unwrapped[i + 1] - unwrapped[i - 1]) / denom

    smooth_twists = []
    for param in smooth_params:
        k = 0
        while k < len(params) - 1 and param > params[k + 1]:
            k += 1
        if k >= len(params) - 1:
            val = unwrapped[-1]
            smooth_twists.append(normalize_angle(val))
            continue
        t0 = params[k]
        t1 = params[k + 1]
        dt = max(1e-9, (t1 - t0))
        u = (param - t0) / dt
        h00 = 2 * u**3 - 3 * u**2 + 1
        h10 = u**3 - 2 * u**2 + u
        h01 = -2 * u**3 + 3 * u**2
        h11 = u**3 - u**2
        val = (
            h00 * unwrapped[k]
            + h10 * (dt * m[k])
            + h01 * unwrapped[k + 1]
            + h11 * (dt * m[k + 1])
        )
        smooth_twists.append(normalize_angle(val))

    if len(smooth_twists) >= 2:
        smooth_twists[0] = twists[0]
        smooth_twists[-1] = twists[-1]

    return smooth_twists


def calculate_smooth_roundness(curve_points_3d, roundness_values, smooth_curve_points_3d):
    """Calculate smoothly interpolated roundness values using segment-based interpolation."""
    if not curve_points_3d or not roundness_values or not smooth_curve_points_3d:
        return [0.3] * len(smooth_curve_points_3d)
    
    if len(curve_points_3d) != len(roundness_values):
        return [0.3] * len(smooth_curve_points_3d)
    
    if len(curve_points_3d) == 1:
        return [roundness_values[0]] * len(smooth_curve_points_3d)
    
    smooth_roundness = []
    
    for smooth_point in smooth_curve_points_3d:
        min_dist_sq = float('inf')
        best_segment_idx = 0
        
        for i in range(len(curve_points_3d) - 1):
            p1 = curve_points_3d[i]
            p2 = curve_points_3d[i + 1]
            segment_vec = p2 - p1
            segment_length_sq = segment_vec.length_squared
            
            if segment_length_sq < 1e-10:
                closest_point_on_segment = p1
            else:
                point_vec = smooth_point - p1
                t = point_vec.dot(segment_vec) / segment_length_sq
                t = max(0.0, min(1.0, t))
                closest_point_on_segment = p1 + t * segment_vec
            
            dist_sq = (smooth_point - closest_point_on_segment).length_squared
            
            if dist_sq < min_dist_sq:
                min_dist_sq = dist_sq
                best_segment_idx = i
        
        p1 = curve_points_3d[best_segment_idx]
        p2 = curve_points_3d[best_segment_idx + 1]
        roundness1 = roundness_values[best_segment_idx]
        roundness2 = roundness_values[best_segment_idx + 1]
        
        segment_vec = p2 - p1
        segment_length_sq = segment_vec.length_squared
        
        if segment_length_sq < 1e-10:
            t = 0.0
        else:
            point_vec = smooth_point - p1
            t = point_vec.dot(segment_vec) / segment_length_sq
            t = max(0.0, min(1.0, t))
        
        if abs(roundness1 - 1.0) < 1e-6 and abs(roundness2 - 1.0) < 1e-6:
            interpolated_roundness = 1.0
        else:
            interpolated_roundness = roundness1 + (roundness2 - roundness1) * t
            if interpolated_roundness >= 0.999:
                interpolated_roundness = 1.0
        
        smooth_roundness.append(interpolated_roundness)
    
    return smooth_roundness


def register():
    pass


def unregister():
    pass
