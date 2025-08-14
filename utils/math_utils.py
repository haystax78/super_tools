import mathutils
from mathutils import Vector
from mathutils.kdtree import KDTree
from math import radians
from . import falloff_utils


def calculate_faces_centroid(faces, world_matrix):
    """Calculate the centroid of a list of faces in world space"""
    if not faces:
        return Vector((0, 0, 0))
    
    total_area = 0
    centroid = Vector((0, 0, 0))
    
    for face in faces:
        # Calculate face area
        try:
            area = face.calc_area()
        except:
            continue  # Skip faces that can't calculate area
        
        # Skip faces with zero or negative area
        if area <= 0:
            continue
        
        # Calculate face center
        try:
            center = face.calc_center_median()
        except:
            continue  # Skip faces that can't calculate center
        
        # Transform to world space
        try:
            world_center = world_matrix @ center
        except:
            continue  # Skip faces that can't transform
        
        # Accumulate weighted by area
        centroid += world_center * area
        total_area += area
    
    if total_area > 0:
        centroid /= total_area
    
    return centroid


def calculate_faces_average_normal(faces, world_matrix):
    """Calculate the area-weighted average normal of a list of faces in world space"""
    if not faces:
        return Vector((0, 0, 1))
    
    total_area = 0
    avg_normal = Vector((0, 0, 0))
    
    # Get the world matrix normal transformation
    normal_matrix = world_matrix.to_3x3().inverted().transposed()
    
    for face in faces:
        # Calculate face area
        area = face.calc_area()
        # Skip faces with zero area
        if area <= 0:
            continue
        # Get face normal
        normal = face.normal
        # Transform to world space
        world_normal = (normal_matrix @ normal).normalized()
        
        # Accumulate weighted by area
        avg_normal += world_normal * area
        total_area += area
    
    if total_area > 0:
        avg_normal /= total_area
    else:
        # Fallback if all faces have zero area
        return Vector((0, 0, 1))
    
    # Normalize the result, handling zero-length vectors
    if avg_normal.length > 0:
        return avg_normal.normalized()
    else:
        return Vector((0, 0, 1))


def orient_faces_away_from_point(faces, vertices, pivot_point, world_matrix):
    """
    Rotate faces to orient their average normal away from a pivot point.
    
    Args:
        faces: List of bmesh faces to orient
        vertices: List of bmesh vertices that belong to the faces
        pivot_point: Vector point to orient away from (in world space)
        world_matrix: Object's world transformation matrix
        
    Returns:
        bool: True if rotation was applied, False if no rotation needed
    """
    if not faces or not vertices:
        return False
        
    # Calculate current centroid and normal of the faces (world space)
    faces_centroid_world = calculate_faces_centroid(faces, world_matrix)
    current_normal_world = calculate_faces_average_normal(faces, world_matrix)
    
    # Calculate desired direction (away from pivot point) in world space
    direction_vector = faces_centroid_world - pivot_point
    if direction_vector.length == 0:
        return False
        
    desired_direction = direction_vector.normalized()
    
    # Check if rotation is needed
    if current_normal_world.length == 0:
        return False
        
    angle = current_normal_world.angle(desired_direction)
    if angle <= radians(1):  # Less than 1 degree difference
        return False
        
    # Calculate rotation in world space
    rotation_axis = current_normal_world.cross(desired_direction)
    if rotation_axis.length == 0:
        return False
        
    rotation_axis = rotation_axis.normalized()
    rotation_matrix_world = mathutils.Matrix.Rotation(angle, 3, rotation_axis)
    
    # Convert world space rotation to local space
    rotation_matrix_local = world_matrix.inverted().to_3x3() @ rotation_matrix_world @ world_matrix.to_3x3()
    
    # Calculate faces centroid in local space for vertex operations
    faces_centroid_local = calculate_faces_centroid(faces, mathutils.Matrix.Identity(4))
    
    # Apply rotation to vertices around faces centroid (all in local space)
    for vertex in vertices:
        # Translate to origin (faces centroid in local space)
        pos = vertex.co - faces_centroid_local
        # Apply rotation (local space)
        pos = rotation_matrix_local @ pos
        # Translate back
        vertex.co = pos + faces_centroid_local
        
    return True


