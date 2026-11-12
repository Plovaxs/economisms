"""Allowlisted typed recipe dispatch and pre-execution resource admission.

Service limits bound shapes and estimated operation counts; they are not
wall-time predictions or hard operating-system memory guarantees. Trusted
local replay can opt out of admission limits while retaining typed decoding.
"""

from __future__ import annotations

import importlib
import json
import math
from collections.abc import Mapping
from dataclasses import asdict, dataclass, fields
from types import MappingProxyType
from typing import Any, Protocol

from prometheus.evidence.contracts import CONVENTIONS
from prometheus.evidence.jsonio import strict_json_loads
from prometheus.experiments.manifest import RunManifest, compute_result_hash, json_default


@dataclass(frozen=True, slots=True)
class RunnerSpec:
    module: str
    config_name: str
    function_name: str
    config_module: str | None = None


RUNNERS: Mapping[str, RunnerSpec] = MappingProxyType(
    {
        "simulation": RunnerSpec(
            "multi_step_run", "MultiStepRunConfig", "run_multi_step_simulation"
        ),
        "benchmark": RunnerSpec("benchmark_run", "BenchmarkRunConfig", "run_benchmark"),
        "study": RunnerSpec("study_run", "StudyRunConfig", "run_study"),
        "economy": RunnerSpec("economy_run", "EconomyRunConfig", "run_economy"),
        "monetary": RunnerSpec("monetary_run", "MonetaryRunConfig", "run_monetary_simulation"),
        "monetary_study": RunnerSpec("monetary_study", "MonetaryStudyConfig", "run_monetary_study"),
        "rate_study": RunnerSpec("rate_study", "RateStudyConfig", "run_rate_study"),
        "mixture_study": RunnerSpec("mixture_study", "MixtureStudyConfig", "run_mixture_study"),
        "monetary_operations": RunnerSpec(
            "monetary_operations_run",
            "MonetaryOperationsConfig",
            "run_monetary_operations",
            "prometheus.econosim.monetary_operations",
        ),
        "qmacro": RunnerSpec("qmacro_run", "QMacroRunConfig", "run_qmacro_job"),
        "recessionnet_kaggle": RunnerSpec(
            "recessionnet_kaggle_run", "RecessionNetKaggleRunConfig", "run_recessionnet_kaggle_job"
        ),
        "inflationcast": RunnerSpec(
            "inflationcast_run", "InflationcastRunConfig", "run_inflationcast_job"
        ),
        "neural_sde": RunnerSpec("neural_sde_run", "NeuralSdeRunConfig", "run_neural_sde_job"),
        "pde_solver": RunnerSpec("pde_solver_run", "PdeSolverRunConfig", "run_pde_solver"),
        "marl": RunnerSpec("marl_run", "MarlRunConfig", "run_marl"),
        "rl_hedge": RunnerSpec("rl_hedge_run", "RlHedgeRunConfig", "run_rl_hedge"),
    }
)

if set(RUNNERS) != set(CONVENTIONS):
    raise RuntimeError("recipe registry differs from the supported artifact contracts")


class RecipeError(ValueError):
    pass


class ResourceLimitError(RecipeError):
    pass


@dataclass(frozen=True, slots=True)
class ResourceLimits:
    max_recipe_bytes: int = 1_048_576
    max_nodes: int = 20_000
    max_depth: int = 16
    max_string_length: int = 2_048
    max_integer_bits: int = 63
    max_steps: int = 240
    max_households: int = 1_000
    max_train_paths: int = 100_000
    max_eval_paths: int = 100_000
    max_epochs: int = 1_000
    max_batch_size: int = 8_192
    max_training_replicates: int = 16
    max_test_banks: int = 16
    max_scenarios: int = 32
    max_training_macro_banks: int = 16
    max_resamples: int = 10_000
    max_path_values: int = 10_000_000
    max_training_work: int = 50_000_000
    max_evaluation_work: int = 100_000_000
    max_bootstrap_work: int = 500_000_000
    max_economic_work: int = 5_000_000

    def __post_init__(self) -> None:
        if any(
            type(getattr(self, f.name)) is not int or getattr(self, f.name) < 1
            for f in fields(self)
        ):
            raise ValueError("resource limits must be positive integers")


@dataclass(frozen=True, slots=True)
class ResourceEstimate:
    steps: int
    households: int
    training_replicates: int
    fitted_models: int
    test_banks: int
    scenarios: int
    training_macro_banks: int
    train_paths: int
    eval_paths: int
    epochs: int
    batch_size: int
    resamples: int
    path_values: int
    training_work: int
    evaluation_work: int
    bootstrap_work: int
    economic_work: int


