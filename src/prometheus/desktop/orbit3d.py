"""A small 3-D engine for the model web: the same one the web app uses, in Python and without Qt.

Vectors, an orbit camera with inertia, a perspective projection, depth sorting, hit testing and a
deterministic spherical layout of the registry's graph. It is pure (no widget, no painter), so each
piece is tested without a display; the Atlas page only draws what it returns.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Any

Vec3 = tuple[float, float, float]

GOLDEN_ANGLE = math.pi * (3 - math.sqrt(5))
PITCH_LIMIT = 1.45
DISTANCE_RANGE = (1.6, 7.0)
AUTO_ROTATE_SPEED = 0.18  # radians per second
DAMPING = 3.2  # per second
SHELLS = {"model": 1.0, "baseline": 0.52, "pipeline": 0.13}


def add(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def scale(a: Vec3, k: float) -> Vec3:
    return (a[0] * k, a[1] * k, a[2] * k)


def dot(a: Vec3, b: Vec3) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def cross(a: Vec3, b: Vec3) -> Vec3:
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def length(a: Vec3) -> float:
    return math.hypot(a[0], a[1], a[2])


def normalise(a: Vec3) -> Vec3:
    n = length(a)
    return (0.0, 0.0, 1.0) if n == 0 else (a[0] / n, a[1] / n, a[2] / n)


def fibonacci_sphere(count: int) -> list[Vec3]:
    if count <= 0:
        return []
    if count == 1:
        return [(0.0, 1.0, 0.0)]
    points: list[Vec3] = []
    for i in range(count):
        y = 1 - 2 * i / (count - 1)
        r = math.sqrt(max(0.0, 1 - y * y))
        theta = GOLDEN_ANGLE * i
        points.append((math.cos(theta) * r, y, math.sin(theta) * r))
    return points


def tangent_basis(n: Vec3) -> tuple[Vec3, Vec3]:
    helper: Vec3 = (0.0, 1.0, 0.0) if abs(n[1]) < 0.9 else (1.0, 0.0, 0.0)
    u = normalise(cross(n, helper))
    v = normalise(cross(n, u))
    return u, v


def wrap_angle(a: float) -> float:
    r = a % (2 * math.pi)
    return r - 2 * math.pi if r > math.pi else r


# ----- the camera -----------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Orbit:
    yaw: float = 0.6
    pitch: float = 0.35
    distance: float = 3.1
    yaw_velocity: float = 0.0
    pitch_velocity: float = 0.0


def clamp_orbit(o: Orbit) -> Orbit:
    return replace(
        o,
        yaw=wrap_angle(o.yaw),
        pitch=max(-PITCH_LIMIT, min(PITCH_LIMIT, o.pitch)),
        distance=max(DISTANCE_RANGE[0], min(DISTANCE_RANGE[1], o.distance)),
    )


def rotate(p: Vec3, yaw: float, pitch: float) -> Vec3:
    cy, sy = math.cos(yaw), math.sin(yaw)
    x1 = p[0] * cy + p[2] * sy
    z1 = -p[0] * sy + p[2] * cy
    cp, sp = math.cos(pitch), math.sin(pitch)
    return (x1, p[1] * cp - z1 * sp, p[1] * sp + z1 * cp)


@dataclass(frozen=True, slots=True)
class Projected:
    x: float
    y: float
    scale: float  # pixels per world unit at this depth
    depth: float  # larger is farther
    visible: bool


def project(p: Vec3, camera: Orbit, width: float, height: float) -> Projected:
    x, y, z = rotate(p, camera.yaw, camera.pitch)
    depth = camera.distance - z
    if depth <= 0.15:
        return Projected(width / 2, height / 2, 0.0, depth, False)
    k = min(width, height) * 0.4 * camera.distance / depth
    return Projected(width / 2 + x * k, height / 2 - y * k, k, depth, True)


def depth_order(projected: Sequence[Projected]) -> list[int]:
    return sorted(range(len(projected)), key=lambda i: -projected[i].depth)


def pick(projected: Sequence[Projected], radii: Sequence[float], px: float, py: float) -> int:
    """The nearest visible item whose disc contains the pointer, or -1."""
    best, best_depth = -1, math.inf
    for i, p in enumerate(projected):
        if p.visible and math.hypot(px - p.x, py - p.y) <= radii[i] and p.depth < best_depth:
            best, best_depth = i, p.depth
    return best


def step_orbit(o: Orbit, dt: float, *, dragging: bool, auto_rotate: bool) -> Orbit:
    """Advance by `dt` seconds: velocity decays; auto-rotation takes over when still."""
    if dt <= 0:
        return o
    decay = math.exp(-DAMPING * dt)
    yaw_v = 0.0 if dragging else o.yaw_velocity * decay
    pitch_v = 0.0 if dragging else o.pitch_velocity * decay
    if abs(yaw_v) < 1e-3:
        yaw_v = 0.0
    if abs(pitch_v) < 1e-3:
        pitch_v = 0.0
    drift = (
        AUTO_ROTATE_SPEED if auto_rotate and not dragging and yaw_v == 0 and pitch_v == 0 else 0.0
    )
    moved = clamp_orbit(replace(o, yaw=o.yaw + (yaw_v + drift) * dt, pitch=o.pitch + pitch_v * dt))
    return replace(moved, yaw_velocity=yaw_v, pitch_velocity=pitch_v)


def drag_orbit(o: Orbit, dx: float, dy: float, dt: float) -> Orbit:
    sensitivity = 0.0065
    moved = clamp_orbit(replace(o, yaw=o.yaw + dx * sensitivity, pitch=o.pitch + dy * sensitivity))
    cap = 6.0
    yaw_v = dx * sensitivity / dt if dt > 0 else 0.0
    pitch_v = dy * sensitivity / dt if dt > 0 else 0.0
    return replace(
        moved, yaw_velocity=max(-cap, min(cap, yaw_v)), pitch_velocity=max(-cap, min(cap, pitch_v))
    )


def zoom_orbit(o: Orbit, factor: float) -> Orbit:
    return replace(o, distance=clamp_orbit(replace(o, distance=o.distance * factor)).distance)


# ----- the layout -----------------------------------------------------------------------------


def relax_on_sphere(
    points: Sequence[Vec3], radius: float, minimum: float, rounds: int
) -> list[Vec3]:
    """Push points on a sphere apart until none is closer than `minimum` (or `rounds` pass)."""
    current = [scale(normalise(p), radius) for p in points]
    for _ in range(rounds):
        push: list[Vec3] = [(0.0, 0.0, 0.0)] * len(current)
        moved = False
        for i in range(len(current)):
            for j in range(i + 1, len(current)):
                d = add(current[i], scale(current[j], -1))
                dist = length(d)
                if dist >= minimum:
                    continue
                moved = True
                direction = (
                    normalise((math.cos(i * 2.4 + j), math.sin(i * 1.7 + j), math.cos(j * 3.1)))
                    if dist < 1e-9
                    else scale(d, 1 / dist)
                )
                amount = (minimum - dist) * 0.5
                push[i] = add(push[i], scale(direction, amount))
                push[j] = add(push[j], scale(direction, -amount))
        if not moved:
            break
        current = [scale(normalise(add(p, push[i])), radius) for i, p in enumerate(current)]
    return current


def layout_web3(
    nodes: Sequence[dict[str, Any]], edges: Sequence[dict[str, Any]]
) -> dict[str, Vec3]:
    """Families on the outer shell as tight clusters, baselines on an inner shell near the models
    they were judged against, pipelines at the core. Deterministic."""
    drawn = [
        n
        for n in nodes
        if n["kind"] in ("model", "baseline", "pipeline") and n["status"] != "not_built"
    ]
    models = [n for n in drawn if n["kind"] == "model"]
    families = sorted({n["family"] for n in models})
    anchors = fibonacci_sphere(len(families))
    out: dict[str, Vec3] = {}
    for fi, family in enumerate(families):
        anchor = anchors[fi]
        u, v = tangent_basis(anchor)
        for k, node in enumerate(
            sorted((n for n in models if n["family"] == family), key=lambda n: n["id"])
        ):
            radius = 0.0 if k == 0 else 0.1 + 0.09 * math.sqrt(k)
            angle = GOLDEN_ANGLE * k
            offset = add(scale(u, math.cos(angle) * radius), scale(v, math.sin(angle) * radius))
            out[node["id"]] = scale(normalise(add(anchor, offset)), SHELLS["model"])
    baselines = sorted((n for n in drawn if n["kind"] == "baseline"), key=lambda n: n["id"])
    fallback = fibonacci_sphere(max(len(baselines), 2))
    wanted: list[Vec3] = []
    for i, node in enumerate(baselines):
        targets = [
            out[e["target"]]
            for e in edges
            if e["kind"] == "baseline_for" and e["source"] == node["id"] and e["target"] in out
        ]
        if targets:
            total: Vec3 = (0.0, 0.0, 0.0)
            for t in targets:
                total = add(total, normalise(t))
            direction = normalise(total)
        else:
            direction = fallback[i]
        u, v = tangent_basis(direction)
        jitter = add(
            scale(u, 0.09 * math.cos(GOLDEN_ANGLE * i)), scale(v, 0.09 * math.sin(GOLDEN_ANGLE * i))
        )
        wanted.append(scale(normalise(add(direction, jitter)), SHELLS["baseline"]))
    for node, position in zip(
        baselines, relax_on_sphere(wanted, SHELLS["baseline"], 0.2, 60), strict=True
    ):
        out[node["id"]] = position
    pipelines = sorted((n for n in drawn if n["kind"] == "pipeline"), key=lambda n: n["id"])
    for i, node in enumerate(pipelines):
        angle = 2 * math.pi * i / max(len(pipelines), 1)
        out[node["id"]] = (
            math.cos(angle) * SHELLS["pipeline"],
            0.0,
            math.sin(angle) * SHELLS["pipeline"],
        )
    return {n["id"]: out[n["id"]] for n in drawn}


def along(a: Vec3, b: Vec3, t: float) -> Vec3:
    f = t - math.floor(t)
    return (a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f, a[2] + (b[2] - a[2]) * f)


def depth_alpha(depth: float, near: float, far: float, floor: float = 0.25) -> float:
    if far <= near:
        return 1.0
    t = max(0.0, min(1.0, (depth - near) / (far - near)))
    return 1 - (1 - floor) * t