def calculate_border_vertices_centroid(selected_faces, bm, world_matrix):
    """
    Calculate centroid of unselected vertices that are directly connected 
    to selected faces by an edge. This finds the "attachment points" where
    the selection connects to the rest of the mesh.
    
    Args:
        selected_faces: List of selected bmesh faces
        bm: bmesh instance
        world_matrix: Object's world transformation matrix
        
    Returns:
        Vector: Centroid of border vertices in world space
    """
    if not selected_faces:
        return Vector((0, 0, 0))
    
    # Get all vertices that belong to selected faces
    selected_verts = set()
    for face in selected_faces:
        for vert in face.verts:
            selected_verts.add(vert)
    
    # Find edges that connect selected faces to unselected geometry
    border_vertices = set()
    
    for vert in selected_verts:
        # Look at all edges connected to this selected vertex
        for edge in vert.link_edges:
            # Get the other vertex of this edge
            other_vert = edge.other_vert(vert)
            
            # If the other vertex is NOT in our selected vertices,
            # then this is a border connection
            if other_vert not in selected_verts:
                border_vertices.add(other_vert)
    
    print(f"Super Orient: Found {len(border_vertices)} border vertices from {len(selected_verts)} selected vertices")
    
    if not border_vertices:
        # Fallback to selection centroid if no border vertices found
        print("Super Orient: No border vertices found, using selection centroid as fallback")
        return calculate_faces_centroid(selected_faces, world_matrix)
    
    # Calculate average position of border vertices
    total_pos = Vector((0, 0, 0))
    for vert in border_vertices:
        world_pos = world_matrix @ vert.co
        total_pos += world_pos
    
    return total_pos / len(border_vertices)


def calculate_proportional_border_vertices_centroid(selected_faces, bm, world_matrix, proportional_size):
    """
    Calculate centroid of vertices that are connected to but outside the proportional editing radius.
    This is used when proportional editing is enabled to find the proper orientation target.
    
    Args:
        selected_faces: List of selected bmesh faces
        bm: bmesh instance
        world_matrix: Object's world transformation matrix
        proportional_size: Proportional editing radius (in world space)
        
    Returns:
        Vector: Centroid of border vertices outside proportional radius in world space
    """
    if not selected_faces or proportional_size <= 0:
        return calculate_border_vertices_centroid(selected_faces, bm, world_matrix)
    
    # Get all vertices from selected faces
    selected_verts = set()
    for face in selected_faces:
        for vert in face.verts:
            selected_verts.add(vert)
    
    # Build KDTree of SELECTED vertices in WORLD space so distances are measured
    # from the SELECTION BORDER (minimum distance to any selected vertex), not
    # from the selection volume center.
    if not selected_verts:
        return Vector((0, 0, 0))

    selected_world = [world_matrix @ v.co for v in selected_verts]
    kd = KDTree(len(selected_world))
    for i, co in enumerate(selected_world):
        kd.insert(co, i)
    kd.balance()

    print(f"DEBUG PIVOT: Proportional size (world): {proportional_size:.3f}")

    # Find vertices that are:
    # 1) within proportional radius measured from the selection BORDER (min distance
    #    to any selected vertex), and
    # 2) their neighbors that are OUTSIDE the radius -> these form the proportional border
    border_vertices = set()

    proportional_verts = set()
    for vert in bm.verts:
        vert_world = world_matrix @ vert.co
        # distance to selection BORDER = nearest selected vertex distance
        _, _, min_dist = kd.find(vert_world)
        if min_dist <= proportional_size:
            proportional_verts.add(vert)

    print(f"DEBUG PIVOT: Found {len(proportional_verts)} vertices within proportional radius (border-based)")

    # Now find vertices outside the radius that connect to vertices inside
    for vert_inside in proportional_verts:
        for edge in vert_inside.link_edges:
            other_vert = edge.other_vert(vert_inside)
            other_world = world_matrix @ other_vert.co
            _, _, dist_other = kd.find(other_world)
            if dist_other > proportional_size:
                border_vertices.add(other_vert)
    
    print(f"Super Orient: Found {len(border_vertices)} proportional border vertices (outside radius {proportional_size:.3f})")
    
    if not border_vertices:
        # Fallback to regular border vertices if no proportional border found
        print("Super Orient: No proportional border vertices found, using regular border calculation")
        return calculate_border_vertices_centroid(selected_faces, bm, world_matrix)
    
    # Calculate average position of border vertices (already in world space)
    total_pos = Vector((0, 0, 0))
    for vert in border_vertices:
        world_pos = world_matrix @ vert.co
        total_pos += world_pos
    
    return total_pos / len(border_vertices)


