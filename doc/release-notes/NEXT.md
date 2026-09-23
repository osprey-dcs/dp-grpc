# Release Notes — next release (unreleased)

**This is the working draft for the next release. It is not a release note yet.**

Sections accumulate here as tickets land, so the content is written while it is fresh and gets
reviewed in the PR that causes it. At release time this file is renamed to
`doc/release-notes/rel-<version>.md` and finished — see **Cutting the release** at the bottom.

**The version is deliberately not named anywhere in this file.** `release.yml` resolves the notes
path strictly from the tag (`doc/release-notes/${GITHUB_REF_NAME}.md`), so a file committed under
a guessed version is both stranded and a failed release-notes check on the tag that does ship.
Nothing here should assert what *else* the release contains, either: that is knowable only once
the release is cut, and a stale claim in a file that already looks finished is not something the
person cutting the release has any reason to re-read.

## Contents

- [Signed release artifacts (dp-grpc #137)](#signed-release-artifacts-dp-grpc-issue-137)
- [Stub sync no longer rewrites dp-python-lib's pyproject.toml (dp-grpc #153)](#stub-sync-no-longer-rewrites-dp-python-libs-pyprojecttoml-dp-grpc-issue-153)
- [Cutting the release](#cutting-the-release)

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

### Verifying these artifacts

Download the assets into a single directory with no subdirectories, then:

```bash
sha256sum -c SHA256SUMS
```

`SHA256SUMS` covers every published artifact, so that fails if you downloaded only some of them —
most consumers want just the JAR.  To check only the files you have, use
`sha256sum --ignore-missing -c SHA256SUMS`, and confirm the file you care about is listed `OK`,
since `--ignore-missing` also exits 0 when it checked nothing at all.

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

### Checksum paths fixed

The `.sha256` files published through 1.16.0 recorded the artifact path as
`release/dp-grpc-<version>.jar`, because the workflow generated them from the repository root.
A consumer who downloaded the jar and its checksum into one directory and ran `sha256sum -c` got:

```
sha256sum: release/dp-grpc-<version>.jar: No such file or directory
```

unless they first recreated a `release/` subdirectory.  `SHA256SUMS` is generated from inside the
artifact directory and records bare filenames, so it verifies where the files actually land.

### Upgrade items

1. **Update any scripted download of the `.sha256` files.** `dp-grpc-<version>.jar.sha256` and
   `dp-grpc-<version>.tar.gz.sha256` no longer exist.  One `SHA256SUMS` covers both artifacts.
2. **Drop any workaround for the checksum path.** If a script recreated a `release/` subdirectory
   to make `sha256sum -c` succeed, remove it.
3. **Optionally, start verifying the signature.** It is a new capability, not a new requirement.

---

## Stub sync no longer rewrites dp-python-lib's pyproject.toml (dp-grpc Issue #153)

No effect on the published artifacts or the API. This fixes the release-time workflow that syncs
generated Python stubs to [dp-python-lib](https://github.com/osprey-dcs/dp-python-lib).

`generate-python-stubs.yml` had an `Update pyproject.toml version` step whose substitution was
unanchored, so `version\s*=` also matched the tail of ruff's `target-version = "py310"` and
rewrote it to a version number. Ruff then could not parse the file and exited before linting
anything, failing dp-python-lib's CI on every sync.

The step was removed rather than anchored: dp-python-lib moved to setuptools-scm and declares
`dynamic = ["version"]`, so its version comes from its own git tag and there is no literal
`version = "..."` left for the step to bump. `pyproject.toml` is also dropped from the sync
commit's `git add`, leaving the sync to touch only the generated stubs it owns.

---

## Cutting the release

When the version is known and the release is being cut:

1. **`git mv doc/release-notes/NEXT.md doc/release-notes/rel-<version>.md`.** The filename must
   match the tag exactly; `release.yml` fails the run before the build if it does not.
2. **Retitle** the H1 to `# dp-grpc <version> Release Notes` and replace this file's preamble with
   a "Changes since rel-<previous>" summary — written now, when the full contents of the release
   are actually known.
3. **Add the "Upgrading from &lt;previous&gt;" section** as the first section after Contents,
   folding in the per-ticket upgrade items above. Call out silent behavior changes separately from
   compile errors, per CLAUDE.md — a change that alters results without raising an error is the
   one a reader most needs up front.
4. **Delete this "Cutting the release" section** and update Contents.
5. **Add the row to `README.md`'s `## Release Notes` table.**
6. **Decide whether the release is breaking** and say so in the opening if it is. Note that #137
   renames published release assets: that breaks scripted downloads even in a release with no API
   change at all.
7. **Start a fresh `NEXT.md`** for the following cycle.
