"""Recouvre la transformation similarite (echelle, rotation, translation) qui
envoie les coordonnees MODELE du DWG vers le repere d'AFFICHAGE du PDF.

On ne connait pas la correspondance point a point entre les INSERTs du DWG et
les glyphes du PDF (un symbole PDF = plusieurs paths -> plusieurs glyphes). On la
retrouve par RANSAC : deux paires (p_i->q_a, p_j->q_b) definissent une similarite ;
on compte les INSERTs dont l'image tombe pres d'un glyphe PDF ; on garde la
meilleure hypothese, puis on l'affine par moindres carres sur les inliers.

Cle de robustesse : on ne melange que des points portes par les MEMES calques
(GI-CFA, FAUCHE-CFA...), partages entre DWG et PDF.
"""
from __future__ import annotations

import math
import random


def _similarity_from_2(p1, p2, q1, q2):
    """Similarite envoyant p1->q1 et p2->q2. Retourne (s, cos, sin, tx, ty) ou None."""
    vpx, vpy = p2[0] - p1[0], p2[1] - p1[1]
    vqx, vqy = q2[0] - q1[0], q2[1] - q1[1]
    np2 = vpx * vpx + vpy * vpy
    if np2 < 1e-9:
        return None
    # s*e^{i theta} = vq / vp  (nombres complexes)
    a = (vqx * vpx + vqy * vpy) / np2      # s*cos
    b = (vqy * vpx - vqx * vpy) / np2      # s*sin
    s = math.hypot(a, b)
    if s < 1e-9:
        return None
    tx = q1[0] - (a * p1[0] - b * p1[1])
    ty = q1[1] - (b * p1[0] + a * p1[1])
    return (s, a, b, tx, ty)


def apply_tf(tf, pt):
    s, a, b, tx, ty = tf
    x, y = pt
    return (a * x - b * y + tx, b * x + a * y + ty)


def _build_grid(pts, cell):
    grid = {}
    for idx, q in enumerate(pts):
        key = (int(q[0] // cell), int(q[1] // cell))
        grid.setdefault(key, []).append((idx, q))
    return grid


def _nearest(grid, cell, pt):
    """Retourne (index_q, distance) du plus proche point de la grille."""
    gx, gy = int(pt[0] // cell), int(pt[1] // cell)
    best_i, best = None, 1e18
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            for idx, q in grid.get((gx + dx, gy + dy), ()):
                d = (q[0] - pt[0]) ** 2 + (q[1] - pt[1]) ** 2
                if d < best:
                    best, best_i = d, idx
    return best_i, math.sqrt(best)


def _score(P, grid, cell, tf, tol):
    """Nombre de CIBLES PDF distinctes appariees (injectif) -> immunise contre la
    transformation degeneree qui collapse tous les points sur un seul glyphe."""
    claimed = {}
    for p in P:
        idx, d = _nearest(grid, cell, apply_tf(tf, p))
        if idx is not None and d <= tol and (idx not in claimed or d < claimed[idx]):
            claimed[idx] = d
    return len(claimed), claimed


def recover_transform(model_pts, pdf_pts, tol=22.0, iters=6000, seed=0):
    """model_pts, pdf_pts : listes de (x, y) portees par les calques communs.

    Retourne dict {tf, inliers, n_model, n_pdf, scale, deg, rms} ou None si echec.
    tol = distance d'inlier en points PDF.
    """
    P, Q = list(model_pts), list(pdf_pts)
    if len(P) < 2 or len(Q) < 2:
        return None
    rng = random.Random(seed)
    cell = max(tol, 8.0)
    grid = _build_grid(Q, cell)

    # etendue du nuage PDF -> garde d'etalement (rejette les solutions agglutinees)
    qxs = [q[0] for q in Q]
    qys = [q[1] for q in Q]
    qdiag = math.hypot(max(qxs) - min(qxs), max(qys) - min(qys)) or 1.0
    min_spread = 0.35 * qdiag

    def _spread(claimed):
        pts = [Q[i] for i in claimed]
        if len(pts) < 2:
            return 0.0
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        return math.hypot(max(xs) - min(xs), max(ys) - min(ys))

    best_tf, best_in = None, -1
    for _ in range(iters):
        i, j = rng.randrange(len(P)), rng.randrange(len(P))
        if i == j:
            continue
        a, b = rng.randrange(len(Q)), rng.randrange(len(Q))
        if a == b:
            continue
        tf = _similarity_from_2(P[i], P[j], Q[a], Q[b])
        if tf is None:
            continue
        if tf[0] <= 1e-6 or tf[0] > 1e6:
            continue
        inl, claimed = _score(P, grid, cell, tf, tol)
        # garde d'etalement : les cibles appariees doivent couvrir le plan, pas un coin
        if _spread(claimed) < min_spread:
            continue
        if inl > best_in:
            best_in, best_tf = inl, tf

    if best_tf is None or best_in < 3:
        return None

    # affinage moindres carres : correspondance injective (une cible par source)
    tf = best_tf
    for _ in range(4):
        _, claimed = _score(P, grid, cell, tf, tol)
        pairs = []
        for p in P:
            idx, d = _nearest(grid, cell, apply_tf(tf, p))
            if idx is not None and d <= tol and claimed.get(idx) == d:
                pairs.append((p, Q[idx]))
        if len(pairs) < 2:
            break
        nt = _fit_similarity_lsq(pairs)
        if nt is None or nt[0] <= 1e-6:
            break
        tf = nt

    # metriques finales
    inl, claimed = _score(P, grid, cell, tf, tol)
    rms = math.sqrt(sum(d * d for d in claimed.values()) / inl) if inl else 1e18
    deg = math.degrees(math.atan2(tf[2], tf[1]))
    return {"tf": tf, "inliers": inl, "n_model": len(P), "n_pdf": len(Q),
            "scale": tf[0], "deg": deg, "rms": rms}


def _fit_similarity_lsq(pairs):
    """Moindres carres d'une similarite sur des correspondances (p -> q)."""
    n = len(pairs)
    mpx = sum(p[0] for p, _ in pairs) / n
    mpy = sum(p[1] for p, _ in pairs) / n
    mqx = sum(q[0] for _, q in pairs) / n
    mqy = sum(q[1] for _, q in pairs) / n
    sa = sb = sxx = 0.0
    for p, q in pairs:
        px, py = p[0] - mpx, p[1] - mpy
        qx, qy = q[0] - mqx, q[1] - mqy
        sa += qx * px + qy * py
        sb += qy * px - qx * py
        sxx += px * px + py * py
    if sxx < 1e-9:
        return None
    a, b = sa / sxx, sb / sxx      # s*cos, s*sin
    tx = mqx - (a * mpx - b * mpy)
    ty = mqy - (b * mpx + a * mpy)
    return (math.hypot(a, b), a, b, tx, ty)
