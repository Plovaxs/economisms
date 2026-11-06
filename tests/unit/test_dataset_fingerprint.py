import numpy as np
import pytest

from prometheus.experiments.dataset_fingerprint import (
    DatasetFingerprint,
    compute_dataset_fingerprint,
    verify_dataset_fingerprint,
)
from prometheus.stochastica.gbm import simulate_gbm_paths


def _log_returns_from_prices(paths: np.ndarray) -> np.ndarray:
    return np.diff(np.log(paths), axis=1)


def _simple_returns_from_prices(paths: np.ndarray) -> np.ndarray:
    return np.diff(paths, axis=1) / paths[:, :-1]


def _real_price_paths() -> np.ndarray:
    rng = np.random.default_rng(0)
    return simulate_gbm_paths(100.0, 0.08, 0.2, 1.0, n_steps=50, n_paths=10, rng=rng)


def test_rejects_an_empty_transformation_id() -> None:
    with pytest.raises(ValueError, match="transformation_id"):
        compute_dataset_fingerprint(np.array([1.0, 2.0]), "")


def test_rejects_an_empty_array() -> None:
    with pytest.raises(ValueError, match="empty"):
        compute_dataset_fingerprint(np.array([]), "transform")


def test_two_independent_computations_of_the_same_real_transformation_match_exactly() -> None:
    """DAT-12's own acceptance criterion, literally: "every model
    reproduces dataset fingerprint exactly." Two SEPARATE consumers
    ("model A" and "model B") each apply the SAME named transformation
    to their own copy of the SAME real GBM price paths -- not a
    synthetic float array -- and must get the bit-identical
    fingerprint."""
    price_paths = _real_price_paths()
    fp_a = compute_dataset_fingerprint(
        _log_returns_from_prices(price_paths.copy()), "log_returns_v1"
    )
    fp_b = compute_dataset_fingerprint(
        _log_returns_from_prices(price_paths.copy()), "log_returns_v1"
    )
    assert fp_a == fp_b


def test_a_different_transformation_on_the_same_raw_data_gives_a_different_fingerprint() -> None:
    """The discriminating half: the fingerprint must depend on WHICH
    transformation was applied, not just on the raw data's identity."""
    price_paths = _real_price_paths()
    log_fp = compute_dataset_fingerprint(_log_returns_from_prices(price_paths), "log_returns_v1")
    simple_fp = compute_dataset_fingerprint(
        _simple_returns_from_prices(price_paths), "simple_returns_v1"
    )
    assert log_fp != simple_fp


def test_a_different_transformation_id_on_identical_values_gives_a_different_fingerprint() -> None:
    """Even with the exact same numeric output, a different declared
    `transformation_id` must change the fingerprint -- the id is part
    of what is being fingerprinted, not just the values."""
    values = np.array([0.01, -0.02, 0.015])
    fp_a = compute_dataset_fingerprint(values, "method_a")
    fp_b = compute_dataset_fingerprint(values, "method_b")
    assert fp_a != fp_b


def test_verify_dataset_fingerprint_passes_for_a_genuine_reproduction() -> None:
    price_paths = _real_price_paths()
    expected = compute_dataset_fingerprint(
        _log_returns_from_prices(price_paths.copy()), "log_returns_v1"
    )
    assert verify_dataset_fingerprint(
        expected, _log_returns_from_prices(price_paths.copy()), "log_returns_v1"
    )


def test_verify_dataset_fingerprint_fails_for_a_mismatched_transformation_id() -> None:
    price_paths = _real_price_paths()
    expected = compute_dataset_fingerprint(
        _log_returns_from_prices(price_paths.copy()), "log_returns_v1"
    )
    assert not verify_dataset_fingerprint(
        expected, _log_returns_from_prices(price_paths.copy()), "simple_returns_v1"
    )


def test_verify_dataset_fingerprint_catches_a_tiny_numerical_perturbation() -> None:
    """Sensitive to a genuinely tiny change (1e-9), not just gross
    tampering -- confirming this is a real exact-reproduction check,
    not a loose approximate one."""
    price_paths = _real_price_paths()
    expected = compute_dataset_fingerprint(
        _log_returns_from_prices(price_paths.copy()), "log_returns_v1"
    )
    tampered = _log_returns_from_prices(price_paths.copy())
    tampered[0, 0] += 1e-9
    assert not verify_dataset_fingerprint(expected, tampered, "log_returns_v1")


def test_dataset_fingerprint_type_is_constructible_directly() -> None:
    fp = DatasetFingerprint(transformation_id="t", fingerprint="abc")
    assert fp.transformation_id == "t"
