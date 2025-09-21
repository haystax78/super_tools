import numpy as np
from mathutils import Matrix, Vector
from typing import Tuple

# Rigid/Similarity CPD step adapted for NumPy. We move Y towards X.
# X: (N,3) fixed target points. Y: (M,3) moving source points.


def _init_sigma2(Y: np.ndarray, X: np.ndarray) -> float:
    if X.size == 0 or Y.size == 0:
        return 1.0
    N, D = X.shape
    M, _ = Y.shape
    # Use average squared distance between sets as initial variance (as in CPD)
    diff = X.mean(axis=0) - Y.mean(axis=0)
    var = (np.sum((X - X.mean(axis=0)) ** 2) / N + np.sum((Y - Y.mean(axis=0)) ** 2) / M)
    sigma2 = var / (D)
    return max(sigma2, 1e-6)


def cpd_rigid_step(
    Y: np.ndarray,  # (M,3) moving
    X: np.ndarray,  # (N,3) fixed
    sigma2: float | None = None,
    w: float = 0.0,
    allow_scale: bool = False,
) -> Tuple[Matrix, float, Vector, float, float, int]:
    """
    Perform one CPD rigid/similarity EM step that transforms Y towards X.
    Returns (R, s, t, sigma2_new, Np, outlier_count)
    - R: 3x3 rotation (mathutils.Matrix)
    - s: uniform scale (float) (1.0 if allow_scale is False)
    - t: translation (mathutils.Vector)
    - sigma2_new: updated variance
    - Np: effective inlier count (float)
    - outlier_count: estimated number of outlier correspondences
    """
    if X.ndim != 2 or Y.ndim != 2:
        raise ValueError("X and Y must be 2D arrays")
    if X.shape[1] != 3 or Y.shape[1] != 3:
        raise ValueError("X and Y must have shape (*, 3)")

    N, D = X.shape
    M, _ = Y.shape

    if sigma2 is None or sigma2 <= 0:
        sigma2 = _init_sigma2(Y, X)

    # E-step: posterior P (N x M). Normalize each row (per X_n) with outlier term.
    # c = (2*pi*sigma2)^{D/2} * w/(1-w) * M/N
    c = (2.0 * np.pi * sigma2) ** (D / 2.0) * (w / max(1.0 - w, 1e-9)) * (M / max(N, 1))

    # Pairwise squared distances D2[n, m] = ||X_n - Y_m||^2
    x2 = np.sum(X**2, axis=1, keepdims=True)      # (N,1)
    y2 = np.sum(Y**2, axis=1, keepdims=True).T    # (1,M)
    D2 = x2 + y2 - 2.0 * (X @ Y.T)               # (N,M)

    K = np.exp(-D2 / (2.0 * sigma2))             # (N,M)
    den = K.sum(axis=1, keepdims=True) + c       # (N,1)
    den = np.maximum(den, 1e-12)
    P = K / den                                   # (N,M)
    P = np.nan_to_num(P, nan=0.0, posinf=0.0, neginf=0.0)

    # Column/row sums
    P1 = P.sum(axis=0)          # (M,)
    Pt1 = P.sum(axis=1)         # (N,)
    Np = float(P1.sum())        # scalar
    if Np < 3.0:
        # Not enough effective correspondences; gently increase sigma2 and do no-op transform
        sigma2_new = max(float(sigma2) * 1.1, 1e-6)
        return Matrix.Identity(3), 1.0, Vector((0.0, 0.0, 0.0)), sigma2_new, Np, 0

    # Compute weighted means
    mu_x = (X.T @ Pt1) / (Np + 1e-9)   # (3,)
    mu_y = (Y.T @ P1) / (Np + 1e-9)    # (3,)

    # Centered
    Xc = X - mu_x
    Yc = Y - mu_y

    # Compute cross-covariance A = Xc^T P Yc
    A = Xc.T @ (P @ Yc)

    # SVD for rotation
    try:
        U, Svals, Vt = np.linalg.svd(A, full_matrices=False)
    except Exception:
        # Add small jitter on diagonal and retry
        A_jit = A + 1e-8 * np.eye(D, dtype=A.dtype)
        U, Svals, Vt = np.linalg.svd(A_jit, full_matrices=False)
    C = np.eye(D)
    if np.linalg.det(U @ Vt) < 0:
        C[-1, -1] = -1
    R_np = U @ C @ Vt

    # Scale
    if allow_scale:
        num = np.sum(Svals * C.diagonal())
        # trace(Yc^T diag(P1) Yc) = sum_m P1_m * ||Yc_m||^2
        den_scale = float(np.sum(P1[:, None] * (Yc ** 2)))
        den_scale = den_scale if den_scale > 1e-16 else 1.0
        s = num / den_scale
    else:
        s = 1.0

    # Translation
    t_np = mu_x - s * (R_np @ mu_y)

    # Update sigma^2
    trX = float(np.sum(Pt1[:, None] * (Xc ** 2)))
    trY = float(np.sum(P1[:, None] * (Yc ** 2)))
    sigma2_new = (trX + s * s * trY - 2.0 * s * np.sum(Svals * C.diagonal())) / (Np * D + 1e-9)
    # Clamp sigma2 to reasonable range to avoid collapse/explosion
    sigma2_new = float(np.clip(sigma2_new, 1e-8, 1e6))

    # Outliers (approx): count targets with high c/(sum+ c) weight
    # Rough outlier estimate: fraction controlled by w over total correspondences
    outliers = int(round(w * N)) if N > 0 else 0

    R = Matrix((Vector(R_np[0]), Vector(R_np[1]), Vector(R_np[2])))
    t = Vector(t_np.tolist())
    return R, float(s), t, float(sigma2_new), float(Np), int(outliers)