@dataclass(frozen=True, slots=True)
class PreparedRecipe:
    kind: str
    canonical_json: str
    recipe_sha256: str
    estimate: ResourceEstimate

    @property
    def config(self) -> dict[str, Any]:
        result: dict[str, Any] = strict_json_loads(self.canonical_json)
        return result


def _spec(kind: str) -> RunnerSpec:
    if not isinstance(kind, str) or kind not in RUNNERS:
        raise RecipeError("unsupported runner kind")
    return RUNNERS[kind]


def _config_class(kind: str) -> Any:
    spec = _spec(kind)
    module = importlib.import_module(
        spec.config_module or f"prometheus.orchestration.{spec.module}"
    )
    return getattr(module, spec.config_name)


def default_recipe(kind: str) -> dict[str, Any]:
    model = _config_class(kind)()
    result: dict[str, Any] = strict_json_loads(
        json.dumps(asdict(model), default=json_default, allow_nan=False)
    )
    return result


def _check_raw(value: Any, limits: ResourceLimits) -> None:
    stack = [(value, 0)]
    nodes = 0
    caps = {
        "n_steps": limits.max_steps,
        "n_households": limits.max_households,
        "n_train_paths": limits.max_train_paths,
        "n_eval_paths": limits.max_eval_paths,
        "risk_eval_n_paths": limits.max_eval_paths,
        "n_train_epochs": limits.max_epochs,
        "batch_size": limits.max_batch_size,
        "n_bootstrap_resamples": limits.max_resamples,
        "n_nested_resamples": limits.max_resamples,
    }
    lengths = {
        "training_seeds": limits.max_training_replicates,
        "test_seeds": limits.max_test_banks,
        "scenarios": limits.max_scenarios,
        "training_macro_seeds": limits.max_training_macro_banks,
    }
    while stack:
        item, depth = stack.pop()
        nodes += 1
        if nodes > limits.max_nodes or depth > limits.max_depth:
            raise ResourceLimitError("recipe structure exceeds node/depth budget")
        if isinstance(item, Mapping):
            if nodes + len(stack) + len(item) > limits.max_nodes:
                raise ResourceLimitError("recipe object exceeds node budget")
            for key, child in item.items():
                if not isinstance(key, str) or len(key) > limits.max_string_length:
                    raise RecipeError("recipe object keys must be bounded strings")
                if key in caps and type(child) is int and child > caps[key]:
                    raise ResourceLimitError(f"{key} exceeds configured limit {caps[key]}")
                if (
                    key in lengths
                    and isinstance(child, (list, tuple))
                    and len(child) > lengths[key]
                ):
                    raise ResourceLimitError(f"{key} exceeds configured cardinality limit")
                stack.append((child, depth + 1))
        elif isinstance(item, (list, tuple)):
            if nodes + len(stack) + len(item) > limits.max_nodes:
                raise ResourceLimitError("recipe sequence exceeds node budget")
            stack.extend((child, depth + 1) for child in item)
        elif isinstance(item, str) and len(item) > limits.max_string_length:
            raise ResourceLimitError("recipe string exceeds configured limit")
        elif type(item) is int and item.bit_length() > limits.max_integer_bits:
            raise ResourceLimitError("recipe integer exceeds configured precision budget")
        elif isinstance(item, float) and not math.isfinite(item):
            raise RecipeError("recipe numbers must be finite")


_NEW_KIND_EPOCH_FIELDS: Mapping[str, str] = {
    "qmacro": "max_epochs",
    "recessionnet_kaggle": "max_epochs",
    "inflationcast": "max_epochs",
    "neural_sde": "max_epochs",
    "pde_solver": "pinn_epochs",
    "marl": "n_epochs",
    "rl_hedge": "n_epochs",
}
_NEW_KINDS = (
    "qmacro",
    "recessionnet_kaggle",
    "inflationcast",
    "neural_sde",
    "pde_solver",
    "marl",
    "rl_hedge",
)


