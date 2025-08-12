"""
Performance optimization utilities for proportional editing operations.
Provides optimized algorithms for dense mesh processing.
"""

import bmesh
import mathutils
from mathutils import Vector
import math


class ProportionalFalloffCache:
    """Cache for proportional falloff calculations to avoid redundant computations"""
    
    def __init__(self):
        self.vertex_distances = {}  # Cache of vertex distances to selection
        self.selection_hash = None  # Hash of current selection for cache invalidation
        self.last_falloff_size = None
        self.last_falloff_type = None
        self.cached_proportional_verts = {}
        self.last_use_border_anchors = None
        self.last_world_scale = None  # Store tuple(scale_x, scale_y, scale_z)
    
    def get_selection_hash(self, selected_faces):
        """Generate a hash for the current selection to detect changes"""
        face_indices = tuple(sorted(f.index for f in selected_faces))
        return hash(face_indices)
    
    def is_cache_valid(self, selected_faces, falloff_size, falloff_type, use_border_anchors, world_scale_tuple):
        """Check if cached data is still valid"""
        current_hash = self.get_selection_hash(selected_faces)
        return (self.selection_hash == current_hash and 
                self.last_falloff_size == falloff_size and
                self.last_falloff_type == falloff_type and
                self.last_use_border_anchors == use_border_anchors and
                self.last_world_scale == world_scale_tuple)
    
    def invalidate_cache(self):
        """Clear all cached data"""
        self.vertex_distances.clear()
        self.cached_proportional_verts.clear()
        self.selection_hash = None
        self.last_falloff_size = None
        self.last_falloff_type = None
        self.last_use_border_anchors = None
        self.last_world_scale = None


