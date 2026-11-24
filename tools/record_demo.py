# ruff: noqa: S603, S607, S310 -- our own interpreter, `git`, and http://127.0.0.1 only
"""Record the demo edition's data: REAL responses from the REAL local backend.

Run from the repository root with the project's virtualenv:  python tools/record_demo.py
It starts the job worker, the job API and the dashboard on throwaway ports with a temporary state
directory and credentials, calls every page the web app calls with that page's default settings,
runs each lab once with its default configuration, and writes frontend/demo-data/recording.json.
Nothing is invented: a failed call is listed under "failures" and is simply absent from the demo.
Rerun it, review the diff, and commit when the backend's output has changed.
"""

import datetime
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ROOT = Path(tempfile.mkdtemp(prefix="econosim-demo-"))
PY = sys.executable
env = {**os.environ, "OMP_NUM_THREADS": "1"}
LOGS = ROOT / "logs"
LOGS.mkdir(exist_ok=True)


def run(*a):
    return subprocess.run([PY, *a], cwd=REPO, env=env, check=True, capture_output=True, text=True)


if not (ROOT / "auth.json").exists():
    run(
        "-m",
        "prometheus.service",
        "init-auth",
        "--credentials",
        str(ROOT / "auth.json"),
        "--token-file",
        str(ROOT / "token"),
        "--owner",
        "alice",
    )
token = (ROOT / "token").read_text().strip()
procs = []


def spawn(name, *a):
    p = subprocess.Popen(
        [PY, *a],
        cwd=REPO,
        env=env,
        stdout=open(LOGS / f"{name}.log", "w"),
        stderr=subprocess.STDOUT,
    )
    procs.append(p)
    print("started", name, p.pid, flush=True)


def call(base, path, method="GET", body=None, headers=None):
    h = {"Authorization": f"Bearer {token}", "Accept": "application/json", **(headers or {})}
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        h["Content-Type"] = "application/json"
    req = urllib.request.Request(base + path, data=data, headers=h, method=method)
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


JOBS, DASH = "http://127.0.0.1:18765", "http://127.0.0.1:18766"
DASH_PATHS = [
    "/market-paths?sigma=0.2&n_paths=2000",
    "/economy?n_steps=6&seed=0",
    "/pricing?strike=100&volatility=0.2",
    "/audit-trail",
    "/portfolio/alice",
    "/experiments",
    "/hedge-actions",
    "/validation-issues",
    "/portfolio-risk",
    "/model-usage?model_id=recessionnet&application=research",
]
LABS = {
    "qmacro": dict(
        seed=0,
        max_epochs=200,
        patience=20,
        window=6,
        horizon=6,
        ar_order=3,
        validation_split_date="1988-01-01",
        test_split_date="2000-01-01",
        bootstrap_resamples=500,
        feature_series_ids=["FF3_Mkt-RF", "FF3_SMB", "FF3_HML", "FF3_RF"],
        target_series_id="FF3_Mkt-RF",
    ),
    "recessionnet_kaggle": dict(
        seed=0,
        max_epochs=200,
        patience=20,
        window=6,
        horizon=6,
        validation_split_date="2001-01-01",
        test_split_date="2008-01-01",
        bootstrap_resamples=500,
    ),
    "inflationcast": dict(
        seed=0,
        max_epochs=150,
        patience=15,
        window=6,
        validation_split_date="2019-01-01",
        test_split_date="2022-01-01",
        bootstrap_resamples=300,
        calibration_coverage=0.9,
    ),
    "neural_sde": dict(seed=0, max_epochs=300, patience=20),
    "pde_solver": dict(
        seed=0,
        risk_free_rate=0.05,
        volatility=0.2,
        maturity=1.0,
        strike=100,
        n_space_grid_1d=400,
        pinn_epochs=100,
        bsde_epochs=20,
    ),
    "marl": dict(
        seed=0,
        n_epochs=30,
        episodes_per_epoch=8,
        n_steps=6,
        firm_opening_capital_minor_units=100000,
    ),
    "rl_hedge": dict(
        seed=0,
        n_epochs=400,
        s0=100.0,
        mu=0.05,
        sigma=0.2,
        maturity=1.0,
        n_steps=20,
        n_paths=2000,
        strike=100.0,
        option_type="call",
        risk_free_rate=0.03,
        cost_rate=0.001,
        initial_premium=5.0,
        cvar_alpha=0.95,
        learning_rate=0.01,
        band_width=0.05,
        reward_objective="cvar",
    ),
}
out = {"dashboard": {}, "jobs": {}, "failures": {}}
try:
    spawn("worker", "-m", "prometheus.jobs", "--root", str(ROOT), "work")
    spawn(
        "api",
        "-m",
        "prometheus.service",
        "serve",
        "--root",
        str(ROOT),
        "--credentials",
        str(ROOT / "auth.json"),
        "--port",
        "18765",
    )
    spawn(
        "dash",
        "-m",
        "prometheus.dashboard",
        "serve",
        "--credentials",
        str(ROOT / "auth.json"),
        "--port",
        "18766",
        "--demo",
    )
    for _ in range(60):
        try:
            urllib.request.urlopen(JOBS + "/health/live", timeout=2)
            break
        except Exception:
            time.sleep(1)
    for p in DASH_PATHS:
        sep = "&" if "?" in p else "?"
        try:
            out["dashboard"][p] = call(DASH, f"/dashboard{p}{sep}format=json")
            print("dash ok", p, flush=True)
        except Exception as e:
            out["failures"][p] = repr(e)
            print("dash FAIL", p, e, flush=True)
    for kind, cfg in LABS.items():
        try:
            key = (
                "rec-"
                + hashlib.sha256((kind + json.dumps(cfg, sort_keys=True)).encode()).hexdigest()[:40]
            )
            job = call(
                JOBS, "/v1/jobs", "POST", {"kind": kind, "config": cfg}, {"Idempotency-Key": key}
            )
            t0 = time.time()
            while job["status"] not in ("succeeded", "failed", "cancelled", "timed_out"):
                time.sleep(2)
                job = call(JOBS, f"/v1/jobs/{job['job_id']}")
                if time.time() - t0 > 1500:
                    raise TimeoutError("job too slow")
            if job["status"] != "succeeded":
                raise RuntimeError(f"{job['status']} {job.get('error_code')}")
            out["jobs"][kind] = {
                "job": job,
                "config": cfg,
                "artifact": call(JOBS, f"/v1/jobs/{job['job_id']}/artifact"),
            }
            print("job ok", kind, round(time.time() - t0), "s", flush=True)
        except Exception as e:
            out["failures"][kind] = repr(e)
            print("job FAIL", kind, e, flush=True)
finally:
    for p in procs:
        p.terminate()
    for p in procs:
        try:
            p.wait(timeout=15)
        except Exception:
            p.kill()
sha = subprocess.run(
    ["git", "rev-parse", "--short", "HEAD"], cwd=REPO, capture_output=True, text=True
).stdout.strip()
out["meta"] = {
    "recorded_at": datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%d"),
    "git": sha,
    "note": "Real responses recorded from the real local backend, default settings.",
}
dest = REPO / "frontend/demo-data"
dest.mkdir(exist_ok=True)
shutil.rmtree(ROOT, ignore_errors=True)
(dest / "recording.json").write_text(json.dumps(out, separators=(",", ":")))
print("wrote", (dest / "recording.json").stat().st_size, "bytes; failures:", list(out["failures"]))
