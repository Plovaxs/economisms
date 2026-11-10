"""Controlled model rollback with stale-cache purge (MLO-12: "implement
controlled model rollbacks and retirement"; acceptance criterion:
"rollback test confirms restored model and stale-cache purge"), plus
MGR-12 ("define model decommissioning and rollback procedure";
acceptance: "retired version not served; historical evidence
preserved") and DRI-12 ("document decommission or safe-shutdown
contingency"; acceptance: "unhealthy model service stops serving
unapproved outputs").

`mark_unhealthy`/`mark_healthy` implement DRI-12's safe-shutdown
contingency directly on the serving slot rather than as a separate,
disconnected process document: once `mark_unhealthy(reason)` is called,
`cached_predict` fails CLOSED -- it raises `UnhealthyServiceError`
immediately, computing nothing and returning nothing, rather than
serving a possibly-corrupted or stale "unapproved" output while the
health state is bad. `reason` is a required, non-empty field (the same
"no silently-defaulted field" pattern this module's other guards use)
so a shutdown is always traceable to why. `mark_healthy` is a separate,
explicit call -- health never self-clears on a timer or a retry, since
that would reintroduce exactly the silent-recovery-to-a-bad-state risk
this guard exists to prevent.

`ModelServingSlot` models a minimal real serving layer: which
`evidence.model_package.ModelPackage` is currently being served, plus
an inference cache keyed by `(content_hash, input_key)` -- a realistic
reason a stale-cache purge actually matters: a cached prediction
computed under one model version must never be served as if it came
from a DIFFERENT version, even if the input happens to match. `deploy`
simply swaps the currently-served package, keeping whatever cache
entries already exist (a later rollback may still find them valid).
`rollback_to` is the controlled rollback itself: it restores a
PREVIOUS package as current and purges every cache entry NOT keyed to
that package's own `content_hash` -- selectively, not by clearing the
whole cache, since an entry already computed under the package being
restored TO remains valid and is deliberately preserved.

`deploy_if_not_retired` closes MGR-12's specific "retired version not
served" wording literally: plain `deploy`/`rollback_to` above take a
bare `ModelPackage` and have no opinion about registry state (by
design -- this module predates `evidence.model_registry` and is
usable without it); `deploy_if_not_retired` additionally takes the
package's `evidence.model_registry.ModelRegistryEntry` and refuses with
`RetiredModelDeploymentError` if that entry's `state == "retired"`,
reusing the registry's own real state (MLO-08) and append-only
`history` (which already preserves every transition, including the
retirement itself, satisfying "historical evidence preserved") rather
than inventing a second, parallel retirement flag.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from prometheus.evidence.model_package import ModelPackage
from prometheus.evidence.model_registry import ModelRegistryEntry


class RetiredModelDeploymentError(ValueError):
    """Raised by `deploy_if_not_retired` when the package's registry
    entry is in the `retired` state."""


class UnhealthyServiceError(RuntimeError):
    """Raised by `cached_predict` when the slot has been marked
    unhealthy -- the service refuses to produce any further output
    until explicitly marked healthy again."""


@dataclass(slots=True)
class ModelServingSlot:
    current: ModelPackage
    _inference_cache: dict[tuple[str, str], str] = field(default_factory=dict, init=False)
    _unhealthy_reason: str | None = field(default=None, init=False)

    @property
    def is_healthy(self) -> bool:
        return self._unhealthy_reason is None

    def mark_unhealthy(self, reason: str) -> None:
        if not reason or not reason.strip():
            raise ValueError("reason must not be empty -- a shutdown is always traceable")
        self._unhealthy_reason = reason

    def mark_healthy(self) -> None:
        self._unhealthy_reason = None

    def deploy(self, package: ModelPackage) -> None:
        self.current = package

    def deploy_if_not_retired(self, package: ModelPackage, entry: ModelRegistryEntry) -> None:
        if entry.model_id != package.model_id:
            raise ValueError(
                f"registry entry {entry.model_id!r} does not match package {package.model_id!r}"
            )
        if entry.state == "retired":
            raise RetiredModelDeploymentError(
                f"{package.model_id}@{package.model_version}: registry entry is retired "
                "-- a retired model cannot be (re)deployed to serving"
            )
        self.deploy(package)

    def cached_predict(self, input_key: str, compute: Callable[[], str]) -> str:
        if self._unhealthy_reason is not None:
            raise UnhealthyServiceError(
                f"{self.current.model_id}@{self.current.model_version}: service marked "
                f"unhealthy ({self._unhealthy_reason!r}) -- refusing to serve any output"
            )
        cache_key = (self.current.content_hash, input_key)
        if cache_key not in self._inference_cache:
            self._inference_cache[cache_key] = compute()
        return self._inference_cache[cache_key]

    def cache_size(self) -> int:
        return len(self._inference_cache)

    def rollback_to(self, target: ModelPackage) -> None:
        """Restores `target` as the currently served package and purges
        every cache entry not keyed to `target.content_hash` -- a cache
        entry computed under the model being rolled AWAY from must
        never be served again, while one already valid for the
        restored model is kept, not needlessly recomputed."""
        self._inference_cache = {
            key: value
            for key, value in self._inference_cache.items()
            if key[0] == target.content_hash
        }
        self.current = target