def get_proportional_vertices_optimized(selected_faces, bm, proportional_size, falloff_type, center_point_local=None, cache=None, world_matrix=None, use_border_anchors=False, use_topology_distance=True):
    """
    Get vertices within proportional editing radius with optimized performance for dense meshes.
    Uses caching and batched processing to reduce computation overhead.
    
    Args:
        selected_faces: List of selected bmesh faces
        bm: bmesh object
        proportional_size: Proportional editing radius (in world space)
        falloff_type: Falloff type ('SMOOTH', 'SPHERE', 'ROOT', 'INVERSE_SQUARE', 'SHARP', 'LINEAR')
        center_point_local: Fixed center point in local space for distance calculations
        cache: ProportionalFalloffCache instance for caching results
        world_matrix: Object's world transformation matrix for coordinate space conversion
        use_border_anchors: Use border anchors mode to measure falloff distances from neighboring non-selected vertices
        use_topology_distance: Use topology-based distance along edges instead of radial distance
        
    Returns:
        dict: {vertex: weight} mapping for vertices within proportional radius
    """
    if not selected_faces or proportional_size <= 0:
        return {}
    
    # Determine world scale tuple for cache purposes
    if world_matrix is not None:
        scale = world_matrix.to_scale()
        world_scale_tuple = (round(scale.x, 6), round(scale.y, 6), round(scale.z, 6))
    else:
        world_scale_tuple = (1.0, 1.0, 1.0)

    # Check cache validity
    if cache and cache.is_cache_valid(selected_faces, proportional_size, falloff_type, use_border_anchors, world_scale_tuple):
        return cache.cached_proportional_verts.copy()
    
    # Get selected vertices
    selected_verts = set()
    for face in selected_faces:
        for vert in face.verts:
            selected_verts.add(vert)
    
    # Use provided center point or calculate from selection
    if center_point_local is not None:
        selection_center = center_point_local
        print(f"DEBUG FALLOFF: Using provided center point: {center_point_local}")
    else:
        if not selected_verts:
            return {}
        selection_center = Vector((0, 0, 0))
        for vert in selected_verts:
            selection_center += vert.co
        selection_center /= len(selected_verts)
        print(f"DEBUG FALLOFF: Calculated center from selected verts: {selection_center}")
    
    # Decide computation space and radius
    if world_matrix is not None:
        # World-space path: transform positions and use world radius directly
        selection_center_ws = world_matrix @ selection_center
        radius = proportional_size
        space = "WORLD"
        print(f"DEBUG FALLOFF: Using WORLD space distances. Radius={radius:.3f}")
    else:
        # Local-space path: assume proportional_size already in local units
        selection_center_ws = None  # not used in local path
        radius = proportional_size
        space = "LOCAL"
        print(f"DEBUG FALLOFF: Using LOCAL space distances. Radius={radius:.3f}")
    
    # Pre-calculate squared proportional size for faster distance comparisons
    proportional_size_sq = radius * radius
    
    # Batch process vertices for better performance
    proportional_verts = {}
    
    # Process selected vertices first (always weight 1.0)
    for vert in selected_verts:
        proportional_verts[vert] = 1.0
    
    print(f"DEBUG FALLOFF: Selection center: {selection_center}")
    print(f"DEBUG FALLOFF: Selected vertices: {len(selected_verts)} (all weight 1.0)")
    
    # When requested, compute border anchors = SELECTED border verts (verts in selection adjacent to any unselected face)
    anchor_positions = None
    if use_border_anchors:
        selected_faces_set = set(selected_faces)
        border_selected_verts = set()
        for sv in selected_verts:
            # A selected vertex is a border vertex if any linked face is not in the selected face set
            for lf in sv.link_faces:
                if lf not in selected_faces_set:
                    border_selected_verts.add(sv)
                    break
        if border_selected_verts:
            if world_matrix is not None:
                anchor_positions = [(world_matrix @ v.co).copy() for v in border_selected_verts]
            else:
                anchor_positions = [v.co.copy() for v in border_selected_verts]
            print(f"DEBUG FALLOFF: Using SELECTED border anchors with {len(anchor_positions)} verts in {space} space")
        else:
            print("DEBUG FALLOFF: No selected border anchors found - falling back to center distance")
    
    # Calculate distances using topology or radial method
    if use_topology_distance:
        # Use topology-based distance calculation (BFS along edges)
        if use_border_anchors and border_selected_verts:
            # Calculate topology distances from border anchors
            topology_distances = calculate_topology_distances_from_anchors(bm, border_selected_verts, radius, world_matrix)
        else:
            # Calculate topology distances from all selected vertices
            topology_distances = calculate_topology_distances_from_anchors(bm, selected_verts, radius, world_matrix)
        
        print(f"DEBUG FALLOFF: Calculated topology distances for {len(topology_distances)} vertices")
        
        # Process vertices with topology distances
        for vert, distance in topology_distances.items():
            if vert in selected_verts:
                proportional_verts[vert] = 1.0
                continue
                
            # Calculate falloff weight
            if distance == 0:
                weight = 1.0
                normalized_distance = 0.0
            else:
                normalized_distance = distance / radius
                weight = calculate_falloff_weight(normalized_distance, falloff_type)
            
            if weight > 0:
                proportional_verts[vert] = weight
    else:
        # Use original radial distance calculation
        unselected_verts = [v for v in bm.verts if v not in selected_verts]
        print(f"DEBUG FALLOFF: Processing {len(unselected_verts)} unselected vertices (radial)")
        
        debug_count = 0
        for vert in unselected_verts:
            # Calculate distance from vertex to selection center or nearest border anchor
            if world_matrix is not None:
                vpos = world_matrix @ vert.co
                center_pos = selection_center_ws
            else:
                vpos = vert.co
                center_pos = selection_center
            
            if anchor_positions:
                # compute min squared distance to anchors
                min_dist_sq = float('inf')
                for aco in anchor_positions:
                    dsq = (vpos - aco).length_squared
                    if dsq < min_dist_sq:
                        min_dist_sq = dsq
                distance_sq = min_dist_sq
            else:
                distance_sq = (vpos - center_pos).length_squared
            
            # Early exit if we're already outside the proportional radius
            if distance_sq > proportional_size_sq:
                continue
            
            # Calculate actual distance only for vertices within radius
            distance = math.sqrt(distance_sq)
            
            # Calculate falloff weight
            if distance == 0:
                weight = 1.0
                normalized_distance = 0.0
            else:
                # Normalize distance (0 to 1) using chosen space radius
                normalized_distance = distance / radius
                weight = calculate_falloff_weight(normalized_distance, falloff_type)
            
            # Debug output for first few vertices
            if debug_count < 5:
                mode = "anchor" if anchor_positions else "center"
                pos_dbg = (world_matrix @ vert.co) if world_matrix is not None else vert.co
                print(f"DEBUG FALLOFF: Vertex {debug_count}: pos={pos_dbg}, space={space}, mode={mode}, dist={distance:.3f}, norm_dist={normalized_distance:.3f}, weight={weight:.3f}")
                debug_count += 1
            
            if weight > 0:
                proportional_verts[vert] = weight
    
    # Debug summary
    total_affected = len(proportional_verts)
    weight_ranges = {'1.0': 0, '0.8-0.99': 0, '0.5-0.79': 0, '0.1-0.49': 0, '0.01-0.09': 0}
    for weight in proportional_verts.values():
        if weight >= 1.0:
            weight_ranges['1.0'] += 1
        elif weight >= 0.8:
            weight_ranges['0.8-0.99'] += 1
        elif weight >= 0.5:
            weight_ranges['0.5-0.79'] += 1
        elif weight >= 0.1:
            weight_ranges['0.1-0.49'] += 1
        else:
            weight_ranges['0.01-0.09'] += 1
    
    print(f"DEBUG FALLOFF: Total affected vertices: {total_affected}")
    print(f"DEBUG FALLOFF: Weight distribution: {weight_ranges}")
    print(f"DEBUG FALLOFF: Falloff type: {falloff_type}")
    
    # Update cache
    if cache:
        cache.selection_hash = cache.get_selection_hash(selected_faces)
        cache.last_falloff_size = proportional_size
        cache.last_falloff_type = falloff_type
        cache.last_use_border_anchors = use_border_anchors
        cache.last_world_scale = world_scale_tuple
        cache.cached_proportional_verts = proportional_verts.copy()
    
    return proportional_verts