def _new_kind_estimate(kind: str, config: Mapping[str, Any]) -> ResourceEstimate:
    """`qmacro`/`recessionnet_kaggle`/`inflationcast`/`neural_sde`/
    `pde_solver`/`marl`/`rl_hedge` each use their own field names
    (`max_epochs`, `bootstrap_resamples`, `n_space_grid_1d`,
    `episodes_per_epoch`, `n_paths`, ...), not the legacy hedging/
    econosim-shaped names `estimate_resources` otherwise reads (and
    several of them reuse names like `n_steps` that WOULD collide with
    that legacy logic's own meaning) -- handled here, mapped onto the
    same generic estimate dimensions, so none of these seven kinds is
    silently admitted at a near-zero cost estimate."""
    epochs = int(config.get(_NEW_KIND_EPOCH_FIELDS.get(kind, ""), 0))
    resamples = int(config.get("bootstrap_resamples", 0))
    train_paths = int(config.get("n_paths", 0))
    training_work = 0
    evaluation_work = 0
    steps = 1
    # `steps` deliberately does NOT reuse `epochs`: `max_steps`'s
    # default limit (240) encodes "calendar periods in an econosim
    # run," an entirely different magnitude from training epochs
    # (hundreds), so admitting these kinds by their real epoch count
    # through that same ceiling would be a category error, not a
    # genuine bound (`test_every_default_recipe_is_typed_canonical_
    # and_admitted` only requires `steps > 0`, not that it equal
    # `epochs`). Each kind instead reports whatever small, real,
    # non-fabricated per-run dimension it actually has, or `1` (one
    # real run performed) where none exists.
    if kind in ("qmacro", "recessionnet_kaggle"):
        training_work = epochs * 3  # linear / classical MLP / hybrid quantum
        steps = int(config.get("window", 1))
    elif kind == "inflationcast":
        training_work = epochs * 5  # + naive persistence, + GRU
        steps = int(config.get("window", 1))
    elif kind == "neural_sde":
        training_work = epochs
        steps = int(config.get("patience", 1))
    elif kind == "pde_solver":
        # Crank-Nicolson grid cost (training_work) plus PINN/deep-BSDE
        # training cost (evaluation_work) -- both real, configurable
        # cost drivers now that `pde_solver_run.run_pde_solver` calls
        # `train_pinn`/`train_deep_bsde` directly with real epoch
        # counts, rather than the fixed 1500/400 `pde_solvers.
        # benchmark.compute_cost_comparison` hardcodes.
        training_work = int(config.get("n_space_grid_1d", 0)) ** 2
        evaluation_work = epochs + int(config.get("bsde_epochs", 0)) * 512
    elif kind == "marl":
        steps = int(config.get("n_steps", 1))
        training_work = (
            epochs * int(config.get("episodes_per_epoch", 0)) * int(config.get("n_steps", 0)) * 2
        )
    elif kind == "rl_hedge":
        steps = int(config.get("n_steps", 1))
        training_work = epochs * train_paths * int(config.get("n_steps", 0))
    return ResourceEstimate(
        steps=steps,
        households=0,
        training_replicates=0,
        fitted_models=0,
        test_banks=0,
        scenarios=0,
        training_macro_banks=0,
        train_paths=train_paths,
        eval_paths=train_paths,
        epochs=epochs,
        batch_size=0,
        resamples=resamples,
        path_values=0,
        training_work=training_work,
        evaluation_work=evaluation_work,
        bootstrap_work=resamples,
        economic_work=0,
    )


def estimate_resources(kind: str, config: Mapping[str, Any]) -> ResourceEstimate:
    if kind in _NEW_KINDS:
        return _new_kind_estimate(kind, config)
    economic = config.get("economy", config)
    hedge = config.get("hedge", config)
    n_steps = int(economic.get("n_steps", config.get("n_steps", 1)))
    financial = kind not in ("economy", "monetary_operations")
    study = kind in ("study", "monetary_study", "rate_study", "mixture_study")
    rows = len(config.get("training_seeds", (0,))) if study else int(financial)
    models = rows * (2 if kind in ("rate_study", "mixture_study") else 1)
    banks = len(config.get("test_seeds", (0,))) if study or kind == "benchmark" else 1
    scenarios = len(config.get("scenarios", (0,))) if study else 1
    macro_banks = len(config.get("training_macro_seeds", ()))
    train = int(hedge.get("n_train_paths", 0)) if financial else 0
    evaluate = (
        int(config.get("n_eval_paths", hedge.get("risk_eval_n_paths", 0))) if financial else 0
    )
    epochs = int(hedge.get("n_train_epochs", 0)) if financial else 0
    batch = int(hedge.get("batch_size", min(256, train))) if financial else 0
    resamples = int(config.get("n_bootstrap_resamples", 0))
    nested = int(config.get("n_nested_resamples", 0))
    arms = 3 if kind in ("rate_study", "mixture_study") else 2
    path_values = (rows * train + scenarios * banks * evaluate) * (n_steps + 1)
    training_work = models * epochs * batch * n_steps
    evaluation_work = max(1, rows) * scenarios * banks * evaluate * n_steps * arms
    bootstrap_work = resamples * max(1, rows) * scenarios * banks
    if kind in ("benchmark", "study"):
        bootstrap_work += resamples * max(1, rows) * scenarios * banks * evaluate
    if nested:
        bootstrap_work += nested * scenarios * 2 * rows * banks * evaluate * 4
    households = int(economic.get("n_households", 2))
    macro_runs = (
        scenarios * banks + rows * macro_banks
        if kind in ("monetary_study", "rate_study", "mixture_study")
        else int(kind in ("economy", "monetary", "monetary_operations", "simulation"))
    )
    economic_work = macro_runs * (
        households**2 + n_steps * households * int(economic.get("max_price_evaluations", 1))
    )
    return ResourceEstimate(
        n_steps,
        households,
        rows,
        models,
        banks,
        scenarios,
        macro_banks,
        train,
        evaluate,
        epochs,
        batch,
        max(resamples, nested),
        path_values,
        training_work,
        evaluation_work,
        bootstrap_work,
        economic_work,
    )


