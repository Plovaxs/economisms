"""The desktop settings file and the Qt-free 3-D engine (no display needed)."""

from __future__ import annotations

import json
import math
import os
import stat
from pathlib import Path

import pytest

from prometheus.desktop import orbit3d as o
from prometheus.desktop import settings as s
from prometheus.modelzoo import graph as zoo_graph

# ----- settings ---------------------------------------------------------------------------------


def test_defaults_are_the_designed_values() -> None:
    d = s.DEFAULTS
    assert (d.theme, d.text_scale, d.high_contrast, d.reduce_motion) == (
        "system",
        1.0,
        False,
        False,
    )
    assert (d.atlas_view, d.auto_rotate, d.labels_3d) == ("3d", True, "selected")


@pytest.mark.parametrize("raw", [None, 5, "x", [], True])
def test_anything_that_is_not_an_object_gives_the_defaults(raw: object) -> None:
    assert s.sanitize(raw) == s.DEFAULTS


def test_valid_values_are_kept_and_invalid_ones_dropped_field_by_field() -> None:
    got = s.sanitize(
        {
            "theme": "dark",
            "text_scale": 1.3,
            "high_contrast": True,
            "reduce_motion": "yes",
            "atlas_view": "4d",
            "auto_rotate": False,
            "labels_3d": "all",
            "unknown": 1,
        }
    )
    assert got.theme == "dark" and got.text_scale == 1.3 and got.high_contrast is True
    assert got.reduce_motion is False and got.atlas_view == "3d"
    assert got.auto_rotate is False and got.labels_3d == "all"


def test_a_text_scale_that_is_not_offered_or_is_a_bool_is_refused() -> None:
    assert s.sanitize({"text_scale": 2.0}).text_scale == 1.0
    assert s.sanitize({"text_scale": True}).text_scale == 1.0
    assert s.sanitize({"text_scale": "1.3"}).text_scale == 1.0
    assert s.sanitize({"text_scale": 1}).text_scale == 1.0


def test_with_changes_sanitises_too() -> None:
    assert s.DEFAULTS.with_changes(theme="light", text_scale=1.5).theme == "light"
    assert s.DEFAULTS.with_changes(theme="purple").theme == "system"


def test_saving_is_private_atomic_and_round_trips(tmp_path: Path) -> None:
    state = tmp_path / "state"
    mine = s.DEFAULTS.with_changes(theme="dark", text_scale=1.15, high_contrast=True)
    assert s.save(state, mine) is True
    assert s.load(state) == mine
    mode = stat.S_IMODE(os.stat(s.settings_path(state)).st_mode)
    assert mode == 0o600
    assert not list(state.glob(".settings-*")), "no temporary file is left behind"
    assert json.loads(s.settings_path(state).read_text())["theme"] == "dark"


def test_a_missing_or_corrupt_file_means_the_defaults(tmp_path: Path) -> None:
    assert s.load(tmp_path / "nowhere") == s.DEFAULTS
    (tmp_path / s.FILE_NAME).write_text("{not json")
    assert s.load(tmp_path) == s.DEFAULTS
    (tmp_path / s.FILE_NAME).write_text(json.dumps({"theme": "dark", "text_scale": 99}))
    assert s.load(tmp_path).theme == "dark" and s.load(tmp_path).text_scale == 1.0


def test_an_unwritable_directory_is_reported_not_raised(tmp_path: Path) -> None:
    blocker = tmp_path / "file"
    blocker.write_text("x")
    assert s.save(blocker / "inside", s.DEFAULTS) is False


# ----- the engine -------------------------------------------------------------------------------


def test_vectors_and_the_fibonacci_sphere() -> None:
    assert o.length(o.normalise((3, 4, 0))) == pytest.approx(1)
    assert o.normalise((0, 0, 0)) == (0.0, 0.0, 1.0)
    assert o.cross((1, 0, 0), (0, 1, 0)) == (0, 0, 1)
    pts = o.fibonacci_sphere(24)
    assert all(o.length(p) == pytest.approx(1) for p in pts)
    assert min(math.dist(a, b) for i, a in enumerate(pts) for b in pts[i + 1 :]) > 0.3
    assert o.fibonacci_sphere(0) == [] and len(o.fibonacci_sphere(1)) == 1
    for n in [o.normalise((1, 2, 3)), (0.0, 1.0, 0.0), (1.0, 0.0, 0.0)]:
        u, v = o.tangent_basis(n)
        assert abs(o.dot(u, n)) < 1e-9 and abs(o.dot(v, n)) < 1e-9 and abs(o.dot(u, v)) < 1e-9


def test_rotation_and_projection() -> None:
    p = (0.3, -0.5, 0.8)
    assert o.length(o.rotate(p, 1.1, -0.4)) == pytest.approx(o.length(p))
    cam = o.Orbit(yaw=0, pitch=0, distance=3)
    centre = o.project((0, 0, 0), cam, 800, 600)
    assert (centre.x, centre.y) == (pytest.approx(400), pytest.approx(300))
    assert (
        o.project((0.5, 0, 0), cam, 800, 600).x > 400
        and o.project((0, 0.5, 0), cam, 800, 600).y < 300
    )
    near, far = o.project((0, 0, 0.8), cam, 800, 600), o.project((0, 0, -0.8), cam, 800, 600)
    assert near.scale > far.scale and near.depth < far.depth
    behind = o.project((0, 0, 5), cam, 800, 600)
    assert behind.visible is False and math.isfinite(behind.x)


