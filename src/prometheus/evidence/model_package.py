"""Model package versioning and content-hash immutability (MLO-07:
"version artifacts and keep immutable approved packages"; acceptance
criterion: "every model package resolves to unique content hash").

`ModelPackage` is deliberately a LIGHTWEIGHT, frozen record -- a
model/version label plus a `content_hash` -- not a container for the
artifact's own (potentially large) bytes, the same separation
`evidence.integrity`'s checksum seals already draw between a hash and
the content it covers. `build_model_package` is the only intended
constructor: it computes `content_hash` from the artifact's actual
bytes via plain SHA256 (not `experiments.manifest.compute_result_hash`'s
canonical-JSON convention, since an artifact's bytes are an opaque
binary blob -- e.g. a real `torch.save`d model `state_dict`, used in
this module's own test file -- not a JSON-serializable payload), so a
caller can never end up with a package whose recorded hash does not
actually match the bytes it was built from.

"Immutable approved packages" is demonstrated, not merely asserted:
`verify_package_integrity` independently re-hashes an artifact's bytes
(as if re-reading them back from separate storage) and compares
against the package's own recorded `content_hash`, raising
`PackageIntegrityError` if they no longer match -- catching exactly the
case a real immutability guarantee exists to prevent, bytes that
changed after the package recording them was built.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

_SHA256_HEX_PATTERN = re.compile(r"[0-9a-f]{64}")


class PackageIntegrityError(ValueError):
    """Raised when an artifact's recomputed hash does not match its
    package's recorded `content_hash`."""


@dataclass(frozen=True, slots=True)
class ModelPackage:
    model_id: str
    model_version: str
    content_hash: str

    def __post_init__(self) -> None:
        if not self.model_id:
            raise ValueError("model_id must not be empty")
        if not self.model_version:
            raise ValueError("model_version must not be empty")
        if not _SHA256_HEX_PATTERN.fullmatch(self.content_hash):
            raise ValueError("content_hash must be a 64-character lowercase hex SHA256 digest")


def build_model_package(model_id: str, model_version: str, artifact_bytes: bytes) -> ModelPackage:
    if not artifact_bytes:
        raise ValueError("artifact_bytes must not be empty")
    content_hash = hashlib.sha256(artifact_bytes).hexdigest()
    return ModelPackage(model_id=model_id, model_version=model_version, content_hash=content_hash)


def verify_package_integrity(package: ModelPackage, artifact_bytes: bytes) -> None:
    actual = hashlib.sha256(artifact_bytes).hexdigest()
    if actual != package.content_hash:
        raise PackageIntegrityError(
            f"{package.model_id}@{package.model_version}: recomputed hash {actual} does not "
            f"match the package's recorded content_hash {package.content_hash} -- the artifact "
            "was modified after packaging, or does not match this package at all"
        )