def get_proportional_vertices(selected_faces, bm, proportional_size, falloff_type='SMOOTH', center_point_local=None):
    """
    Get vertices affected by proportional editing with their influence weights.
    
    Args:
        selected_faces: List of selected bmesh faces
        bm: bmesh instance
        proportional_size: Proportional editing radius
        falloff_type: Falloff type ('SMOOTH', 'SPHERE', 'ROOT', 'INVERSE_SQUARE', 'SHARP', 'LINEAR')
        center_point_local: Fixed center point in local space for distance calculations (if None, calculates from current selection)
        
    Returns:
        dict: {vertex: weight} mapping for vertices within proportional radius
    """
    if not selected_faces or proportional_size <= 0:
        return {}
    
    # Get all vertices from selected faces
    selected_verts = set()
    for face in selected_faces:
        for vert in face.verts:
            selected_verts.add(vert)
    
    # Use provided center point or calculate from current selection (both in local space)
    if center_point_local is not None:
        selection_center = center_point_local
    else:
        # Calculate selection centroid for distance calculations
        if not selected_verts:
            return {}
        
        selection_center = Vector((0, 0, 0))
        for vert in selected_verts:
            selection_center += vert.co
        selection_center /= len(selected_verts)
    
    # Find all vertices within proportional radius
    proportional_verts = {}
    
    for vert in bm.verts:
        # Skip vertices that are already selected
        if vert in selected_verts:
            proportional_verts[vert] = 1.0  # Full influence for selected
            continue
            
        # Calculate minimum distance to any selected vertex
        # This ensures smooth falloff from the selection boundary
        min_distance = float('inf')
        for selected_vert in selected_verts:
            dist = (vert.co - selected_vert.co).length
            if dist < min_distance:
                min_distance = dist
        
        distance = min_distance
        
        # Skip vertices outside proportional radius
        if distance > proportional_size:
            continue
        
        # Calculate falloff weight based on distance
        if distance == 0:
            weight = 1.0
        else:
            # Normalize distance (0 to 1)
            normalized_distance = distance / proportional_size
            # Use unified falloff utilities for consistency
            weight = falloff_utils.calculate_falloff_weight_scalar(normalized_distance, falloff_type)
        
        proportional_verts[vert] = weight
    
    return proportional_verts


def apply_proportional_transformation(vertices_weights, translation, rotation_matrix, rotation_center):
    """
    Apply translation and rotation to vertices with proportional weights.
    
    Args:
        vertices_weights: Dict of {vertex: weight} from get_proportional_vertices
        translation: Vector translation to apply
        rotation_matrix: Matrix rotation to apply
        rotation_center: Vector center point for rotation
    """
    for vert, weight in vertices_weights.items():
        if weight <= 0:
            continue
            
        # Apply weighted translation
        weighted_translation = translation * weight
        
        # Apply weighted rotation
        if rotation_matrix and weight > 0:
            # Translate to rotation center
            pos = vert.co - rotation_center
            # Apply rotation
            rotated_pos = rotation_matrix @ pos
            # Calculate rotation delta
            rotation_delta = rotated_pos - pos
            # Apply weighted rotation delta
            weighted_rotation_delta = rotation_delta * weight
            # Apply both translation and rotation
            vert.co += weighted_translation + weighted_rotation_delta
        else:
            # Just apply translation
            vert.co += weighted_translation


