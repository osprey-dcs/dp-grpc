# Plan: PR-triggered CI for the build and the cookbook snippet check (issue #142)

- **Ticket**: [osprey-dcs/dp-grpc#142](https://github.com/osprey-dcs/dp-grpc/issues/142) —
  the authoritative scope statement; this plan records the design rationale and work breakdown.
- **Related**: [#141](https://github.com/osprey-dcs/dp-grpc/issues/141) retired the per-recipe
  "verified against" headers, leaving the compile-based checks as the only guarantee that a
  recipe matches the protos. [#137](https://github.com/osprey-dcs/dp-grpc/issues/137) set the
  current conventions for workflow files (SHA-pinned actions, least-privilege `permissions`).
- **Status**: triaged and scoped 2026-09-24; not yet implemented.

Both existing workflows fire on a `rel-*` tag push, after a release is cut. Nothing validates a
branch before it merges, so `mvn compile` and `tools/check-cookbook-snippets.py` run only when a
contributor remembers to run them. This plan adds a small, read-only workflow that runs both on
every pull request and on every push to `main`.

## Contents

1. [Triage verification](#triage-verification)
2. [Verdict](#verdict)
3. [Settled decisions and rationale](#settled-decisions-and-rationale)
4. [Target workflow shape](#target-workflow-shape)
5. [Blast radius](#blast-radius)
6. [Work breakdown](#work-breakdown)
7. [Not doing](#not-doing)

## Triage verification

Every factual premise in the ticket was re-checked on 2026-09-24 against the current `main`:

| Ticket claim | Verified |
|---|---|
| `.github/workflows/` holds only `release.yml` and `generate-python-stubs.yml` | Yes |
| Both trigger on `rel-*` tag pushes | Yes. Both also accept `workflow_dispatch`, which the ticket omits; neither runs on a PR |
| The snippet check's docstring describes it as a CI gate | Yes, verbatim |
| The check exits non-zero on a real failure and errors clearly without `target/classes` | Yes (`sys.exit` in `classpath()`) |
| The check is stdlib-only Python | Yes. It also shells out to `javac` and to `mvn dependency:build-classpath`, both present once `setup-java` has run |
| `release.yml` pins actions to SHAs and explains why | Yes |
| The checks currently pass on `main` | Yes: `mvn compile` plus the check took about 7 s on a warm local build (103 blocks from 9 docs, 5 `cookbook:partial` skips). A new gate will not be red on day one |

Two things in the original ticket text were **stale or imprecise**. The ticket has since been
rewritten to match this plan, so neither appears there now:

- It listed #137 as an open workflow ticket. #137 is closed (its PRs merged), and so is #136.
- It said `release.yml` "already does" `mvn compile`. It actually runs `mvn -B package`. See D2.

Two facts the ticket does not mention, and which shape the plan:

- **`main` has no branch protection.** The only active ruleset is "Copilot review for default
  branch". A new workflow is advisory until a ruleset requires its check. See D5.
- **Dependabot already covers the new workflow.** `.github/dependabot.yml` watches the
  `github-actions` ecosystem at `/`, which picks up every file in `.github/workflows/`. A new
  `ci.yml` needs no dependabot change. It also gives the monthly grouped action-bump PR its first
  automated check, but only a partial one: `ci.yml` exercises `checkout` and `setup-java` alone.
  Bumps to `upload-artifact`, `download-artifact`, `cosign-installer`, `action-gh-release`, and
  `setup-python` still go untested until a release or a `workflow_dispatch` rehearsal.

## Verdict

**Worth doing, and cheap.** The gap is real: the snippet check has caught defects that review
missed, and after #141 it is the only thing standing between a recipe and a reader holding
uncompilable code. The whole change is one small workflow file, a one-time repository setting,
and a documentation touch-up. There is no proto change and no dp-service impact.

## Settled decisions and rationale

**D1: Triggers are `pull_request` plus `push` to `main`, as the ticket proposes.** The PR run is
the gate. The `main` run catches whatever merges without one, such as a direct push or a merge
queued before the check existed, and gives `main` a status badge's worth of truth. The
`pull_request` event, not `pull_request_target`, is used, so fork PRs run with a read-only token
and no secrets. That suits a job that needs neither.

**D2: Run `mvn -B package`, not `mvn -B compile`.** This departs from the ticket. `package` is
what `release.yml` runs, so CI proves the release build itself rather than a subset of it. A
`pom.xml` change that compiles but breaks packaging surfaces on the PR instead of on a pushed
`rel-*` tag, where it would cost a retag. The difference in cost is negligible: the repo has no
tests (`src/test` does not exist), so `package` only adds jar assembly. `package` still produces
`target/classes`, which is all the snippet check needs.

**D3: No `paths` / `paths-ignore` filter.** The ticket leans this way on runtime grounds. There
is a stronger reason. A workflow skipped by a path filter never reports a status, so once the
check is required (D5), a PR touching only filtered paths waits forever on a check that will not
arrive. The run is short enough that filtering buys nothing worth that trap.

**D4: `permissions: contents: read` and SHA-pinned actions, copying the pins from `release.yml`.**
This is the convention #137 established. Reusing the exact `actions/checkout` and
`actions/setup-java` SHAs keeps the two workflows on the same versions, and Dependabot's grouped
PR bumps them together. Pinning matters less for a job holding no write token, but one rule for
every workflow is easier to keep than a rule with an exception.

**D5: Make the check required, through a ruleset on `main`.** Without this the workflow reports
but does not gate, and the ticket's premise that the checks "should not depend on memory" is only
half met. This is a repository setting, not a file in the PR, so it is a separate step taken
after the workflow has run green at least once. A ruleset accepts any check name, but the UI
suggests only checks that have recently reported, and requiring a check before it has ever run
green would block every open PR. It needs a maintainer with admin rights on the repo.

Because a required check is matched by name, the job gets a deliberately stable and specific
name (`ci-build`), and the workflow file says so. A rename later silently leaves the ruleset
requiring a check that no longer runs, which blocks every PR. A generic name such as `build`
invites a collision: any other workflow's job, or a plain commit status, named `build` would
satisfy the rule.

The ruleset settles two more things:

- **The check's source is pinned to the GitHub Actions app.** Name matching alone accepts a
  status of that name from any integration, or one posted through the API. Pinning the source
  means only the workflow run can satisfy it.
- **Branches must be up to date before merging.** The snippet check spans files, so two PRs can
  each pass alone and fail together — a proto rename on `main` and a new recipe on a branch that
  uses the old name. Requiring an up-to-date branch catches that before merge rather than on the
  following push-to-`main` run (D1). The cost is an occasional "Update branch" click, which is
  acceptable at this repo's PR volume.

**D6: Cancel superseded PR runs.** `concurrency` keyed on the ref with
`cancel-in-progress: true`, so a force-push does not leave a stale run occupying a runner.
`release.yml` already anticipates this: its comment reads "unlike CI this pins cancel-in-progress
off". Runs on `main` are not cancelled. Each push to `main` is a distinct commit worth a verdict,
so the group includes the SHA for pushes.

**D7: A job timeout.** `timeout-minutes: 15`. A cold run (dependency download, protoc fetch)
should finish in two or three minutes. The timeout only bounds a hung Maven download, since the
default ceiling is six hours.

## Target workflow shape

```yaml
name: CI

on:
  pull_request:
  push:
    branches: [main]

# PR runs are superseded by the next push to the branch, so cancel them.  Pushes to main
# each get their own group (keyed on the SHA) so every merged commit gets a verdict.
concurrency:
  group: ci-${{ github.event_name == 'push' && github.sha || github.ref }}
  cancel-in-progress: true

permissions:
  contents: read

jobs:
  # The job name is what the main-branch ruleset requires.  Renaming it leaves the ruleset
  # waiting on a check that never reports, which blocks every PR -- update the ruleset first.
  ci-build:
    runs-on: ubuntu-latest
    timeout-minutes: 15
    steps:
      # Same pins as release.yml; Dependabot bumps both together.
      - uses: actions/checkout@<sha from release.yml> # vX.Y.Z

      - uses: actions/setup-java@<sha from release.yml> # vX.Y.Z
        with:
          distribution: temurin
          java-version: 21
          cache: maven

      # package rather than compile: this is the build release.yml runs, so a pom change
      # that would break a release fails here instead of on the rel-* tag.
      - name: Build
        run: mvn -B package

      - name: Check cookbook snippets
        run: python3 tools/check-cookbook-snippets.py
```

`python3` comes from the runner image. Nothing in the script needs a version newer than the
image ships, so no `setup-python` step is needed.

## Blast radius

- **Contributors.** PRs gain a check. Once D5 is in place, a PR that breaks a proto or a cookbook
  snippet cannot merge until it is fixed. This is the intended effect.
- **Dependabot.** Its PRs now run CI. A bump that breaks `checkout` or `setup-java` now shows up
  as a red PR rather than a broken release. Bumps to the other actions are not exercised (see
  Triage verification).
- **Releases, dp-service, dp-python-lib, and users of the jar.** None affected. No proto, pom,
  or release-workflow change.
- **Release notes.** This change is not user-visible, since it affects contributors only, so it
  gets **no** section in `doc/release-notes/NEXT.md`.

## Work breakdown

One PR:

1. Add `.github/workflows/ci.yml` per the shape above, with the pins copied from `release.yml`.
2. `CLAUDE.md`, "Verifying documentation": state that CI runs both checks on every PR, and keep
   the local commands, since running them before pushing is still the fast loop.
3. `tools/check-cookbook-snippets.py`: in the docstring, change "usable as a pre-commit or CI
   check" to name `ci.yml` as the place it runs.
4. Verify on the PR itself: the new workflow runs and passes. Then push a throwaway commit that
   breaks one snippet (say, a misspelled type), confirm the job goes red on that step, and remove
   the commit with a force-push rather than a revert. This repo merges PRs with merge commits, so
   a break-and-revert pair would land permanently in `main`'s history.

After merge, as a maintainer step outside the PR:

5. Add `ci-build` as a required status check on `main`, via a new ruleset or by extending the
   existing one: source pinned to GitHub Actions, and "require branches to be up to date"
   enabled (D5). Confirm it on the next PR.

## Not doing

- **Prose, link, or spelling checks.** Out of scope per the ticket.
- **Reintroducing per-recipe version assertions.** Retired by #141.
- **`buf lint` / `buf breaking`.** Linting would flag the repo's established lowerCamelCase field
  convention wholesale. Breaking-change detection cannot be a gate in a repo that makes
  deliberate breaking changes (#132). As an advisory, non-blocking check it may be worth a
  separate ticket.
- **Exercising Python stub generation on PRs.** `generate-python-stubs.yml` compiles the same
  protos with `grpcio-tools`' bundled protoc. A proto that Java's protoc accepts and that protoc
  rejects is not a failure mode seen here, and the Java build already proves the protos parse.
- **Adding the snippet check to `release.yml`.** With the check required on `main`, every tagged
  commit has already passed it. Duplicating it would only matter for a tag pushed on an unmerged
  commit, and that is a process error that CI cannot fix.
- **A Maven Dependabot ecosystem.** This is a separate concern: keeping protobuf and gRPC versions
  current is a deliberate, dp-service-coordinated decision, not a routine bump.