def calculate_topology_distances_from_anchors(bm, anchor_verts, max_distance, world_matrix=None):
    """
    Calculate topology-based distances from anchor vertices using BFS along mesh edges.
    
    Args:
        bm: bmesh object
        anchor_verts: Set or list of anchor vertices to measure distances from
        max_distance: Maximum distance to calculate (in world space units)
        world_matrix: Object's world transformation matrix for edge length calculation
        
    Returns:
        dict: {vertex: distance} mapping for vertices within max_distance
    """
    from collections import deque
    
    distances = {}
    queue = deque()
    
    # Initialize anchor vertices with distance 0
    for vert in anchor_verts:
        distances[vert] = 0.0
        queue.append((vert, 0.0))
    
    print(f"DEBUG TOPOLOGY: Starting BFS from {len(anchor_verts)} anchor vertices")
    
    # BFS to calculate topology distances
    processed_count = 0
    while queue:
        current_vert, current_distance = queue.popleft()
        processed_count += 1
        
        # Process all connected vertices
        for edge in current_vert.link_edges:
            neighbor = edge.other_vert(current_vert)
            
            # Calculate edge length in world space if matrix provided
            if world_matrix is not None:
                edge_start = world_matrix @ current_vert.co
                edge_end = world_matrix @ neighbor.co
                edge_length = (edge_end - edge_start).length
            else:
                edge_length = edge.calc_length()
            
            new_distance = current_distance + edge_length
            
            # Skip if beyond max distance
            if new_distance > max_distance:
                continue
            
            # Update distance if this is a shorter path or first visit
            if neighbor not in distances or new_distance < distances[neighbor]:
                distances[neighbor] = new_distance
                queue.append((neighbor, new_distance))
    
    print(f"DEBUG TOPOLOGY: Processed {processed_count} vertices, found distances for {len(distances)} vertices")
    
    return distances


def calculate_falloff_weight(normalized_distance, falloff_type):
    """
    Calculate falloff weight for a normalized distance.
    Separated for better performance and reusability.
    """
    t = normalized_distance
    
    if falloff_type == 'SMOOTH':
        return 1.0 - (3.0 * t * t - 2.0 * t * t * t)
    elif falloff_type == 'SPHERE':
        if t >= 1.0:
            return 0.0
        return math.cos(t * math.pi * 0.5)
    elif falloff_type == 'ROOT':
        return max(0.0, (1.0 - t) ** 0.5)
    elif falloff_type == 'INVERSE_SQUARE':
        if t < 1.0:
            return 1.0 / (1.0 + t * t)
        else:
            return 0.0
    elif falloff_type == 'SHARP':
        return max(0.0, (1.0 - t) * (1.0 - t))
    elif falloff_type == 'LINEAR':
        return max(0.0, 1.0 - t)
    elif falloff_type == 'CONSTANT':
        return 1.0
    elif falloff_type == 'RANDOM':
        # Note: For random, we'd need the vertex index for consistent seeding
        # This is a simplified version
        return 0.5  # Placeholder
    else:
        # Default to smooth
        return 1.0 - (3.0 * t * t - 2.0 * t * t * t)


def batch_vertex_transformation(vertices_weights, translation, rotation_matrix, rotation_center, batch_size=1000):
    """
    Apply transformations to vertices in batches for better performance on dense meshes.
    
    Args:
        vertices_weights: Dict of {vertex: weight} from proportional calculations
        translation: Vector translation to apply
        rotation_matrix: Matrix rotation to apply
        rotation_center: Vector center point for rotation
        batch_size: Number of vertices to process per batch
    """
    vertex_items = list(vertices_weights.items())
    
    for i in range(0, len(vertex_items), batch_size):
        batch = vertex_items[i:i + batch_size]
        
        for vert, weight in batch:
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
