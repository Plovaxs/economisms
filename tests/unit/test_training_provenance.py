import dataclasses

import numpy as np
import pytest

from prometheus.experiments.training_provenance import (
    TrainingProvenanceManifest,
    capture_training_provenance,
)
from prometheus.hedging.deep_hedge import train_deep_hedge
from prometheus.stochastica.gbm import simulate_gbm_paths


def _training_config() -> dict:
    return dict(
        dt=0.1, strike=100.0, maturity=1.0, option_type="call", risk_free_rate=0.05,
        cost_rate=0.005, initial_premium=10.0, cvar_alpha=0.9, turnover_penalty=0.001,
        n_epochs=5, batch_size=64, learning_rate=0.01,
    )


def _price_paths() -> np.ndarray:
    rng = np.random.default_rng(1)
    return simulate_gbm_paths(100.0, 0.08, 0.2, 1.0, n_steps=10, n_paths=500, rng=rng)


def test_capture_training_provenance_reports_config_seed_and_environment() -> None:
    manifest = capture_training_provenance(_training_config(), seed=0)
    assert manifest.config == _training_config()
    assert manifest.seed == 0
    assert set(manifest.environment) == {"python", "platform", "dependencies", "source_sha256"}


def test_manifest_is_immutable() -> None:
    manifest = capture_training_provenance(_training_config(), seed=0)
    with pytest.raises(dataclasses.FrozenInstanceError):
        manifest.seed = 1  # type: ignore[misc]


def test_manifest_id_is_deterministic_for_identical_config_and_seed() -> None:
    m1 = capture_training_provenance(_training_config(), seed=0)
    m2 = capture_training_provenance(_training_config(), seed=0)
    assert m1.manifest_id == m2.manifest_id


def test_manifest_id_differs_for_a_different_seed() -> None:
    """The discriminating half: the RNG state is part of what is being
    captured, so changing only the seed must change the manifest id --
    otherwise the id would not actually pin the RNG state at all."""
    m1 = capture_training_provenance(_training_config(), seed=0)
    m2 = capture_training_provenance(_training_config(), seed=1)
    assert m1.manifest_id != m2.manifest_id


def test_manifest_id_differs_for_a_different_config_value() -> None:
    config_a = _training_config()
    config_b = {**_training_config(), "learning_rate": 0.02}
    m1 = capture_training_provenance(config_a, seed=0)
    m2 = capture_training_provenance(config_b, seed=0)
    assert m1.manifest_id != m2.manifest_id


def test_a_captured_manifest_is_sufficient_to_replay_a_real_training_run() -> None:
    """AUD-03's own acceptance criterion, literally: "stored manifest
    sufficient for replay at pinned environment." Confirmed directly
    against a real `train_deep_hedge` run, not assumed from the fact
    that `seed` is merely present on the manifest -- the SECOND call
    below uses ONLY the manifest's own stored `config` and `seed` (plus
    the externally-supplied, non-JSON-serializable price path array,
    which a manifest cannot itself hold), and still reproduces the
    EXACT SAME objective history, value for value."""
    price_paths = _price_paths()
    config = _training_config()
    seed = 0

    original = train_deep_hedge(price_paths=price_paths, seed=seed, **config)
    manifest = capture_training_provenance(config, seed)

    replayed = train_deep_hedge(price_paths=price_paths, **manifest.config, seed=manifest.seed)
    assert replayed.objective_history == original.objective_history


def test_replaying_with_a_different_seed_from_a_different_manifest_does_not_match() -> None:
    """The discriminating half: replay reproducing the original result
    is not a tautology (e.g. training converging to the same answer
    regardless of seed) -- a manifest captured with a DIFFERENT seed
    must replay to a DIFFERENT result."""
    price_paths = _price_paths()
    config = _training_config()

    original = train_deep_hedge(price_paths=price_paths, seed=0, **config)
    other_manifest = capture_training_provenance(config, seed=1)
    replayed = train_deep_hedge(
        price_paths=price_paths, **other_manifest.config, seed=other_manifest.seed
    )
    assert replayed.objective_history != original.objective_history


def test_training_provenance_manifest_type_is_constructible_directly() -> None:
    manifest = TrainingProvenanceManifest(
        config={"a": 1}, seed=0, environment={"python": "3.14"}, manifest_id="abc"
    )
    assert manifest.config == {"a": 1}
