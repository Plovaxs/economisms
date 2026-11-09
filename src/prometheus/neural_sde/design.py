"""NSD-01: "Specify neural drift and diffusion architecture -- Design
record lists input features, units and constraints."

`NeuralSDEDesignSpec` is a frozen, importable record (not a prose
document someone could let drift out of sync with the code) -- every
field below is also the literal argument the rest of this package's
functions take, so the design record and the implementation cannot
silently diverge. `design_record_text` renders it as the human-readable
record the acceptance criterion asks for.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class NeuralSDEDesignSpec:
    state_series_ids: tuple[str, ...]
    state_units: tuple[str, ...]
    regime_series_ids: tuple[str, ...]
    regime_units: tuple[str, ...]
    time_unit: str
    constraints: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if len(self.state_series_ids) == 0:
            raise ValueError("state_series_ids must be non-empty")
        if len(self.state_series_ids) != len(self.state_units):
            raise ValueError("state_series_ids and state_units must have the same length")
        if len(self.regime_series_ids) != len(self.regime_units):
            raise ValueError("regime_series_ids and regime_units must have the same length")

    @property
    def state_dim(self) -> int:
        return len(self.state_series_ids)

    @property
    def regime_dim(self) -> int:
        return len(self.regime_series_ids)


DEFAULT_DESIGN_SPEC = NeuralSDEDesignSpec(
    state_series_ids=("KAGGLE_NASDAQ_YOY", "KAGGLE_GDP_YOY"),
    state_units=("percent, year-over-year", "percent, year-over-year"),
    regime_series_ids=("KAGGLE_FEDFUNDS", "KAGGLE_CLAIMS_YOY", "KAGGLE_M2_YOY"),
    regime_units=("percent, annualized rate", "percent, year-over-year", "percent, year-over-year"),
    time_unit="months (dt=1.0 per monthly observation)",
    constraints=(
        "state variables are YoY growth/level rates, not price levels: no "
        "positivity constraint applies (the real KAGGLE_GDP_YOY series "
        "reaches -7.69% in 2020-05, its most negative value in the entire "
        "1981-2023 sample -- see neural_sde.ood) -- the positivity "
        "constraint this package enforces instead is finiteness and a "
        "hard architectural bound on drift/diffusion magnitude "
        "(neural_sde.model)",
        "diffusion output must be a valid covariance matrix (symmetric "
        "PSD) by construction, not by a post-hoc repair step "
        "(neural_sde.model's Cholesky parameterization)",
        "regime features and state are read only through "
        "econosim.pit.build_feature_vector, so no training or evaluation "
        "event can see a feature not yet eligible as of its own decision "
        "time (neural_sde.dataset)",
        "normalization statistics are fit once on the training split "
        "only and frozen before being applied to validation/test "
        "(neural_sde.dataset.FittedScaler)",
    ),
)


def design_record_text(spec: NeuralSDEDesignSpec = DEFAULT_DESIGN_SPEC) -> str:
    lines = [
        "Neural SDE design record",
        "=========================",
        f"State variables ({spec.state_dim}):",
    ]
    for series_id, unit in zip(spec.state_series_ids, spec.state_units, strict=True):
        lines.append(f"  - {series_id}  [{unit}]")
    lines.append(f"Regime/conditioning features ({spec.regime_dim}):")
    for series_id, unit in zip(spec.regime_series_ids, spec.regime_units, strict=True):
        lines.append(f"  - {series_id}  [{unit}]")
    lines.append(f"Time unit: {spec.time_unit}")
    lines.append("Constraints:")
    for constraint in spec.constraints:
        lines.append(f"  - {constraint}")
    return "\n".join(lines)