def test_depth_order_and_picking() -> None:
    items = [
        o.Projected(100, 100, 1, 5, True),
        o.Projected(102, 100, 1, 2, True),
        o.Projected(300, 300, 1, 9, True),
        o.Projected(100, 100, 1, 1, False),
    ]
    assert o.depth_order(items) == [2, 0, 1, 3]
    assert o.pick(items, [10] * 4, 101, 100) == 1
    assert o.pick(items, [10] * 4, 600, 600) == -1


def test_the_orbit_stays_in_range_drags_coasts_and_rests() -> None:
    c = o.clamp_orbit(o.Orbit(yaw=7, pitch=9, distance=100))
    assert (
        c.pitch == o.PITCH_LIMIT
        and c.distance == o.DISTANCE_RANGE[1]
        and -math.pi <= c.yaw <= math.pi
    )
    dragged = o.drag_orbit(o.Orbit(), 100, -40, 0.1)
    assert (
        dragged.yaw > o.Orbit().yaw and dragged.pitch < o.Orbit().pitch and dragged.yaw_velocity > 0
    )
    now = dragged
    for _ in range(200):
        now = o.step_orbit(now, 1 / 60, dragging=False, auto_rotate=False)
    assert now.yaw_velocity == 0 and now.yaw > dragged.yaw


def test_dragging_holds_still_and_auto_rotation_needs_stillness_and_permission() -> None:
    held = o.step_orbit(o.Orbit(yaw_velocity=2), 0.5, dragging=True, auto_rotate=True)
    assert held.yaw == pytest.approx(o.Orbit().yaw)
    spun = o.step_orbit(o.Orbit(), 1, dragging=False, auto_rotate=True)
    assert spun.yaw - o.Orbit().yaw == pytest.approx(o.AUTO_ROTATE_SPEED)
    assert o.step_orbit(o.Orbit(), 1, dragging=False, auto_rotate=False).yaw == pytest.approx(
        o.Orbit().yaw
    )
    assert o.step_orbit(o.Orbit(), 0, dragging=False, auto_rotate=True) == o.Orbit()


def test_zoom_is_bounded() -> None:
    assert o.zoom_orbit(o.Orbit(), 0.5).distance < o.Orbit().distance
    assert o.zoom_orbit(o.Orbit(), 1e-6).distance == o.DISTANCE_RANGE[0]
    assert o.zoom_orbit(o.Orbit(), 1e6).distance == o.DISTANCE_RANGE[1]


def test_the_layout_of_the_registry_graph() -> None:
    graph = zoo_graph.build_graph()
    layout = o.layout_web3(graph.nodes, graph.edges)
    kinds = {n["id"]: n["kind"] for n in graph.nodes}
    assert len(layout) > 50 and "ferminet" not in layout
    assert o.layout_web3(graph.nodes, graph.edges) == layout  # deterministic
    for node_id, position in layout.items():
        r = o.length(position)
        if kinds[node_id] == "model":
            assert r == pytest.approx(o.SHELLS["model"])
        elif kinds[node_id] == "baseline":
            assert r == pytest.approx(o.SHELLS["baseline"])
        else:
            assert r < o.SHELLS["baseline"]
    points = list(layout.values())
    assert min(math.dist(a, b) for i, a in enumerate(points) for b in points[i + 1 :]) > 0.02
    base = layout["mlp_operator"]
    targets = [
        layout[e["target"]]
        for e in graph.edges
        if e["kind"] == "baseline_for" and e["source"] == "mlp_operator"
    ]
    assert max(o.dot(o.normalise(base), o.normalise(t)) for t in targets) > 0.8


def test_helpers() -> None:
    assert o.along((0, 0, 0), (10, 0, 0), 0.25) == (2.5, 0, 0)
    assert o.along((0, 0, 0), (10, 0, 0), 1.25)[0] == pytest.approx(2.5)
    assert o.depth_alpha(1, 1, 5) == 1 and o.depth_alpha(5, 1, 5, 0.3) == pytest.approx(0.3)
    assert o.depth_alpha(3, 3, 3) == 1


def test_saving_into_a_directory_that_does_not_exist_makes_it_private(tmp_path: Path) -> None:
    state = tmp_path / "made" / "by" / "settings"
    assert s.save(state, s.DEFAULTS) is True
    assert stat.S_IMODE(os.stat(state).st_mode) == 0o700  # the session refuses anything looser


def test_the_python_engine_agrees_with_the_browser_engine() -> None:
    """`frontend/src/atlas/layout.parity.json` was written by the TypeScript engine; the same file
    is checked in `engine.test.ts`, so neither implementation can drift without a test failing."""
    path = Path(__file__).resolve().parents[2] / "frontend" / "src" / "atlas" / "layout.parity.json"
    recorded = json.loads(path.read_text())
    graph = zoo_graph.build_graph()
    layout = o.layout_web3(graph.nodes, graph.edges)
    assert set(layout) == set(recorded["layout"])
    for node_id, position in layout.items():
        for got, want in zip(position, recorded["layout"][node_id], strict=True):
            assert got == pytest.approx(want, abs=1e-6), node_id
    assert len(recorded["projections"]) > 20
    for row in recorded["projections"]:
        cam = row["camera"]
        camera = o.Orbit(yaw=cam["yaw"], pitch=cam["pitch"], distance=cam["distance"])
        point = tuple(row["point"])
        turned = o.rotate(point, camera.yaw, camera.pitch)
        for got, want in zip(turned, row["rotated"], strict=True):
            assert got == pytest.approx(want, abs=1e-6)
        q = o.project(point, camera, row["view"]["width"], row["view"]["height"])
        for key in ("x", "y", "scale", "depth"):
            assert getattr(q, key) == pytest.approx(row[key], abs=1e-6), key
        assert q.visible is row["visible"]
