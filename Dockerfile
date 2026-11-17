# ECONOSIM/PROMETHEUS-X -- a research/demo container, not a production
# deployment. SIMULATED DATA, RESEARCH ONLY; no live trading, no real
# brokerage connection (see evidence/gate_report_r0.json, scope_prohibited).
# A complementary way to run the already-built demo with nothing installed
# locally but Docker -- frontend/README.md's npm/uv-based local dev workflow
# is unaffected and remains the way to actively develop the frontend.
#
# Two stages, each reusing commands already verified elsewhere in this
# repository rather than inventing a second install path:
#   1. frontend-build -- the same `npm ci && npm run build`
#      .github/workflows/frontend-ci.yml already runs.
#   2. runtime -- `uv sync --locked --all-extras --group build` (an
#      EDITABLE install, deliberately NOT the wheel-build-and-verify
#      sequence ci.yml's own reproducibility check uses): several
#      orchestration job kinds (inflationcast/recessionnet_kaggle/
#      neural_sde/recessionnet_yield_curve) locate their committed
#      data_cache/ snapshots via a path relative to __file__, which
#      only resolves correctly when the package lives at a real,
#      checkout-shaped path -- the exact class of bug PR-185 found
#      and fixed for CI's own test run. A wheel install here would
#      silently reintroduce it for a real runtime deployment instead
#      of just a test run. src/ and data_cache/ (156KB) are copied in
#      at the same relative layout an editable checkout has; test
#      fixtures, caches, node_modules and the separate 97MB evidence/
#      reference-bundle directory (confirmed unreferenced by any
#      runtime code path) are left out on purpose.

FROM node:20-slim AS frontend-build
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.11-slim AS runtime
LABEL org.opencontainers.image.description="ECONOSIM/PROMETHEUS-X research demo -- SIMULATED DATA, RESEARCH ONLY, not financial advice, no live trading"
WORKDIR /app
COPY requirements/bootstrap.txt requirements/bootstrap.txt
RUN python -m pip install --no-cache-dir --require-hashes --only-binary=':all:' -r requirements/bootstrap.txt
COPY pyproject.toml uv.lock ./
COPY src/ src/
COPY data_cache/ data_cache/
RUN uv sync --locked --all-extras --group build
COPY --from=frontend-build /app/frontend/dist /app/frontend/dist
ENV PATH="/app/.venv/bin:${PATH}"
RUN useradd --create-home --uid 1000 econosim && chown -R econosim:econosim /app
USER econosim
EXPOSE 8080
CMD ["python", "-m", "prometheus.webgateway", "serve", "--dist", "/app/frontend/dist", "--host", "0.0.0.0", "--allow-non-loopback-without-tls"]
