# dp-grpc 1.17.0 Release Notes

Changes since rel-1.16.0.  This release contains **no proto or API changes** — the generated
stubs are identical to 1.16.0's.  It changes how release artifacts are published and verified:
the checksum files are consolidated into one `SHA256SUMS`, and that file is signed with keyless
Sigstore.

**The asset names change.** A scripted download of `dp-grpc-<version>.jar.sha256` will get a 404
against this release.  See **Upgrading from 1.16.0** below.

## Contents

- [Upgrading from 1.16.0](#upgrading-from-1160)
- [Signed release artifacts (dp-grpc #137)](#signed-release-artifacts-dp-grpc-issue-137)
- [Verifying these artifacts](#verifying-these-artifacts)
- [Checksum paths fixed](#checksum-paths-fixed)

## Upgrading from 1.16.0

No code changes are required; the stubs are unchanged.  Only artifact consumers are affected:

1. **Update any scripted download of the `.sha256` files.** `dp-grpc-<version>.jar.sha256` and
   `dp-grpc-<version>.tar.gz.sha256` no longer exist.  One `SHA256SUMS` covers both artifacts.
2. **Drop any workaround for the checksum path.** If a script recreated a `release/` subdirectory
   to make `sha256sum -c` succeed, remove it — see [Checksum paths fixed](#checksum-paths-fixed).
3. **Optionally, start verifying the signature.** It is a new capability, not a new requirement.

## Signed release artifacts (dp-grpc Issue #137)

The checksums published with previous releases established integrity but not origin.  They were
written by the same job, with the same token, to the same release page as the artifacts they
described — so anyone able to replace a jar could replace the checksum sitting next to it.

This release adds a keyless Sigstore signature over `SHA256SUMS`, which binds the artifacts to the
repository, workflow file, tag, and source commit that produced them.  There is no key to
distribute, rotate, or leak: the signing identity is a short-lived certificate issued to the
GitHub Actions run itself and recorded in the public Rekor transparency log.

The release workflow is now split into two jobs.  The job that builds and signs holds the OIDC
signing token but cannot write to the release; the job that publishes can write to the release but
holds no signing token.  Publishing is gated on a `rel-*` tag push, so the `workflow_dispatch`
rehearsal trigger added alongside it is structurally incapable of publishing.

Published assets are now:

```
dp-grpc-<version>.jar
dp-grpc-<version>.tar.gz
SHA256SUMS
SHA256SUMS.cosign.bundle
```

## Verifying these artifacts

Download the assets into a single directory with no subdirectories, then:

```bash
sha256sum -c SHA256SUMS
```

To verify the signature, install [cosign](https://docs.sigstore.dev/cosign/system_config/installation/)
and run:

```bash
cosign verify-blob \
  --bundle SHA256SUMS.cosign.bundle \
  --certificate-identity-regexp '^https://github.com/osprey-dcs/dp-grpc/\.github/workflows/release\.yml@refs/tags/rel-' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com \
  SHA256SUMS
```

Expect `Verified OK`.

Keep the `--certificate-identity-regexp` exactly as written.  It is anchored at the start and
pinned to this repository, this workflow file, and a `rel-` tag.  A loosened or unanchored pattern
would accept a valid signature made by any workflow in any repository — which is the usual way
this check ends up passing while proving nothing.

Full instructions, including what the signature proves that the checksum does not, are in
[`README.env`](https://github.com/osprey-dcs/dp-grpc/blob/main/README.env).

## Checksum paths fixed

The `.sha256` files published through 1.16.0 recorded the artifact path as
`release/dp-grpc-<version>.jar`, because the workflow generated them from the repository root.
A consumer who downloaded the jar and its checksum into one directory and ran `sha256sum -c` got:

```
sha256sum: release/dp-grpc-1.16.0.jar: No such file or directory
```

unless they first recreated a `release/` subdirectory.  `SHA256SUMS` is generated from inside the
artifact directory and records bare filenames, so it verifies where the files actually land.
