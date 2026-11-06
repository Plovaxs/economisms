"""Controlled model rollback with stale-cache purge (MLO-12: "implement
controlled model rollbacks and retirement"; acceptance criterion:
"rollback test confirms restored model and stale-cache purge").

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
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from prometheus.evidence.model_package import ModelPackage


@dataclass(slots=True)
class ModelServingSlot:
    current: ModelPackage
    _inference_cache: dict[tuple[str, str], str] = field(default_factory=dict, init=False)

    def deploy(self, package: ModelPackage) -> None:
        self.current = package

    def cached_predict(self, input_key: str, compute: Callable[[], str]) -> str:
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
