# Plan: typed Python stubs (`.pyi`) from `generate-python-stubs.yml` (issue #158)

- **Ticket**: [osprey-dcs/dp-grpc#158](https://github.com/osprey-dcs/dp-grpc/issues/158) —
  the authoritative scope statement; this plan records the design rationale and work breakdown.
- **Related**: split out of
  [osprey-dcs/dp-python-lib#30](https://github.com/osprey-dcs/dp-python-lib/issues/30), whose
  mypy CI gate landed in dp-python-lib PR #57 by suppressing the generated package.
  [#153](https://github.com/osprey-dcs/dp-grpc/issues/153) is the most recent change to this
  workflow. [#142](https://github.com/osprey-dcs/dp-grpc/issues/142) deliberately kept stub
  generation out of PR CI.
- **Status**: triaged and scoped 2026-09-24; not yet implemented.

The generated `_pb2.py` and `_pb2_grpc.py` modules carry no type information. As a result,
dp-python-lib's `mypy src/` cannot see a single protobuf message class. This plan makes the stub
workflow emit `.pyi` files alongside them, and sets out the dp-python-lib work needed to benefit
from them.

## Contents

1. [Triage verification](#triage-verification)
2. [The experiment](#the-experiment)
3. [Verdict](#verdict)
4. [Settled decisions and rationale](#settled-decisions-and-rationale)
5. [Cross-repo sequencing](#cross-repo-sequencing)
6. [Blast radius](#blast-radius)
7. [Work breakdown](#work-breakdown)
8. [dp-python-lib handoff](#dp-python-lib-handoff)
9. [Not doing](#not-doing)

## Triage verification

Every factual premise in the ticket was re-checked on 2026-09-24 against dp-grpc `main` and
dp-python-lib `origin/main`:

| Ticket claim | Verified |
|---|---|
| The generation step is `grpc_tools.protoc` with `--python_out` / `--grpc_python_out`, then a `find … -name "*_pb2*.py"` sed fixup | Yes, verbatim |
| The `find` glob skips `.pyi` | Yes |
| The `.pyi` imports might have a different shape, such as no `as` clause, which the sed would miss | **No, for this toolchain.** Both generators emit `import common_pb2 as _common_pb2`, which the existing sed pattern rewrites correctly. Only the glob needs widening. The worry is still reasonable for a future generator version, so D3 adds a fail-closed guard |
| The sync step (`rm -rf` then `cp -r out/python/*`) needs no change | Yes. The glob carries `.pyi` across |
| The dry-run summary lists `*.py` only | Yes |
| "Pin the generator version alongside `grpcio-tools`" | **Imprecise.** `grpcio-tools` is not pinned either: the workflow runs `pip install grpcio grpcio-tools protobuf` unversioned. See D2 |
| dp-python-lib's `mypy src/` reports 426 errors across 27 files, about 390 from this cause | **Stale.** PR #57 fixed the real errors. With the suppression removed, `main` now reports **386 errors in 13 files, every one `name-defined` or `attr-defined`**. That strengthens the ticket's point, since the protobuf blind spot is now the only thing wrong |
| dp-python-lib#30 "adds" the suppression | It has landed. #30 is closed, merged via PR #57 |

Three facts the ticket does not mention, each of which shapes the plan:

- **dp-python-lib types its stub as `Any`.** Every client passes its stub class to
  `ServiceApiClientBase.__init__(channel, stub_class: Callable[[grpc.Channel], Any])`, which stores
  `self._stub = stub_class(channel)`. Calls then go through a helper that takes
  `stub_call: Callable`. So no generator, whichever is chosen, type-checks dp-python-lib's RPC
  calls until dp-python-lib types `_stub`. The ticket counts typed stub calls as part of the
  payoff. They are, but only after that dp-python-lib change.
- **Stub-call types also need `types-grpcio`.** mypy-protobuf's `_pb2_grpc.pyi` types each RPC as
  `grpc.UnaryUnaryMultiCallable[Req, Resp]` and so on. dp-python-lib sets
  `ignore_missing_imports` on `grpc`, which turns those into `Any`. Its pyproject explains this
  with the comment "grpcio ships no type information and there is no maintained stub package
  for it". That comment is out of date: `types-grpcio` (typeshed) is on PyPI, at 1.83.0.20260730
  as of this writing.
- **dp-python-lib's suppression does not survive the arrival of `.pyi` files.** mypy always
  follows stub files, so `follow_imports = "skip"` stops applying to them. The first sync that
  carries stubs would therefore turn dp-python-lib's CI **red with 10 errors**, even with the
  suppression untouched. That makes the order of work across the two repos a real constraint. See
  [Cross-repo sequencing](#cross-repo-sequencing).

## The experiment

The ticket asks for the generator to be chosen by generating both options and running
dp-python-lib's `mypy src/` against each. That was done:

- **Toolchain.** `grpcio-tools` 1.84.0 (protobuf gencode 7.35.1), `mypy-protobuf` 5.1.0, and
  mypy 2.3.1, on Python 3.12. The workflow runs 3.11. Generated output should not depend on the
  interpreter version, and step 7 of the work breakdown checks the workflow's own output anyway.
- **Baseline check.** The baseline output, with the fixup applied, is **byte-identical** to the
  stubs committed in dp-python-lib today. The unpinned install currently resolves to exactly what
  was last synced.
- **Variants.** Adding `--pyi_out` or `--mypy_out` leaves every `.py` file byte-identical. The
  new flags only add `.pyi` files.
- **Where the results live.** Raw mypy outputs and the probe file are kept in
  `~/dp/dev/tickets/dp-grpc/158/`.

**Whole-package run** (dp-python-lib `main`, generated package swapped in, suppression removed):

| Variant | Files added | `mypy src/` result |
|---|---|---|
| Baseline (no stubs) | none | 386 errors: 254 `name-defined`, 132 `attr-defined` |
| `--pyi_out` | 5 `_pb2.pyi` (2.7k lines) | 5 errors, 0 `name-defined` / `attr-defined` |
| mypy-protobuf | 5 `_pb2.pyi` + 5 `_pb2_grpc.pyi` (14.7k lines) | 11 errors, 0 `name-defined` / `attr-defined`, of which 4 are `overload-cannot-match` *inside* the generated `_pb2_grpc.pyi` |
| mypy-protobuf + `types-grpcio`, with the `grpc` ignore dropped | same | 9 errors, none in generated code |

The suppression was removed for those runs, to see everything the stubs expose. A separate run
answers what the *first sync* does to dp-python-lib as configured today: mypy-protobuf stubs
swapped in, suppression and `grpc` ignore both left in place. It reports **10 errors**: the
seven hand-written ones below, plus three of the four `overload-cannot-match`. mypy still reads
the `.pyi` files despite `follow_imports = "skip"`. The fourth is absent only because nothing
checked imports `ingestion_stream_pb2_grpc`.

The errors that remain are in hand-written code, and they are real findings rather than stub
defects:

- Four `str | None` / `… | None` values passed where non-optional ones are required, in
  `machine_config_client.py`. Both generators report these.
- One `EnumDescriptor | None` dereferenced unguarded, in `query_conversions.py`. Both generators
  report this.
- Two enum `ValueType` mismatches in `export_client.py`. Only mypy-protobuf reports these, because
  it types enums as distinct `NewType`s.
- Two `None` assigned to a `grpc.Channel` attribute, in `mldp_client.py`. These appear only with
  `types-grpcio`.

The four `overload-cannot-match` errors come from `grpc` resolving to `Any`. That makes the
stub's `__new__(channel: grpc.Channel)` and `__new__(channel: grpc.aio.Channel)` overloads
indistinguishable. `types-grpcio` removes all four.

**What each variant catches.** A probe module with five deliberate mistakes shows the difference:

| Mistake | `--pyi_out` | mypy-protobuf, no `types-grpcio` | mypy-protobuf + `types-grpcio` |
|---|---|---|---|
| P1: wrong request type passed to a stub call | missed | missed | **caught** |
| P2: stub call's response assigned to the wrong response type | missed | missed | **caught** |
| P3: nonexistent field in a message constructor | caught | caught | caught |
| P4: wrong field type in a constructor | caught | caught | caught |
| P5: misspelled field on attribute assignment | caught | caught | caught |

Message-level checking is the same under both generators. Checking stub calls is only possible
with mypy-protobuf, and even then only once `types-grpcio` is present. Without it, mypy-protobuf
catches nothing more than `--pyi_out`, and reports four errors of its own.

## Verdict

**Worth doing, and cheap on this side.** The dp-grpc change is a few lines in one workflow, a pin
file, and a documentation update. There is no proto change, no change to the Java artifact, no
dp-service impact, and no runtime change for Python users, since every `.py` file stays
byte-identical. Most of the value, and most of the work, falls in dp-python-lib, and it depends
on that repo doing three things in order (see the handoff).

## Settled decisions and rationale

**D1: Use mypy-protobuf (`--mypy_out` + `--mypy_grpc_out`).** This is the ticket's leaning, now
backed by the experiment. It is the only option that can type-check stub calls, and dp-python-lib
makes every RPC call through a stub. `--pyi_out` would save a generation-side dependency and
nothing else. It adds no runtime dependency for anyone, because the `.pyi` files are read only by
type checkers. The price is that mypy-protobuf's typing is stricter: its enum `NewType`s surface
two extra errors in dp-python-lib. Those are genuine type confusions and worth fixing anyway.

**D2: Pin both generators, hash-locked, in one requirements file.** The direct pins go in
`tools/python-stubs-requirements.in`:

```
grpcio-tools==1.84.0
mypy-protobuf==5.1.0
```

That file is compiled with `pip-compile --generate-hashes` into
`tools/python-stubs-requirements.txt`, which locks every transitive package (`grpcio`,
`protobuf`, `types-protobuf`, …) to an exact version and hash. Both files are committed. The
workflow and `python-stubs.md` install with `pip install --require-hashes -r
tools/python-stubs-requirements.txt`, so the pins cannot drift between the automated path and the
manual one. The separate `grpcio` and `protobuf` installs are dropped: `grpcio-tools` depends on
both, and generation needs nothing else. By default `pip-compile` records the hashes of every
published distribution of each pinned version, so the lock installs on any platform, not only
the one it was compiled on.

The hashes are there because of where the install runs. This job later checks out dp-python-lib
with `DP_BOT_TOKEN`, a cross-repo write credential. That is why the workflow pins its actions to
commit SHAs. mypy-protobuf is a new package in that job, and it runs as a protoc plugin.
`==` pins on the two direct dependencies would leave the transitive ones floating, and would
still trust PyPI to serve the same bytes for a given version. Hash-locking applies the same
standard as the SHA pins, and it also makes the generated output fully reproducible, down to
the `protobuf` package the mypy-protobuf plugin runs against.

Pinning `grpcio-tools` is the more important half. It is what stamps `GRPC_GENERATED_VERSION` and
the protobuf gencode version into the `.py` files. dp-python-lib's runtime minimums
(`grpcio>=1.84.0`, `protobuf>=7.35.1`) are kept in sync with those stamps by hand, as its
pyproject says. Today a release sync can raise those minimums silently, whenever a new
`grpcio-tools` happens to be out on the day of the tag. Pinned, raising them becomes a
deliberate change to this file, and it then needs a matching dp-python-lib change.

1.84.0 is the version that produced the stubs dp-python-lib has now, so pinning to it changes
nothing in the next sync except adding the `.pyi` files. There is no Dependabot `pip` ecosystem
for this file (see Not doing).

**D3: Widen the fixup to `.pyi`, keep the sed, and fail closed.** The ticket's warning is correct:
an unfixed absolute import in a `.pyi` does not fail at runtime. The type checker just loses the
types without saying so. The experiment shows today's sed pattern already handles the `.pyi`
import shape, so the change is to the `find` only:

```bash
find out/python -name "*_pb2*.py" -o -name "*_pb2*.pyi" | xargs sed -i 's/^import \(.*_pb2\) as/from . import \1 as/'
```

The implementation may keep `-exec` rather than `xargs`. The point is matching both extensions.

After the fixup, a guard step fails the job in two cases:

- **Unfixed imports.** Any generated file still contains a line matching `^import [A-Za-z0-9_]+_pb2\b`.
  This catches a future generator that changes its import shape.
- **Missing stubs.** Any `*.py` module in `out/python` has no matching `*.pyi`. This catches a
  generator flag that was dropped or silently did nothing.

Both checks are cheap. Both turn a silent loss of type information into a red run on the dry run,
before anything reaches dp-python-lib.

**D4: Make the dry run show the stubs, and keep the output.** The step summary lists `.py` and
`.pyi` files, with separate counts. The expected counts are 10 and 10: five protos, each producing
`_pb2` and `_pb2_grpc`. The generated `out/python` tree is also uploaded as a workflow artifact,
on every run, using the `actions/upload-artifact` SHA already pinned in `release.yml`.

The upload is what makes the dry run useful for more than eyeballing. dp-python-lib can download
the exact stubs a release will deliver and confirm its code against them *before* the sync PR
exists. In the sequencing below, that is step 3's check on the preparation PR. On real runs, the
artifact is an audit record of what was synced. It needs no additional token permission.

**D5: `types-grpcio` is dp-python-lib's dependency, not ours.** Generation does not need it. It
matters only where the stubs are type-checked. It is still recorded here, and in
`python-stubs.md`, because without it mypy-protobuf's main advantage disappears and the generated
`_pb2_grpc.pyi` produces four errors of its own.

## Cross-repo sequencing

The constraint is that dp-python-lib's CI goes red on the first sync that carries `.pyi` files,
unless dp-python-lib has prepared for it. With its current config, that sync produces 10 errors,
listed in [The experiment](#the-experiment). Those errors can be fixed in advance, in forms that
also pass against today's untyped stubs:

- **The `overload-cannot-match` errors.** Adding `types-grpcio` and dropping the `grpc`
  `ignore_missing_imports` removes them. This is independent of the stubs.
- **The `None`-handling fixes.** These are valid against either set of stubs.
- **The enum `ValueType` annotations.** These resolve to `Any` under the current suppression, so
  they are harmless there.

Recommended order:

1. **dp-python-lib**: land a *preparation* PR. It adds `types-grpcio` to the `dev` extra, drops
   the `grpc` ignore and fixes the resulting `mldp_client.py` errors, and fixes the hand-written
   errors listed above. It must be verified locally against *both* the stubs committed today and
   mypy-protobuf stubs, and must pass under both. The mypy-protobuf stubs do not have to wait for
   dp-grpc. They can be generated locally with the D2 versions and flags, which is how the triage
   experiment produced them. Once step 3 has run, the dry-run artifact is the same thing.
2. **dp-grpc**: land this ticket's implementation PR. It adds the release gate described below.
3. **dp-grpc**: run the workflow by `workflow_dispatch` with `dry_run: true`, and download the
   `out/python` artifact (D4). Confirm dp-python-lib passes against it, as a check on step 1.
4. **dp-grpc**: the next `rel-*` tag syncs the stubs as usual. The sync PR arrives green.
5. **dp-python-lib**: land a *follow-up* PR. It removes the suppression (`exclude` and the
   `follow_imports = "skip"` override), types `_stub`, adds `py.typed`, and confirms that the
   `.pyi` files and `py.typed` are in the wheel.

The hard constraint is narrower than the numbering: step 1 must land before any `rel-*` tag is
pushed on a commit that contains step 2. Steps 1 and 2 have no dependency on each other. Putting
step 1 first removes the hazard outright, rather than relying on nobody tagging in between.

That gap is real, not theoretical. When this plan was written, `doc/release-notes/NEXT.md`
already held #137 and #153, and that release was waiting to be cut. If step 2 merges before the
release and step 1 has not landed, that release's sync is the one that breaks.

**Release gate.** The implementation PR adds an item to the "Cutting the release" checklist in
`NEXT.md`: *if this release includes #158, confirm dp-python-lib's preparation PR has merged
before pushing the tag.* The checklist is the one document a release cutter is certain to read,
so this covers the case where the order above is not followed.

Step 5 cannot come earlier. With untyped stubs, removing the suppression produces the 386 errors
again.

**Fallback.** If a sync reaches dp-python-lib before step 1, a maintainer pushes the step-1 fixes
onto the bot's `grpc-sync-*` branch before merging. It works, but it mixes hand-written changes
into an automated sync PR, which is why it is the fallback.

**Why not deliver the stubs early?** A non-dry `workflow_dispatch` from `main` would open a sync PR
straight away. It would also put stubs generated from *unreleased* protos into dp-python-lib,
which breaks the convention that dp-python-lib version *N* carries the stubs from dp-grpc `rel-N`.
The dry-run artifact gives dp-python-lib the same stubs to prepare against without that cost.

## Blast radius

- **dp-python-lib CI.** It goes red on the first stub-bearing sync unless step 1 has landed. This
  is the one real hazard, and the sequencing above addresses it.
- **dp-python-lib runtime users.** No change. Every `.py` file is byte-identical, and the `.pyi`
  files are inert at runtime. The wheel gets about 14.7k lines of `.pyi`. Once step 5 adds
  `py.typed`, downstream users type-checking against dp-python-lib see the protobuf types too.
- **dp-python-lib's cookbook snippet checker.** It type-checks doc examples against the package,
  so it becomes much stricter once the stubs are live. It may turn up doc errors that were hidden
  by `Any` until now. That is a benefit, but step 5 should expect it.
- **dp-grpc releases.** None of the Java jar, the proto tarball, `SHA256SUMS`, or signing is
  touched. The only change to the stub workflow's behavior is the two new guard failure modes,
  and those are intended.
- **dp-service.** None.
- **Release notes.** User-visible to Python users, because dp-python-lib ships the stubs. It gets
  a ticket section in `doc/release-notes/NEXT.md`. Per convention, the section says nothing about
  what else the release contains.

## Work breakdown

One dp-grpc PR:

1. **Pin files.** Add `tools/python-stubs-requirements.in` with the D2 pins, and the
   hash-locked `tools/python-stubs-requirements.txt` compiled from it. The `.in` file gets a
   header comment covering three points. First, `grpcio-tools` sets dp-python-lib's runtime
   minimums, so a bump needs a matching dp-python-lib change, including its `[codegen]` extra.
   Second, the file is deliberately not Dependabot-managed. Third, the exact `pip-compile`
   command that regenerates the `.txt`.
2. **Install step.** In `generate-python-stubs.yml`, install with
   `pip install --require-hashes -r tools/python-stubs-requirements.txt`.
3. **Generation step.** Add `--mypy_out=out/python --mypy_grpc_out=out/python`, widen the fixup
   `find` to `.pyi` (D3), and add the guard step after the fixup (D3).
4. **Dry-run output.** List `.py` and `.pyi` in the summary with separate counts (D4), and upload
   `out/python` as an artifact on every run, pinned to `release.yml`'s `upload-artifact` SHA.
5. **`doc/cookbook/python-stubs.md`.** Update "How Python stubs are published" to mention the
   `.pyi` files. Update "Generating stubs yourself" to install from the hash-locked requirements
   file and use the two new flags, and "The import fixup" to use the widened glob. Add a short
   "Type checking" section covering three points:
   - Which module carries what: `_pb2.pyi` holds the messages and `_pb2_grpc.pyi` the service
     stubs.
   - Stub calls are typed only with `types-grpcio` installed.
   - A stub held in an `Any`-typed variable gets no checking.
6. **Release notes.** Add a `doc/release-notes/NEXT.md` section and its Contents entry, and add
   the release gate item to its "Cutting the release" checklist (see
   [Cross-repo sequencing](#cross-repo-sequencing)).
7. **Verify on the PR.** Dispatch the workflow from the PR branch with `dry_run: true`, then:
   - The summary shows 10 `.py` and 10 `.pyi` files.
   - The artifact downloads.
   - The `.py` files are byte-identical to the stubs committed in dp-python-lib.
   - Every `.pyi` import between generated modules is relative.

   Separately, check that the guard fails closed by running it locally on a copy with one import
   left unfixed.

The ticket's acceptance criteria are met by step 7 together with the triage run above. The run
already showed zero `name-defined` / `attr-defined` errors against dp-python-lib `main` with the
mypy-protobuf stubs. Step 7 re-confirms it on the workflow's own output.

The dp-python-lib steps (1 and 5 under [Cross-repo sequencing](#cross-repo-sequencing)) belong to
that repo's tickets. They are not part of this PR.

## dp-python-lib handoff

These are for a dp-python-lib ticket, or for reopening the scope of #30. They are listed here so
that nothing falls between the two repos:

- **Preparation, before the next stub-bearing sync:**
  - add `types-grpcio` to the `dev` extra;
  - drop the `grpc` `ignore_missing_imports` override, and correct its comment, which says there
    is no stub package;
  - fix `mldp_client.py` lines 92 and 108 (`None` assigned to `grpc.Channel`);
  - fix `machine_config_client.py` lines 1081–1082 and 1281–1282 (unchecked `Optional`);
  - fix `query_conversions.py` line 33 (unguarded `EnumDescriptor | None`);
  - fix `export_client.py` lines 33 and 193 (enum `ValueType`);
  - add `mypy-protobuf` to the `[codegen]` extra, which today lists only `grpcio-tools>=1.84.0`.
    Without it, anyone regenerating stubs through dp-python-lib's own toolchain gets `.py`
    files with no `.pyi`. The extra is a second record of the generator requirement, so either
    match its versions to dp-grpc's `tools/python-stubs-requirements.in`, or have its comment
    point there as the authority.

  Line numbers are as of dp-python-lib `origin/main` on 2026-09-24.
- **After the sync:**
  - remove both halves of the `dp_python_lib.grpc` suppression, and update the comment in
    `ci.yml` that cites this ticket;
  - type `_stub`, for example by making `ServiceApiClientBase` generic in its stub type, or with a
    per-subclass annotation;
  - add `py.typed`;
  - confirm that the `.pyi` files and `py.typed` land in the wheel. Recent setuptools includes
    both by default, but this should be verified with the existing wheel-install CI step rather
    than assumed.

## Not doing

- **Also emitting `--pyi_out`.** mypy-protobuf's `_pb2.pyi` covers the same ground, and both
  flags would write the same files.
- **Type-checking the generated stubs in dp-grpc CI.** The stubs are consumed and checked in
  dp-python-lib. Checking them here would need `types-grpcio` and a mypy setup that duplicates
  that repo's. The D3 guard covers the one failure that only this repo can see, a silent import
  miss. #142's reasoning for leaving stub generation out of PR CI still holds.
- **A Dependabot `pip` ecosystem for the pin file.** A generator bump moves dp-python-lib's
  runtime minimums, so it is a coordinated decision, not a routine one. #142 took the same line on
  a Maven ecosystem.
- **Delivering stubs before a release** by a non-dry dispatch. See
  [Cross-repo sequencing](#cross-repo-sequencing).
- **Adding a top-level `permissions` block to `generate-python-stubs.yml`.** The workflow has
  none today, so its `GITHUB_TOKEN` gets the repository default. Tightening that is worthwhile
  hardening, in line with the #137 convention, but it is unrelated to stub typing. It belongs in
  its own small ticket.
