# Verifying a release

Every release publishes the same files from one workflow (`.github/workflows/release.yml`): the wheel, the web
build, the source archive the Linux installer uses, `install-linux.sh`, an SBOM, `build_receipt.json` and
`SHA256SUMS`. There are two independent checks, and they answer different questions.

## 1. Integrity: are these the bytes that were published?

```
sha256sum -c SHA256SUMS            # in the folder holding the downloaded files
```

A checksum list that arrives from the same place as the files proves nothing about who made them. It catches a
corrupt or truncated download, which is what `install-linux.sh` uses it for. **It is not a signature.**

## 2. Provenance: did this workflow build them, from this commit?

From the release that first carries it, each file also has a signed build-provenance attestation (SLSA provenance,
signed with a short-lived Sigstore certificate tied to the workflow's identity and stored by GitHub). With the
GitHub CLI:

```
gh attestation verify econosim-source-<version>.tar.gz --repo Plovaxs/economisms
```

A pass means the file's digest matches an attestation, signed for this repository's `release.yml` workflow, naming
the commit and the tag it ran on. A failure means the file is not what that workflow produced. Verify the wheel,
the installer and the archive the same way before running them.

## What neither check tells you

- Neither says the **code is safe or correct**. Provenance ties bytes to a build, not a build to good intentions;
  anyone who can push a tag to this repository can produce a validly attested release. The protection against that
  is account security and review (see `SECURITY.md`), which a single-maintainer repository has little of.
- Neither covers the **dependencies** the installer downloads (PyTorch and others). They are pinned to `uv.lock`
  and the lock is reviewed; the SBOM lists them; a vulnerability scan (`security` workflow) checks the lock against
  published advisories. A zero today is not a guarantee about tomorrow.
- **No attestation exists for releases before the one that introduced this file** (0.5.3 and earlier carry
  checksums only). The first attested release is the first real test of the mechanism.
