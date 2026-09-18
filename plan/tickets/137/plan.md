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
- **Status**: triaged and scoped 2026-09-18; not yet implemented.

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
there is no path to cutting a release from an arbitrary ref. Note this repo's `release.yml` has no
`workflow_dispatch` trigger at all today, so this is new.

**D6 — Target the next release, not a re-cut.** The ticket suggested `rel-1.16.0`; that shipped
unsigned on 2026-09-16. The reasoning behind the suggestion still applies and points at the next
version now: signatures appearing on a fresh release is cleaner than retroactively changing what
an existing release contains, and `rel-1.15.0` has already been re-cut once this cycle. Do not
re-cut 1.16.0. Whatever version ships next gets the first signed artifacts.

**D7 — Asset rename is a documented release-note item.** Consumers with scripted downloads of
`dp-grpc-<version>.jar.sha256` will 404 after this change. It is a small, well-understood break
for a repo whose consumers are known, but it must be called out in the release notes for the
version that carries it, alongside the new verification instructions.

**D8 — Keep the release-notes existence check, and keep it early.** `release.yml` already verifies
`doc/release-notes/rel-X.Y.Z.md` exists before building, deliberately ahead of
`action-gh-release`, which would otherwise fail on a missing `body_path` only after everything is
built and uploaded. That check must survive the job split and stay in the build job. A rehearsal
has no `rel-` tag and therefore no notes to look for, so it needs the same push-only guard
dp-python-lib uses.

**D9 — Do not adopt dp-python-lib's release-body assembly.** That repo concatenates its notes with
verification instructions into a `RELEASE_BODY.md` in the build job, because its publish job never
checks out the repo. This repo could do the same, but the verification instructions are equally
well placed in the hand-written `doc/release-notes/rel-X.Y.Z.md` and in `README.env`, where they
are reviewable and version-controlled rather than generated. Prefer passing `body_path` to the
notes file as today. This does mean the publish job must either check out the repo or receive the
notes file through the artifact upload; the latter is simpler and is what the work breakdown
assumes.

## Target workflow shape

Two jobs. Permissions are per-job and minimal; the OIDC token never coexists with release-write.

```yaml
permissions:
  contents: read          # default for the workflow; jobs widen as needed

jobs:
  build-and-sign:
    permissions:
      contents: read
      id-token: write     # Sigstore OIDC; the only job that needs it
    steps:
      # checkout, setup-java, mvn -B package, extract version,
      # prepare artifacts, package protos, verify artifacts exist,
      # verify release notes exist (push only)

      - name: Generate SHA256SUMS
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

      # upload-artifact: the jar, the tarball, SHA256SUMS, the bundle, and the notes file

  publish:
    needs: build-and-sign
    if: github.event_name == 'push' && startsWith(github.ref, 'refs/tags/rel-')
    permissions:
      contents: write     # release write; no signing token in scope
    steps:
      # download-artifact, then action-gh-release with body_path pointing at the
      # downloaded notes file
```

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

The `--certificate-identity-regexp` is anchored at the start and pinned to this repo, this
workflow file, and a `rel-` tag ref. An unanchored or looser identity pattern would accept a
signature from any workflow in any repo, which is the common way this verification is made
vacuous.

## Blast radius

**Within this repo**, three files change:

- `.github/workflows/release.yml` — the job split, the signing steps, the consolidated checksums,
  the `workflow_dispatch` rehearsal trigger.
- `README.env` — currently documents only `sha256sum -c dp-grpc-<version>.jar.sha256` and lists
  the two published files. Both statements become wrong. Needs the new asset list, the
  `SHA256SUMS` verification, the `cosign verify-blob` invocation, and a note that `cosign` is the
  tool to install.
- `doc/release-notes/rel-<next>.md` — the asset rename and the new verification path.

`README.md` does not mention checksums or verification and needs no change. `CLAUDE.md`'s
"Releases" section points at `README.env` for download and verification instructions, which stays
true; it is worth a sentence noting artifacts are signed.

**Outside this repo**: nothing consumes the `.sha256` files programmatically that we control.
dp-service builds dp-grpc from source at the matching tag and never downloads a release asset, so
it is unaffected. The sibling tickets are independent cuts of the same change and do not need to
land together.

**Rekor is a public, append-only transparency log.** Signing publishes the artifact digest, the
repo, the workflow path, and the commit SHA to it permanently. All of that is already public for
this repo, so there is nothing to leak here — but it is a property to be aware of, and it would
matter if this pattern were copied to a private repo.

## Work breakdown

1. **Rewrite `release.yml`** into the two-job shape above. Keep the existing build, version
   extraction, artifact preparation, and artifact-existence steps intact — only their job
   placement changes. Keep the release-notes check in the build job with a push-only guard (D8).
   Add the `workflow_dispatch` trigger and the publish gate (D5). Add `set -euo pipefail` to the
   new multi-line run steps, matching the style the existing "Verify release artifacts exist"
   step already uses.

2. **Pass the notes file through `upload-artifact`** so the publish job can use it as `body_path`
   without checking out the repo (D9).

3. **Rehearse via `workflow_dispatch`** against `main` before any tag push. Confirm: the job
   produces a `SHA256SUMS` listing both artifacts; `cosign sign-blob` succeeds and emits a bundle;
   the publish job is skipped. Then verify the rehearsal's bundle locally with the
   `cosign verify-blob` command above, substituting a `--certificate-identity-regexp` that matches
   a branch ref rather than a tag ref — the rehearsal signs under `refs/heads/main`, so the
   tag-anchored pattern will correctly refuse it, and confirming that refusal is itself worth
   doing.

4. **Update `README.env`** — new asset list, both verification commands, a pointer to
   [cosign installation](https://docs.sigstore.dev/cosign/system_config/installation/), and a
   sentence on what the signature proves (repo, workflow, ref, source commit) that the checksum
   does not.

5. **Write the release-notes section** for the version that carries this, covering the asset
   rename as a breaking change for scripted downloads (D7) and the new verification path.

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
