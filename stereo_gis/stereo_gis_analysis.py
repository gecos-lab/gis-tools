# -*- coding: utf-8 -*-
import math
import numpy as np
from qgis.core import QgsProcessingException


def wrap360(deg: float) -> float:
    deg = deg % 360.0
    return deg if deg >= 0 else deg + 360.0


def deg2rad(deg: float) -> float:
    return deg * math.pi / 180.0


def rad2deg(rad: float) -> float:
    return rad * 180.0 / math.pi


def trend_plunge_to_xyz(trend_deg: float, plunge_deg: float) -> np.ndarray:
    tr = deg2rad(trend_deg)
    pl = deg2rad(plunge_deg)
    x = math.sin(tr) * math.cos(pl)   # East
    y = math.cos(tr) * math.cos(pl)   # North
    z = -math.sin(pl)                 # Up (negative is down-plunge)
    v = np.array([x, y, z], dtype=float)
    n = np.linalg.norm(v)
    return v / n if n else v


def xyz_to_trend_plunge(v: np.ndarray) -> tuple[float, float]:
    x, y, z = float(v[0]), float(v[1]), float(v[2])
    plunge = math.asin(max(-1.0, min(1.0, -z)))
    trend = math.atan2(x, y)
    return wrap360(rad2deg(trend)), rad2deg(plunge)


def dipdir_dip_to_pole_xyz(dipdir_deg: float, dip_deg: float) -> np.ndarray:
    pole_trend = dipdir_deg
    pole_plunge = 90.0 - dip_deg
    return trend_plunge_to_xyz(pole_trend, pole_plunge)

def dipdir2strike(dipdir_deg: float) -> float:
    return wrap360(dipdir_deg - 90.0)

def strike2dipdir(strike_deg: float) -> float:
    return wrap360(strike_deg + 90.0)

def mirror_to_upper_hemisphere(v: np.ndarray) -> np.ndarray:
    return -v if v[2] < 0 else v


def vmf_mean_axial(vectors_xyz: np.ndarray) -> dict:
    if vectors_xyz.shape[0] == 0:
        raise QgsProcessingException("No vectors for VMF.")

    V = np.array([mirror_to_upper_hemisphere(v) for v in vectors_xyz], dtype=float)
    S = V.sum(axis=0)
    S_norm = float(np.linalg.norm(S))
    if S_norm == 0.0:
        return {"mean_xyz": np.array([np.nan, np.nan, np.nan]), "Rbar": 0.0, "kappa": float("nan")}

    mean_xyz = S / S_norm
    n = V.shape[0]
    Rbar = S_norm / n

    denom = max(1e-12, 1.0 - Rbar * Rbar)
    kappa = (Rbar * (3.0 - Rbar * Rbar)) / denom
    return {"mean_xyz": mean_xyz, "Rbar": Rbar, "kappa": kappa}


def bingham_principal_axes_axial(vectors_xyz: np.ndarray) -> dict:
    if vectors_xyz.shape[0] == 0:
        raise QgsProcessingException("No vectors for Bingham summary.")

    V = np.array([mirror_to_upper_hemisphere(v) for v in vectors_xyz], dtype=float)
    V = V / np.linalg.norm(V, axis=1, keepdims=True)

    T = (V.T @ V) / V.shape[0]
    evals, evecs = np.linalg.eigh(T)          # ascending
    idx = np.argsort(evals)[::-1]             # descending
    evals = evals[idx]
    evecs = evecs[:, idx]

    beta = evecs[:, 0]
    beta = beta / np.linalg.norm(beta)
    beta = mirror_to_upper_hemisphere(beta)
    return {"axes_xyz": evecs, "evals": evals, "beta_axis_xyz": beta}


def axial_angular_distance(u: np.ndarray, v: np.ndarray) -> float:
    dot = float(np.clip(abs(np.dot(u, v)), -1.0, 1.0))
    return math.acos(dot)


def kmedoids_pam_axial(
    vectors_xyz: np.ndarray,
    k: int,
    maxiter: int = 100,
    init_medoids: np.ndarray | None = None
):
    n = vectors_xyz.shape[0]
    if n == 0:
        raise QgsProcessingException("No vectors to cluster.")
    if not (1 <= k <= n):
        raise QgsProcessingException(f"k must be in [1, {n}]")

    V = np.array([v / np.linalg.norm(v) for v in vectors_xyz], dtype=float)

    D = np.zeros((n, n), dtype=float)
    for i in range(n):
        for j in range(i + 1, n):
            d = axial_angular_distance(V[i], V[j])
            D[i, j] = d
            D[j, i] = d

    if init_medoids is None:
        medoids = np.arange(k, dtype=int)
    else:
        medoids = np.array(init_medoids, dtype=int)
        if medoids.size != k:
            raise QgsProcessingException("init_medoids must have length k")

    labels = np.zeros(n, dtype=int)

    for _ in range(int(maxiter)):
        dist_to_m = D[:, medoids]
        labels_new = np.argmin(dist_to_m, axis=1)

        medoids_new = medoids.copy()
        for ci in range(k):
            idx = np.where(labels_new == ci)[0]
            if idx.size == 0:
                continue
            intra = D[np.ix_(idx, idx)]
            costs = intra.sum(axis=1)
            medoids_new[ci] = int(idx[np.argmin(costs)])

        if np.array_equal(medoids_new, medoids) and np.array_equal(labels_new, labels):
            labels = labels_new
            medoids = medoids_new
            break

        labels = labels_new
        medoids = medoids_new

    return labels, medoids


def read_orientations_from_layer_selection(layer, is_planes: bool, field1: str, field2: str) -> dict:
    """
    Reads orientations from the layer.
    Uses selected features if any are selected; otherwise uses all features.

    Planes: field1=dip,    field2=dipdir -> vectors are POLES.
    Lines:  field1=plunge, field2=trend  -> vectors are lines.
    """
    idx1 = layer.fields().indexOf(field1)
    idx2 = layer.fields().indexOf(field2)
    if idx1 < 0 or idx2 < 0:
        raise QgsProcessingException("Selected field not found in layer.")

    feats = layer.getSelectedFeatures() if layer.selectedFeatureCount() else layer.getFeatures()

    vectors = []
    strikes = []
    dips = []
    trends = []
    plunges = []

    for f in feats:
        a = f.attributes()
        v1 = a[idx1]
        v2 = a[idx2]
        if v1 is None or v2 is None:
            continue
        try:
            v1 = float(v1)
            v2 = float(v2)
        except Exception:
            continue

        if is_planes:
            dip = v1
            dipdir = wrap360(v2)
            if not (0.0 <= dip <= 90.0):
                continue

            pole = dipdir_dip_to_pole_xyz(dipdir, dip)
            vectors.append(pole)

            dips.append(dip)
            strikes.append(dipdir2strike(dipdir))

            tr, pl = xyz_to_trend_plunge(pole)
            trends.append(tr)
            plunges.append(pl)
        else:
            plunge = v1
            trend = wrap360(v2)
            if not (0.0 <= plunge <= 90.0):
                continue

            line = trend_plunge_to_xyz(trend, plunge)
            vectors.append(line)
            trends.append(trend)
            plunges.append(plunge)

    vectors_xyz = np.asarray(vectors, dtype=float)
    return {
        "vectors_xyz": vectors_xyz,
        "strikes_deg": np.asarray(strikes, dtype=float) if strikes else None,
        "dips_deg": np.asarray(dips, dtype=float) if dips else None,
        "trends_deg": np.asarray(trends, dtype=float),
        "plunges_deg": np.asarray(plunges, dtype=float),
    }