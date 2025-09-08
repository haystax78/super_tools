from mathutils import Vector, Matrix
from typing import Tuple
import numpy as np


def compute_similarity_transform_from_points(
    S_A: Vector, S_B: Vector, S_C: Vector,
    T_A: Vector, T_B: Vector, T_C: Vector
) -> Tuple[Matrix, float, Vector]:
    """
    Compute uniform-scale similarity transform (R, s, t) that maps the source triangle
    (S_A, S_B, S_C) near the target triangle (T_A, T_B, T_C) while ensuring A maps exactly:

        p' = R * (s * (p - S_A)) + T_A

    Returns: (R, s, t) such that the equivalent affine is: p' = (s R) p + t.
    We derive t as t = T_A - s * R * S_A.
    """
    # Center at A
    Xb = S_B - S_A
    Xc = S_C - S_A
    Yb = T_B - T_A
    Yc = T_C - T_A

    # Build 3x2 matrices
    X = np.column_stack((np.array(Xb), np.array(Xc)))  # 3x2
    Y = np.column_stack((np.array(Yb), np.array(Yc)))  # 3x2

    if not np.isfinite(X).all() or not np.isfinite(Y).all():
        raise ValueError("Non-finite values in point data")

    # Covariance
    H = X @ Y.T  # 3x3

    # SVD and rotation
    U, Svals, Vt = np.linalg.svd(H)
    V = Vt.T
    R_np = V @ U.T
    if np.linalg.det(R_np) < 0:
        V[:, -1] *= -1
        R_np = V @ U.T

    # Uniform scale: s = trace(S) / ||X||^2
    denom = float((X ** 2).sum())
    s = 1.0 if denom < 1e-16 else (Svals.sum() / denom)

    # Convert rotation to mathutils.Matrix
    R = Matrix([list(R_np[0]), list(R_np[1]), list(R_np[2])])

    # Translation so that A maps exactly
    t = T_A - (R @ S_A) * s
    return R, float(s), t
