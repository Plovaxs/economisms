"""Unambiguous dataset provenance on a model artifact (MLO-03: "track
dataset hash, feature contract and training cutoffs"; acceptance
criterion: "model artifact includes unambiguous dataset provenance").

Deliberately a composition of four primitives this project already
built for other checklist items, not a reinvention of any of them:
`model_package.ModelPackage` (MLO-07, the model's own content hash),
`dataset_fingerprint.DatasetFingerprint` (DAT-12, the dataset's content
hash), `reproducible_inference.InputContract` (MLO-11, which already
names a model's feature contract), and `holdout_manifest.HoldoutManifest`
(EXP-04, whose locked train/validation/test date cutoffs already
include the training cutoff this item asks for).

`build_dataset_provenance` requires the feature contract to name the
SAME model as the package it is attached to (`feature_contract.model_id
== model_package.model_id`), confirmed by a discriminating test -- a
provenance record assembled from mismatched pieces describing
DIFFERENT models would not be "unambiguous," it would be actively
misleading. `training_cutoff_date` is read directly from the manifest's
own `"train"` split, not supplied as a separate, independently-typed
date that could silently disagree with the locked manifest.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from prometheus.evidence.dataset_card import DatasetCard
from prometheus.evidence.model_package import ModelPackage
from prometheus.evidence.reproducible_inference import InputContract
from prometheus.experiments.dataset_fingerprint import DatasetFingerprint
from prometheus.experiments.holdout_manifest import HoldoutManifest


class ProvenanceMismatchError(ValueError):
    """Raised when the pieces assembled into a `DatasetProvenance`
    describe inconsistent models or carry no training split at all."""


@dataclass(frozen=True, slots=True)
class DatasetProvenance:
    model_package: ModelPackage
    dataset_fingerprint: DatasetFingerprint
    feature_contract: InputContract
    holdout_manifest: HoldoutManifest
    dataset_card: DatasetCard | None = None

    @property
    def training_cutoff_date(self) -> date:
        train_splits = [s for s in self.holdout_manifest.splits if s.regime == "train"]
        if not train_splits:
            raise ProvenanceMismatchError(
                "holdout_manifest carries no 'train' split -- there is no training "
                "cutoff to report"
            )
        return max(split.end for split in train_splits)


def build_dataset_provenance(
    model_package: ModelPackage,
    dataset_fingerprint: DatasetFingerprint,
    feature_contract: InputContract,
    holdout_manifest: HoldoutManifest,
    dataset_card: DatasetCard | None = None,
) -> DatasetProvenance:
    if feature_contract.model_id != model_package.model_id:
        raise ProvenanceMismatchError(
            f"feature_contract names model {feature_contract.model_id!r}, but "
            f"model_package is for {model_package.model_id!r} -- a provenance record "
            "cannot describe two different models"
        )
    provenance = DatasetProvenance(
        model_package=model_package,
        dataset_fingerprint=dataset_fingerprint,
        feature_contract=feature_contract,
        holdout_manifest=holdout_manifest,
        dataset_card=dataset_card,
    )
    provenance.training_cutoff_date  # noqa: B018 -- fail fast if there is no train split
    return provenance
