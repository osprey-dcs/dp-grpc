# Release Notes — next release (unreleased)

**This is the working draft for the next release. It is not a release note yet.**

Sections accumulate here as tickets land, so the content is written while it is fresh and gets
reviewed in the PR that causes it. At release time this file is renamed to
`doc/release-notes/rel-<version>.md` and finished — see **Cutting the release** at the bottom.

**The version of the upcoming release is deliberately not named anywhere in this file**, in its
filename or in its prose.  `release.yml` resolves the notes path strictly from the tag
(`doc/release-notes/${GITHUB_REF_NAME}.md`), so a file committed under a guessed version is both
stranded and a failed release-notes check on the tag that does ship.  Past versions are named
freely where they are the point — "published through 1.16.0" is a durable fact about what shipped,
not a guess about what is about to.

Nothing here should assert what *else* the release contains, either: that is knowable only once
the release is cut, and a stale claim in a file that already looks finished is not something the
person cutting the release has any reason to re-read.

## Contents

- [Signed release artifacts (dp-grpc #137)](#signed-release-artifacts-dp-grpc-issue-137)
- [Stub sync no longer rewrites dp-python-lib's pyproject.toml (dp-grpc #153)](#stub-sync-no-longer-rewrites-dp-python-libs-pyprojecttoml-dp-grpc-issue-153)
- [Typed Python stubs (dp-grpc #158)](#typed-python-stubs-dp-grpc-issue-158)
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

`SHA256SUMS` lists the two downloadable artifacts — `dp-grpc-<version>.jar` and
`dp-grpc-<version>.tar.gz` — so that fails if you downloaded only one of them, and most consumers
want just the JAR.  To check only the files you have, use
`sha256sum --ignore-missing -c SHA256SUMS`, and confirm the file you care about is listed `OK`,
since `--ignore-missing` also exits 0 when it checked nothing at all.

`SHA256SUMS` does not list itself or `SHA256SUMS.cosign.bundle`, so `sha256sum -c` says nothing
about either.  What protects them is the signature: `cosign verify-blob` below checks the bundle
against `SHA256SUMS`, and the checksums in turn cover the artifacts.

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

## Typed Python stubs (dp-grpc Issue #158)

No effect on the protos, the Java artifacts, or the Python runtime. This changes what the stub
workflow delivers to [dp-python-lib](https://github.com/osprey-dcs/dp-python-lib).

The generated `*_pb2.py` and `*_pb2_grpc.py` modules carry no type information, so a type checker
could not see a single message class. `generate-python-stubs.yml` now also emits
[mypy-protobuf](https://github.com/nipunn1313/mypy-protobuf) `.pyi` stubs beside every module.
They type message constructors, fields, and enums and, with
[`types-grpcio`](https://pypi.org/project/types-grpcio/) installed, the request and response of
every RPC on the service stubs. The generator change leaves the `.py` output unchanged: those
modules differ from the previous sync only where the protos changed.

Two further changes to the workflow:

- **The generators are pinned and hash-locked**, in
  [`tools/python-stubs-requirements.txt`](https://github.com/osprey-dcs/dp-grpc/blob/main/tools/python-stubs-requirements.txt),
  compiled from `grpcio-tools==1.84.0` and `mypy-protobuf==5.1.0`. They were installed unversioned
  before, so a sync could silently raise the gencode versions stamped into the stubs, and with
  them dp-python-lib's runtime minimums, whenever a new `grpcio-tools` was published.
- **The run fails closed** if any generated file keeps an absolute import of a generated module
  after the import fixup, or if any module has no matching stub. Every run, dry or real, attaches
  the generated tree as the `python-stubs` artifact.

### Upgrade items

1. **If you generate stubs yourself** following
   [`python-stubs.md`](https://github.com/osprey-dcs/dp-grpc/blob/main/doc/cookbook/python-stubs.md),
   install from the requirements file and add `--mypy_out` / `--mypy_grpc_out`. Widen the import
   fixup to `*.pyi`: an unfixed import in a stub does not fail, it silently turns the types it
   carries into `Any`.
2. **To type-check stub calls**, install `types-grpcio`. Without it, mypy reports
   `overload-cannot-match` inside the generated `*_pb2_grpc.pyi`.

---

## Cutting the release

When the version is known and the release is being cut:

1. **Check dp-python-lib against the typed stubs (#158) before pushing the tag.** The first sync
   that carries `.pyi` files type-checks dp-python-lib's code and cookbook snippets against them,
   even with its suppression of the generated package in place. Confirm its preparation PR,
   [osprey-dcs/dp-python-lib#60](https://github.com/osprey-dcs/dp-python-lib/pull/60), is still
   merged. Then dispatch `generate-python-stubs.yml` from `main` with `dry_run: true`, drop the
   `python-stubs` artifact into a dp-python-lib checkout at `src/dp_python_lib/grpc/`, and confirm
   `mypy src/` and its cookbook snippet checker both pass. If they do not, fix dp-python-lib
   first: a red sync PR is the alternative. See
   [`plan/tickets/158/plan.md`](https://github.com/osprey-dcs/dp-grpc/blob/main/plan/tickets/158/plan.md),
   "Cross-repo sequencing".
2. **`git mv doc/release-notes/NEXT.md doc/release-notes/rel-<version>.md`.** The filename must
   match the tag exactly; `release.yml` fails the run before the build if it does not.
3. **Retitle** the H1 to `# dp-grpc <version> Release Notes` and replace this file's preamble with
   a "Changes since rel-<previous>" summary — written now, when the full contents of the release
   are actually known.
4. **Add the "Upgrading from &lt;previous&gt;" section** as the first section after Contents,
   folding in the per-ticket upgrade items above. Call out silent behavior changes separately from
   compile errors, per CLAUDE.md — a change that alters results without raising an error is the
   one a reader most needs up front.
5. **Repoint `blob/main/...` links to `blob/rel-<version>/...`.** This file is published as the
   release body via `body_path`, and relative links do not survive that lift — they resolve against
   the repo root, not `doc/release-notes/`, and 404.  Links here are already absolute for that
   reason, but one pinned to `main` drifts as the repo moves on; pinned to the tag it keeps
   describing the content this release actually shipped.
6. **Delete this "Cutting the release" section** and update Contents.
7. **Add the row to `README.md`'s `## Release Notes` table.**
8. **Decide whether the release is breaking** and say so in the opening if it is. Note that #137
   renames published release assets: that breaks scripted downloads even in a release with no API
   change at all.
9. **Start a fresh `NEXT.md`** for the following cycle.
