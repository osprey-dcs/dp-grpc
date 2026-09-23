# Release-note fragment: signed release artifacts (issue #137)

**This is not a release note.** It is the #137 portion of one, written and reviewed alongside the
implementation so the content does not have to be reconstructed later.

**How to use it.** When the release that first carries signed artifacts is cut, paste the
"Signed release artifacts", "Verifying these artifacts", and "Checksum paths fixed" sections
below into `doc/release-notes/rel-<version>.md`, and fold the upgrade items into that document's
"Upgrading from <previous>" checklist. Then delete this file — it has no reason to outlive the
release it feeds.

**Why it lives here.** Plan step 5 calls for release notes for "the version that carries this",
and that version is not yet known: `release.yml` resolves notes as
`doc/release-notes/${GITHUB_REF_NAME}.md`, strictly from the tag, so a notes file written against
a guessed version number is both a stranded file and a failed release-notes check. The signing
content below is durable; a claim about what *else* a given release contains is not, and the
release is weeks out with proto changes expected in between.

**One thing to re-check before pasting:** the asset rename is described below as affecting
consumers of `rel-1.16.0`. If any release ships between 1.16.0 and this one, update the
"Releases before" line in `README.env` and the version references here to match.

---

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

**The asset names change.**  A scripted download of `dp-grpc-<version>.jar.sha256` will get a 404
against this release.  Published assets are now:

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

---

## Upgrade items

Fold these into the carrying release's "Upgrading from <previous>" checklist:

1. **Update any scripted download of the `.sha256` files.** `dp-grpc-<version>.jar.sha256` and
   `dp-grpc-<version>.tar.gz.sha256` no longer exist.  One `SHA256SUMS` covers both artifacts.
2. **Drop any workaround for the checksum path.** If a script recreated a `release/` subdirectory
   to make `sha256sum -c` succeed, remove it.
3. **Optionally, start verifying the signature.** It is a new capability, not a new requirement.