def _admit(estimate: ResourceEstimate, limits: ResourceLimits) -> None:
    checks = {
        "steps": "max_steps",
        "households": "max_households",
        "training_replicates": "max_training_replicates",
        "test_banks": "max_test_banks",
        "scenarios": "max_scenarios",
        "training_macro_banks": "max_training_macro_banks",
        "train_paths": "max_train_paths",
        "eval_paths": "max_eval_paths",
        "epochs": "max_epochs",
        "batch_size": "max_batch_size",
        "resamples": "max_resamples",
        "path_values": "max_path_values",
        "training_work": "max_training_work",
        "evaluation_work": "max_evaluation_work",
        "bootstrap_work": "max_bootstrap_work",
        "economic_work": "max_economic_work",
    }
    for name, limit in checks.items():
        if getattr(estimate, name) > getattr(limits, limit):
            raise ResourceLimitError(f"{name} estimate exceeds configured {limit}")


def prepare_recipe(
    kind: str, config: Mapping[str, Any], *, limits: ResourceLimits | None = None
) -> PreparedRecipe:
    _spec(kind)
    if not isinstance(config, Mapping):
        raise RecipeError("recipe must be an object")
    if limits is not None:
        _check_raw(config, limits)
    try:
        wire = strict_json_loads(json.dumps(dict(config), default=json_default, allow_nan=False))
        if limits is not None and len(json.dumps(wire).encode()) > limits.max_recipe_bytes:
            raise ResourceLimitError("recipe exceeds encoded byte budget")
        if limits is not None:
            _check_raw(wire, limits)
        decoded = _config_class(kind).from_dict(wire)
        normalized = strict_json_loads(
            json.dumps(asdict(decoded), default=json_default, allow_nan=False)
        )
    except (TypeError, AttributeError, OverflowError, RecursionError) as exc:
        raise RecipeError(f"invalid {kind} recipe: {type(exc).__name__}") from exc
    estimate = estimate_resources(kind, normalized)
    if limits is not None:
        _admit(estimate, limits)
    canonical = json.dumps(normalized, sort_keys=True, allow_nan=False)
    return PreparedRecipe(
        kind, canonical, compute_result_hash({"kind": kind, "config": normalized}), estimate
    )


class RunnerResult(Protocol):
    @property
    def manifest(self) -> RunManifest: ...
    @property
    def evidence_bundle(self) -> dict[str, Any]: ...


def execute_recipe(
    kind: str, config: Mapping[str, Any], *, limits: ResourceLimits | None = None
) -> RunnerResult:
    prepared = prepare_recipe(kind, config, limits=limits)
    decoded = _config_class(kind).from_dict(prepared.config)
    spec = _spec(kind)
    runner = getattr(
        importlib.import_module(f"prometheus.orchestration.{spec.module}"), spec.function_name
    )
    result: RunnerResult = runner(decoded)
    return result


def main(argv: list[str] | None = None) -> int:
    import argparse
    from pathlib import Path

    from prometheus.evidence.contracts import read_evidence_bundle
    from prometheus.evidence.export import export_evidence_bundle

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", required=True, choices=sorted(RUNNERS))
    parser.add_argument("--recipe", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        raw = (
            default_recipe(args.kind) if args.recipe is None else read_evidence_bundle(args.recipe)
        )
        prepared = prepare_recipe(args.kind, raw, limits=ResourceLimits())
        report = {
            "schema_version": 1,
            "kind": prepared.kind,
            "config": prepared.config,
            "recipe_sha256": prepared.recipe_sha256,
            "resource_estimate": asdict(prepared.estimate),
            "limits": asdict(ResourceLimits()),
            "admitted": True,
        }
        if args.output is not None:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            export_evidence_bundle(report, args.output)
    except (ValueError, TypeError, OSError) as exc:
        parser.error(str(exc))
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
