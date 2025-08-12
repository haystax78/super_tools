import bmesh


def get_border_edges(faces):
    """Get edges that form the border of a face selection"""
    if not faces:
        return []
    
    # Count how many selected faces are adjacent to each edge
    edge_face_count = {}
    for face in faces:
        for edge in face.edges:
            if edge in edge_face_count:
                edge_face_count[edge] += 1
            else:
                edge_face_count[edge] = 1
    
    # Border edges are those with only one adjacent selected face
    border_edges = [edge for edge, count in edge_face_count.items() if count == 1]
    return border_edges


def identify_top_faces(extruded_faces, border_edges):
    """Identify top faces that don't share edges with the original border"""
    if not extruded_faces or not border_edges:
        return extruded_faces if extruded_faces else []
    
    top_faces = []
    border_edges_set = set(border_edges)  # Convert to set for faster lookup
    
    for face in extruded_faces:
        # Check if this face shares any edges with the original border
        shares_border_edge = False
        for edge in face.edges:
            if edge in border_edges_set:
                shares_border_edge = True
                break
        
        # If it doesn't share border edges, it's a top face
        if not shares_border_edge:
            top_faces.append(face)
    
    return top_faces
