import bpy
import numpy as np
from mathutils import Matrix, Vector
from mathutils.kdtree import KDTree
from typing import Tuple


def sample_object_vertices_world(
    obj: bpy.types.Object,
    max_points: int = 5000,
    seed: int = 0,
    vgroup_name: str | None = None,
) -> np.ndarray:
    """
    Return Nx3 numpy array of world-space vertex positions from a mesh object.
    If vertex count exceeds max_points, randomly sample without replacement.
    """
    if obj is None or obj.type != 'MESH' or obj.data is None:
        return np.zeros((0, 3), dtype=np.float64)

    mesh = obj.data
    # Optionally restrict to vertices that have weight in a named vertex group
    if vgroup_name and obj.vertex_groups and vgroup_name in obj.vertex_groups:
        gidx = obj.vertex_groups[vgroup_name].index
        sel = []
        for v in mesh.vertices:
            has = any((g.group == gidx and g.weight > 0.0) for g in v.groups)
            if has:
                co = obj.matrix_world @ v.co
                sel.append((co.x, co.y, co.z))
        coords_ws = np.array(sel, dtype=np.float64)
    else:
        coords_ws = np.array([tuple(obj.matrix_world @ v.co) for v in mesh.vertices], dtype=np.float64)
    n = coords_ws.shape[0]
    if n <= max_points:
        return coords_ws
    rng = np.random.default_rng(seed)
    idx = rng.choice(n, size=max_points, replace=False)
    return coords_ws[idx]


def build_kdtree(points: np.ndarray) -> KDTree:
    """Build a KDTree from Nx3 numpy array of points."""
    tree = KDTree(points.shape[0])
    for i, (x, y, z) in enumerate(points):
        tree.insert((x, y, z), i)
    tree.balance()
    return tree


def nearest_neighbors(src_pts: np.ndarray, kd: KDTree) -> Tuple[np.ndarray, np.ndarray]:
    """
    For each source point, query nearest neighbor in kd.
    Returns (matches, distances) where matches is Nx3 numpy array.
    """
    matches = np.empty_like(src_pts)
    dists = np.empty((src_pts.shape[0],), dtype=np.float64)
    for i, (x, y, z) in enumerate(src_pts):
        co, index, dist = kd.find((x, y, z))
        matches[i, :] = co
        dists[i] = dist
    return matches, dists


def kabsch_rigid_transform(A: np.ndarray, B: np.ndarray) -> Tuple[Matrix, Vector]:
    """
    Compute rigid transform R, t that best aligns A to B (both Nx3).
    Returns R (3x3 as mathutils.Matrix) and t (mathutils.Vector).
    """
    if A.shape[0] == 0 or B.shape[0] == 0:
        return Matrix.Identity(3), Vector((0.0, 0.0, 0.0))
    # Centroids
    centroid_A = A.mean(axis=0)
    centroid_B = B.mean(axis=0)
    AA = A - centroid_A
    BB = B - centroid_B
    # Covariance
    H = AA.T @ BB
    U, S, Vt = np.linalg.svd(H)
    R = Vt.T @ U.T
    # Reflection fix
    if np.linalg.det(R) < 0:
        Vt[-1, :] *= -1
        R = Vt.T @ U.T
    t = centroid_B - R @ centroid_A
    Rm = Matrix((Vector(R[0]), Vector(R[1]), Vector(R[2])))
    tv = Vector(t.tolist())
    return Rm, tv


def apply_rigid_transform_to_object(obj: bpy.types.Object, R: Matrix, t: Vector) -> None:
    """Apply world-space rigid transform to object's matrix_world in-place."""
    # Compose 4x4: T @ R
    R4 = R.to_4x4()
    T4 = Matrix.Translation(t)
    M = T4 @ R4
    obj.matrix_world = M @ obj.matrix_world


def procrustes_similarity_transform(A: np.ndarray, B: np.ndarray) -> Tuple[Matrix, float, Vector]:
    """
    Compute uniform-scale similarity transform (R, s, t) that best aligns A to B (both Nx3).
    Returns mathutils R, scalar s, and mathutils t.
    """
    if A.shape[0] == 0 or B.shape[0] == 0:
        return Matrix.Identity(3), 1.0, Vector((0.0, 0.0, 0.0))
    centroid_A = A.mean(axis=0)
    centroid_B = B.mean(axis=0)
    AA = A - centroid_A
    BB = B - centroid_B
    H = AA.T @ BB
    U, S, Vt = np.linalg.svd(H)
    R_np = Vt.T @ U.T
    if np.linalg.det(R_np) < 0:
        Vt[-1, :] *= -1
        R_np = Vt.T @ U.T
    denom = float((AA ** 2).sum())
    s = 1.0 if denom < 1e-16 else (S.sum() / denom)
    R = Matrix((Vector(R_np[0]), Vector(R_np[1]), Vector(R_np[2])))
    t = Vector((centroid_B - s * (R_np @ centroid_A)).tolist())
    return R, float(s), t


def apply_similarity_transform_to_object(obj: bpy.types.Object, R: Matrix, s: float, t: Vector) -> None:
    """Apply world-space similarity transform (uniform scale s, rotation R, translation t)."""
    R4 = R.to_4x4()
    S4 = Matrix.Diagonal((s, s, s, 1.0))
    T4 = Matrix.Translation(t)
    M = T4 @ R4 @ S4
    obj.matrix_world = M @ obj.matrix_world
