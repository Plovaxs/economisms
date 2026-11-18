# ECONOSIM/PROMETHEUS-X -- a research/demo container image. SIMULATED DATA,
# RESEARCH ONLY; no live trading, no real brokerage connection (see
# evidence/gate_report_r0.json, scope_prohibited). It is built to be RUN with
# the controls docker-compose.yml applies (an unprivileged user, a read-only
# root filesystem, no capabilities, resource limits, health checks) -- that
# hardens how the software is deployed; it is not a claim that this project
# is cleared for production use, which its own NO-GO gate decision says it is
# not. A complementary way to run the already-built demo with nothing
# installed locally but Docker -- frontend/README.md's npm/uv-based local dev
# workflow is unaffected and remains the way to actively develop the frontend.
#
# Two stages, each reusing commands already verified elsewhere in this
# repository rather than inventing a second install path:
#   1. frontend-build -- the same `npm ci && npm run build`
#      .github/workflows/frontend-ci.yml already runs (minus package install
#      scripts: nothing in the build needs them, and a build that runs
#      arbitrary code from every transitive dependency at install time is the
#      classic npm supply-chain foothold).
#   2. runtime -- `uv sync --locked --no-install-project --no-build` (plus the
#      three runtime extras), the same flags ci.yml's own install step uses: ONLY hash-verified,
#      pre-built wheels from uv.lock, and the project itself is NOT installed
#      -- src/ is simply put on PYTHONPATH. Several orchestration job kinds
#      (inflationcast/recessionnet_kaggle/neural_sde/recessionnet_yield_curve)
#      locate their committed data_cache/ snapshots via a path relative to
#      __file__, which needs the package to live at a real, checkout-shaped
#      path (the class of bug PR-185 found for CI's own test run); a wheel
#      install would silently break that, a PYTHONPATH import cannot. Not
#      installing the project also means no build backend runs here and
#      setuptools/wheel are not in the image at all: the first image scan
#      (security.yml) found setuptools 78.1.0, wheel 0.45.1 and a vendored
#      jaraco.context with fixable HIGH vulnerabilities, all of them there only
#      because the build dependency group had been installed into a RUNTIME
#      image that never builds anything. src/ and data_cache/ (156KB) are
#      copied in at the same relative layout a checkout has; test fixtures,
#      caches, node_modules and the separate 97MB evidence/ reference-bundle
#      directory (confirmed unreferenced by any runtime code path) are left
#      out on purpose.
#
# Both base images are pinned by DIGEST, not just tag: a tag can be moved to
# different contents after this file was reviewed; a digest cannot. Dependabot
# (docker ecosystem) proposes digest bumps, so they still get refreshed.
#
# Runs as an unprivileged user (uid 10001). The first attempt at this (PR-187)
# was abandoned because a fresh named Docker volume is root-owned and
# init-auth's own write to it failed with a real Permission denied on
# GitHub's runner. The fix is not a chown at runtime: Docker populates an
# EMPTY named volume from the image's content at the mount point, ownership
# included -- so creating /data in the image, owned by the unprivileged user,
# is all it takes. (A volume created by an older, root-running version of this
# image keeps its root ownership: `docker compose down -v` once.)

FROM node:24-slim@sha256:dc26ae92c9fb15cf6b1d63e20f0944b2efe0f115b20e00be48fb23fceb061c54 AS frontend-build
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --ignore-scripts
COPY frontend/ ./
RUN npm run build

FROM python:3.11-slim@sha256:07d4824036af339fa1b6ef769cc99d9c10a141769538b52b3b597c84f7a7b535 AS runtime
LABEL org.opencontainers.image.description="ECONOSIM/PROMETHEUS-X research demo -- SIMULATED DATA, RESEARCH ONLY, not financial advice, no live trading"
# OS packages first, as root: the digest pins a reproducible starting point, and
# this layer applies the security fixes Debian has published since that image
# was built (the first image scan found a fixable HIGH in zlib1g in the then-
# latest official image). The scheduled scan tells us when the pin goes stale.
RUN apt-get update \
    && apt-get -y --no-install-recommends upgrade \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements/bootstrap.txt requirements/bootstrap.txt
RUN python -m pip install --no-cache-dir --require-hashes --only-binary=':all:' -r requirements/bootstrap.txt
COPY pyproject.toml uv.lock ./
# Bytecode is compiled NOW, as root: at run time the code is read-only and the
# user cannot write __pycache__, so without this every process (and every job
# child process) would recompile torch from source on each start.
ENV UV_COMPILE_BYTECODE=1
# Only the extras the runtime imports (service: uvicorn/jsonschema, recovery:
# cryptography, quantum: pennylane) -- not `dev` (pytest, mypy, ruff, hypothesis,
# scikit-learn), which has no business in a deployed image.
RUN uv sync --locked --extra service --extra recovery --extra quantum --no-install-project --no-build
COPY src/ src/
COPY data_cache/ data_cache/
RUN python -m compileall -q src
COPY --from=frontend-build /app/frontend/dist /app/frontend/dist
RUN groupadd --system --gid 10001 econosim \
    && useradd --system --uid 10001 --gid 10001 --no-create-home --home-dir /tmp --shell /usr/sbin/nologin econosim \
    && mkdir /data \
    && chown econosim:econosim /data \
    && chmod 0700 /data
ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONPATH=/app/src \
    HOME=/tmp \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
USER 10001:10001
EXPOSE 8080
CMD ["python", "-m", "prometheus.webgateway", "serve", "--dist", "/app/frontend/dist", "--host", "0.0.0.0", "--allow-non-loopback-without-tls"]
