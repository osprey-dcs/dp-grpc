# Plan: Sign release artifacts with keyless Sigstore (issue #137)

- **Ticket**: [osprey-dcs/dp-grpc#137](https://github.com/osprey-dcs/dp-grpc/issues/137) —
  the authoritative scope statement; this plan records the design rationale and work breakdown.
- **Sibling tickets**: [dp-service#221](https://github.com/osprey-dcs/dp-service/issues/221)
  (also covers the container image) and
  [dp-desktop-app#24](https://github.com/osprey-dcs/dp-desktop-app/issues/24) — same change,
  three repos, each cut independently.
- **Precedent**: [dp-python-lib](https://github.com/osprey-dcs/dp-python-lib) already signs,
  landed under its [#29](https://github.com/osprey-dcs/dp-python-lib/issues/29). Its
  `.github/workflows/release.yml` is the reference implementation.
- **Related**: [#133](https://github.com/osprey-dcs/dp-grpc/issues/133) — SHA-pinned actions,
  same customer-driven supply-chain thread.
- **Status**: triaged and scoped 2026-09-18; revised 2026-09-22 after PR review; not yet
  implemented.

`release.yml` publishes a jar and a proto tarball with `sha256sum` files beside them. The
checksums prove integrity but not provenance: they are written by the same job, with the same
token, to the same release page as the artifacts. Anyone who can replace the jar can replace the
checksum next to it. This plan adds a keyless Sigstore signature over a consolidated `SHA256SUMS`,
so the artifacts can be traced to the workflow, ref, and source commit that produced them.

## Contents

1. [Triage verification](#triage-verification)
2. [Settled decisions and rationale](#settled-decisions-and-rationale)
3. [Target workflow shape](#target-workflow-shape)
4. [Blast radius](#blast-radius)
5. [Work breakdown](#work-breakdown)
6. [Follow-ons](#follow-ons)

## Triage verification

Every factual premise in the ticket was re-checked on 2026-09-18 against the current `main`.
All hold:

| Ticket claim | Verified |
|---|---|
| `release.yml` runs one job with `contents: write` throughout | Yes — single `release` job, no `id-token` |
| Two separate `.sha256` files are published | Yes — `rel-1.16.0` shipped exactly four assets: jar, jar.sha256, tar.gz, tar.gz.sha256 |
| Nothing is published to a Maven repository | Yes — `pom.xml` has no `distributionManagement`, `maven-deploy-plugin`, or `maven-gpg-plugin` |
| dp-service consumes dp-grpc by source build | Yes — its `release.yml` checks out dp-grpc at the matching tag and runs `mvn -B -DskipTests install` |
| dp-python-lib signs with Sigstore | Yes — `sigstore/gh-action-sigstore-python`, split build/publish jobs, signed `SHA256SUMS` |
| `sigstore/cosign-installer@6f9f177…` is v4.1.2 | Yes — tag `v4.1.2` resolves to `6f9f17788090df1f26f669e9d70d6ae9567deba6`, and v4.1.2 is the current release |

One claim is now **stale**: the ticket proposes targeting `rel-1.16.0`. That release shipped on
2026-09-16 with unsigned artifacts. See D6.

## Settled decisions and rationale

**D1 — Sigstore rather than GPG.** The ticket's scope note is correct and is adopted wholesale.
A detached signature beside a jar is not how Maven distributes signatures — the convention is a
GPG `.asc` attached at deploy time — but nothing here is published to a Maven repository, so GPG
would produce `.asc` files on a page where no tooling looks for them while adding a long-lived
private key to manage, rotate, and avoid leaking. Sigstore's keyless model has no key at all, and
binds the artifact to a workflow identity rather than proving only that someone held a key. The
gap worth closing is the release-page jar that a human downloads; Sigstore closes it, GPG does not.

**D2 — `cosign`, not the Python Sigstore action.** dp-python-lib uses
`sigstore/gh-action-sigstore-python`, which would work here — it signs bytes and does not care
about file format — but it would mean telling Java consumers to `pip install sigstore` to verify a
jar. `sigstore/cosign-installer` gives `cosign sign-blob`: same Rekor transparency log, same OIDC
identity model, same guarantees, ecosystem-neutral tooling. This is a deliberate divergence from
the dp-python-lib precedent, and the only one.

**D3 — One signed `SHA256SUMS`, replacing the two `.sha256` files.** This repo ships two artifacts
today and the file count grows with each new one. A single `SHA256SUMS` in the standard
`sha256sum` format means one signature covers everything and verification is
`sha256sum -c SHA256SUMS` plus one `cosign verify-blob`. Matches dp-python-lib. This changes
published asset names — see D7.

**D4 — Split build-and-sign from publish.** Adding `id-token: write` to the existing single job
would put a signing token and release-write access in one scope for the whole run, including the
Maven build. Splitting gives the signing job `contents: read` + `id-token: write` and the publish
job `contents: write`, with artifacts travelling between them via `upload-artifact`. Carried over
from dp-python-lib along with the signing itself.

**D5 — Add a `workflow_dispatch` rehearsal that never publishes.** The ticket asks for a rehearsal
before a real tag push. dp-python-lib already has the pattern worth copying: `workflow_dispatch`
builds, verifies, and signs, and the publish job is gated on
`github.event_name == 'push' && startsWith(github.ref, 'refs/tags/rel-')`. That makes a rehearsal
structurally incapable of publishing, rather than relying on the operator not to. It also means
there is no path to *publishing* a release from an arbitrary ref. Note this repo's `release.yml`
has no `workflow_dispatch` trigger at all today, so this is new.

A rehearsal does still sign. `cosign sign-blob` against a branch ref produces a real signature and
a real, permanent Rekor entry bound to that ref — the gate stops the publish, not the signing.
That is what makes the step 3 verification test possible, and it is harmless here, but it is not
a dry run in the sense of leaving no trace. See "Blast radius" on Rekor permanence.

**D6 — Target the next release, not a re-cut.** The ticket suggested `rel-1.16.0`; that shipped
unsigned on 2026-09-16. The reasoning behind the suggestion still applies and points at the next
version now: signatures appearing on a fresh release is cleaner than retroactively changing what
an existing release contains, and `rel-1.15.0` has already been re-cut once this cycle. Do not
re-cut 1.16.0. Whatever version ships next gets the first signed artifacts.

**D7 — Asset rename is a documented release-note item.** Consumers with scripted downloads of
`dp-grpc-<version>.jar.sha256` will 404 after this change. It is a small, well-understood break
for a repo whose consumers are known, but it must be called out in the release notes for the
version that carries it, alongside the new verification instructions.

**D8 — Keep the release-notes existence check, and move it ahead of the build.** `release.yml`
already verifies `doc/release-notes/rel-X.Y.Z.md` exists, which spares the run a failure from
`action-gh-release` on a missing `body_path` after everything is built and uploaded. But today
that check sits *after* `mvn -B package` (`release.yml:55`, build at `:27`), so it only saves the
upload, not the build. dp-python-lib runs the equivalent check before its build for exactly this
reason. The rewrite should move it ahead of `mvn -B package` in the build job, which costs
nothing and makes the rationale true. A rehearsal has no `rel-` tag and therefore no notes to
look for, so it needs the same push-only guard dp-python-lib uses.

**D9 — Do not adopt dp-python-lib's release-body assembly, and accept what that costs.** That repo
concatenates its notes with verification instructions into a `RELEASE_BODY.md` in the build job.
The reason is not that its publish job skips the checkout — it is that `action-gh-release` treats
`body_path` as taking precedence over `body` outright, a fallback rather than a companion, so
setting both would silently drop the instructions. Concatenation is how it gets the hand-written
notes *and* the verification instructions into one body.

This repo keeps `body_path` pointed at the hand-written notes, because the verification
instructions are better placed in `doc/release-notes/rel-X.Y.Z.md` and `README.env`, where they
are reviewable and version-controlled rather than generated at release time. The publish job
therefore needs the notes file, and receiving it through the artifact upload is simpler than a
second checkout; the work breakdown assumes that.

**The consequence, accepted deliberately:** the release page will carry the notes and four
assets, one of them a `.cosign.bundle`, with no on-page instructions for verifying it. A consumer
has to reach `README.env` to learn what the bundle is for. dp-python-lib made the opposite call.
The mitigation is D7 — the release notes for the version that carries this must themselves
include the verification commands, since the notes *are* the release body. Do not let that item
slip to `README.env` alone.

## Target workflow shape

Two jobs. Permissions are per-job and minimal; the OIDC token never coexists with release-write.
Every `uses:` is SHA-pinned with a version comment, per the convention already in `release.yml`
and `#133`; the `upload-artifact` / `download-artifact` pins below are the ones dp-python-lib
already resolved.

```yaml
# A publish must never be cancelled halfway through, so unlike CI this does not set
# cancel-in-progress.
concurrency:
  group: release-${{ github.ref }}

permissions:
  contents: read          # default for the workflow; jobs widen as needed

jobs:
  build-and-sign:
    permissions:
      contents: read
      id-token: write     # Sigstore OIDC; the only job that needs it
    steps:
      # checkout, setup-java, extract version,
      # verify release notes exist (push only, BEFORE the build -- see D8),
      # mvn -B package, prepare artifacts, package protos, verify artifacts exist

      - name: Generate SHA256SUMS
        # working-directory matters: sha256sum writes the path it was given, so running
        # from inside release/ produces bare filenames.  Consumers verify in a download
        # directory that has no release/ subdirectory, and a `release/dp-grpc-...` entry
        # would make `sha256sum -c` fail for them.  See "Checksum paths" below.
        working-directory: release
        run: |
          set -euo pipefail
          sha256sum dp-grpc-${VERSION}.jar dp-grpc-${VERSION}.tar.gz > SHA256SUMS
          cat SHA256SUMS

      - name: Install cosign
        uses: sigstore/cosign-installer@6f9f17788090df1f26f669e9d70d6ae9567deba6 # v4.1.2

      - name: Sign checksums
        working-directory: release
        run: |
          set -euo pipefail
          cosign sign-blob --yes \
            --bundle SHA256SUMS.cosign.bundle \
            SHA256SUMS

      - name: Upload build outputs
        uses: actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a # v7.0.1
        with:
          # the jar, the tarball, SHA256SUMS, the bundle, and the notes file
          retention-days: 7

  publish:
    needs: build-and-sign
    if: github.event_name == 'push' && startsWith(github.ref, 'refs/tags/rel-')
    permissions:
      contents: write     # release write; no signing token in scope
    steps:
      - name: Download build outputs
        uses: actions/download-artifact@3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c # v8.0.1

      - name: Publish GitHub Release
        uses: softprops/action-gh-release@efb35369e0ad2afab669f228072c1b0d510eae64 # v3.0.3
        with:
          # body_path points at the notes file that travelled through the upload (D9).
          # fail_on_unmatched_files is not set in release.yml today: without it a glob that
          # matches nothing publishes a release quietly missing an asset, which in a signing
          # workflow could mean a release with no bundle and no failure.
          fail_on_unmatched_files: true
```

### Checksum paths

Today's workflow runs `sha256sum release/dp-grpc-${VERSION}.jar`, so the published `.sha256`
files contain `release/dp-grpc-<version>.jar` as the path. A consumer who downloads the jar and
its checksum into one directory and runs `sha256sum -c` gets a failure unless they first
recreate a `release/` subdirectory. This is a live defect in `rel-1.16.0`'s assets, not a
hypothetical.

Generating `SHA256SUMS` from inside `release/` fixes it, and the fix is the reason for
`working-directory` rather than a stylistic choice. Work-breakdown step 1 says to carry the
existing steps across unchanged; **this step is the exception** — do not port
`sha256sum release/...` forward under the new filename.

Published assets become:

```
dp-grpc-<version>.jar
dp-grpc-<version>.tar.gz
SHA256SUMS
SHA256SUMS.cosign.bundle
```

Verification, for `README.env` and the release notes:

```bash
sha256sum -c SHA256SUMS

cosign verify-blob \
  --bundle SHA256SUMS.cosign.bundle \
  --certificate-identity-regexp '^https://github.com/osprey-dcs/dp-grpc/\.github/workflows/release\.yml@refs/tags/rel-' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com \
  SHA256SUMS
```

Both commands run in the directory holding the downloaded assets, with no subdirectories —
which is what the bare filenames in `SHA256SUMS` require, and why they are generated that way.

The `--certificate-identity-regexp` is anchored at the start and pinned to this repo, this
workflow file, and a `rel-` tag ref. An unanchored or looser identity pattern would accept a
signature from any workflow in any repo, which is the common way this verification is made
vacuous.

## Blast radius

**Within this repo**, five files change:

- `.github/workflows/release.yml` — the job split, the signing steps, the consolidated checksums,
  the `workflow_dispatch` rehearsal trigger.
- `README.env` — currently documents only `sha256sum -c dp-grpc-<version>.jar.sha256` and lists
  the two published files. Both statements become wrong. Needs the new asset list, the
  `SHA256SUMS` verification, the `cosign verify-blob` invocation, and a note that `cosign` is the
  tool to install.
- `doc/release-notes/rel-<next>.md` — a new document: the asset rename, and the verification
  commands in full, since this file *is* the release body (D9).
- `README.md` — its `## Release Notes` table gets a row for that new document, as CLAUDE.md
  requires of every release note. Nothing else in `README.md` mentions checksums or verification.
- `CLAUDE.md` — its "Releases" section keeps pointing at `README.env`, which stays true, plus a
  sentence noting artifacts are signed with keyless Sigstore.

**Outside this repo**: nothing consumes the `.sha256` files programmatically that we control.
dp-service builds dp-grpc from source at the matching tag and never downloads a release asset, so
it is unaffected. The sibling tickets are independent cuts of the same change and do not need to
land together.

**Rekor is a public, append-only transparency log.** Signing publishes the artifact digest, the
repo, the workflow path, and the commit SHA to it permanently. All of that is already public for
this repo, so there is nothing to leak here — but it is a property to be aware of, and it would
matter if this pattern were copied to a private repo.

This covers rehearsals as well as releases: a `workflow_dispatch` run signs for real, so each
rehearsal leaves a permanent public entry naming the branch it ran against (D5). Harmless here,
and unavoidable if the rehearsal is to test anything — but worth knowing before rehearsing
repeatedly, or off a branch whose name you would rather not publish.

## Work breakdown

1. **Rewrite `release.yml`** into the two-job shape above. Keep the existing build, version
   extraction, artifact preparation, and artifact-existence steps intact — only their job
   placement changes, with two exceptions: the release-notes check moves ahead of `mvn -B package`
   and gains a push-only guard (D8), and checksum generation moves inside `release/` to produce
   bare paths (see "Checksum paths"). Add the `workflow_dispatch` trigger and the publish gate
   (D5), the `concurrency` group, and `fail_on_unmatched_files: true`. SHA-pin
   `upload-artifact` and `download-artifact` like every other action here.

   Add `set -euo pipefail` to the multi-line `run` steps. Note this is a deliberate improvement,
   not an existing convention being matched: today only "Prepare artifacts" sets anything
   (`set -e`), and "Verify release artifacts exist" sets no flags at all. `set -euo pipefail`
   throughout is dp-python-lib's convention and the one to adopt.

2. **Pass the notes file through `upload-artifact`** so the publish job can use it as `body_path`
   without checking out the repo (D9).

3. **Rehearse via `workflow_dispatch`** against `main` before any tag push. Confirm: the job
   produces a `SHA256SUMS` listing both artifacts with bare filenames; `cosign sign-blob` succeeds
   and emits a bundle; the publish job is skipped. Download the rehearsal's artifacts and check
   `sha256sum -c SHA256SUMS` passes in a flat directory.

   Then verify the bundle locally, twice. First with the branch-anchored identity, which should
   pass — the rehearsal signs under `refs/heads/main`:

   ```bash
   cosign verify-blob \
     --bundle SHA256SUMS.cosign.bundle \
     --certificate-identity-regexp '^https://github.com/osprey-dcs/dp-grpc/\.github/workflows/release\.yml@refs/heads/main$' \
     --certificate-oidc-issuer https://token.actions.githubusercontent.com \
     SHA256SUMS
   ```

   Then again with the `refs/tags/rel-` pattern from "Target workflow shape", which **must fail**.
   Confirming that refusal is the point: it proves the tag anchor in the published instructions is
   load-bearing rather than decorative.

4. **Update `README.env`** — new asset list, both verification commands, a pointer to
   [cosign installation](https://docs.sigstore.dev/cosign/system_config/installation/), and a
   sentence on what the signature proves (repo, workflow, ref, source commit) that the checksum
   does not.

5. **Write the release notes** for the version that carries this, covering the asset rename as a
   breaking change for scripted downloads (D7) and the verification commands in full — the notes
   are the release body, so anything omitted here is absent from the release page (D9). Add the
   row to `README.md`'s `## Release Notes` table, per CLAUDE.md.

6. **Add a sentence to `CLAUDE.md`'s "Releases" section** noting that artifacts are signed with
   keyless Sigstore and that `README.env` carries the verification instructions.

7. **Cut the next release** and verify the published bundle end to end from the release page, as a
   consumer would, before announcing it.

## Follow-ons

- **The sibling repos.** dp-service#221 and dp-desktop-app#24 carry the same change; dp-service
  additionally signs its container image, which `cosign` handles natively but which is out of
  scope here. This plan's workflow shape should transfer to dp-desktop-app almost verbatim.

- **Distribution model.** The ticket raises, and explicitly declines to settle, whether
  build-from-source is the intended long-term model for Java consumers. It works and is arguably
  the most trustworthy option, but it requires the full toolchain and a network fetch of dp-grpc
  at build time. If the answer becomes "publish properly", GitHub Packages
  (`maven.pkg.github.com`) is the low-friction step — no GPG requirement, `GITHUB_TOKEN` auth —
  and Maven Central is the heavier option where GPG becomes mandatory. That decision belongs in
  its own ticket and does not block this one; nothing here forecloses it.

- **Verifying in CI.** Once signing is in place, a consumer-side `cosign verify-blob` in
  dp-service's release workflow would close the loop, turning the signature from something a human
  may check into something the pipeline enforces. Only worth doing if dp-service ever starts
  consuming the published jar rather than building from source.

- **Tag and version validation.** Out of scope for #137, but adjacent and worth its own ticket.
  `release.yml` derives `VERSION` by stripping `rel-` from the tag with no validation, so a typo
  (`rel-v1.17.0`, `rel-1.17`) yields a release named after the typo, and nothing cross-checks the
  built jar's version against the tag. dp-python-lib validates both — an anchored regex on the tag
  shape, then a string compare against the built artifact's version — on the reasoning that
  mislabelled artifacts should not be published. Signing raises the stakes a little: a signature
  binds an artifact to a commit, but says nothing about whether it is *named* correctly. Do not
  fold this into #137; the rewrite is large enough already.