def calculate_spatial_relationship_rotation(
    original_centroid_local, translation, pivot_point, initial_direction_to_pivot, world_matrix
):
    """
    Calculate rotation matrix to maintain spatial relationship between selection and pivot point.
    
    This is the simplified orientation approach that assumes the selection is already properly
    oriented initially and maintains that spatial relationship as it moves.
    
    Args:
        original_centroid_local: Original selection centroid in local space
        translation: Translation vector in local space
        pivot_point: Pivot point in world space
        initial_direction_to_pivot: Initial normalized direction from selection to pivot (world space)
        world_matrix: Object's world transformation matrix
        
    Returns:
        mathutils.Matrix: 3x3 rotation matrix in world space
    """
    # Calculate where the selection centroid should be after translation (in local space)
    target_centroid_local = original_centroid_local + translation
    target_centroid_world = world_matrix @ target_centroid_local
    
    # Calculate rotation to maintain initial spatial relationship with pivot
    # Current direction from pivot to target position
    current_direction_from_pivot = (target_centroid_world - pivot_point).normalized()
    # Initial direction from pivot to original position (opposite of initial_direction_to_pivot)
    initial_direction_from_pivot = -initial_direction_to_pivot
    
    rotation_matrix = mathutils.Matrix.Identity(3)
    
    if current_direction_from_pivot.length > 0 and initial_direction_from_pivot.length > 0:
        angle = initial_direction_from_pivot.angle(current_direction_from_pivot)
        
        if angle > radians(1):  # Significant rotation needed (1 degree threshold)
            rotation_axis = initial_direction_from_pivot.cross(current_direction_from_pivot)
            if rotation_axis.length > 0:
                rotation_axis = rotation_axis.normalized()
                rotation_matrix = mathutils.Matrix.Rotation(angle, 3, rotation_axis)
    
    return rotation_matrix


def apply_spatial_relationship_transformation(
    vertices, original_positions, translation, rotation_matrix, 
    original_centroid_local, world_matrix, weights=None
):
    """
    Apply translation and spatial relationship rotation to vertices.
    
    Args:
        vertices: List of bmesh vertices to transform
        original_positions: Dict of {vertex: original_position} in local space
        translation: Translation vector in local space
        rotation_matrix: Rotation matrix in world space (from calculate_spatial_relationship_rotation)
        original_centroid_local: Original selection centroid in local space (rotation center)
        world_matrix: Object's world transformation matrix
        weights: Optional dict of {vertex: weight} for proportional editing (None = full weight)
    """
    # Convert rotation matrix from world to local using ROTATION-ONLY parts to avoid scale skew
    # Extract object's world rotation (ignore scale) via quaternion
    R_obj_world = world_matrix.to_quaternion().to_matrix()
    R_obj_world_inv = R_obj_world.transposed()  # inverse of pure rotation
    # Similarity transform using rotation-only basis
    local_rotation_matrix = R_obj_world_inv @ rotation_matrix @ R_obj_world
    
    for vert in vertices:
        if vert not in original_positions:
            continue
            
        original_pos = original_positions[vert]
        weight = weights.get(vert, 1.0) if weights else 1.0
        
        if weight > 0:
            # Apply translation
            translated_pos = original_pos + (translation * weight)
            
            # Apply rotation around original centroid
            pos_relative_to_center = original_pos - original_centroid_local
            rotated_relative_pos = local_rotation_matrix @ pos_relative_to_center
            rotation_delta = rotated_relative_pos - pos_relative_to_center
            
            # Apply final position with weighted rotation
            vert.co = translated_pos + (rotation_delta * weight)
