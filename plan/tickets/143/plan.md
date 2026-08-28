# Plan: Remove `ValueStatus` from `DataValue` (issue #143)

- **Ticket**: [osprey-dcs/dp-grpc#143](https://github.com/osprey-dcs/dp-grpc/issues/143) —
  the authoritative scope statement; this plan records the design rationale and work breakdown.
- **Parent epic**: [osprey-dcs/data-platform#83](https://github.com/osprey-dcs/data-platform/issues/83)
- **Companion ticket**: [#132](https://github.com/osprey-dcs/dp-grpc/issues/132) —
  datasets/annotations modernization, same breaking release (merged as
  [#145](https://github.com/osprey-dcs/dp-grpc/pull/145) on 2026-08-27)
- **Replaces**: [#121](https://github.com/osprey-dcs/dp-grpc/issues/121) — the Sample Status
  API, which is the designated replacement mechanism
- **Status**: triaged 2026-08-28; implementation not started
- **Prior verification**: the dp-service blast radius below was verified on 2026-08-27 during
  #132 triage and is recorded in [`../132/plan.md`](../132/plan.md) D13 and
  [`../132/dp-service-handoff.md`](../132/dp-service-handoff.md)

`DataValue.ValueStatus` embeds acquisition-time alarm/status information — EPICS-style
severity, status code, and message — per sample, inside the value itself. The Sample Status
API supersedes it. This ticket removes the mechanism from the protos while leaving `DataValue`
itself in place, since `DataValue` remains the representation for tabular query results and
the heterogeneous escape hatch in annotation Calculations.

The diff is small. Almost all of the work in this plan is getting the reservation right and
rewording four passages of prose that currently describe `valueStatus` as deprecated-but-present.

## Contents

1. [Settled decisions and rationale](#settled-decisions-and-rationale)
2. [Proto design](#proto-design)
3. [Blast radius](#blast-radius)
4. [Work breakdown](#work-breakdown)
5. [Follow-ons](#follow-ons)

## Settled decisions and rationale

**D1 — Remove rather than deprecate further.** The field has carried a deprecation note since
the Sample Status API landed under #121, and the note already names the replacement. Leaving it
in place indefinitely means new producers keep finding it and populating it, which produces
status information that no server path reads and no query can select on. The removal is what
actually closes the mechanism off. It ships in the same release as #132 so the breakage lands
once.

**D2 — Reserve the field number and the field name; do not reserve the nested type name.**
`reserved 15;` prevents a future field from occupying tag 15, and `reserved "valueStatus";`
prevents a future field from taking the name back. Both matter, and for different reasons:

- The *number* is the wire contract. Archived `DataValue` blobs containing field 15 still exist
  and still parse under the new schema — the field is simply unknown and invisible to the API.
  If a future field were assigned tag 15, those archived bytes would decode into it. A
  length-delimited submessage is not self-describing on the wire, so this is a silent
  misinterpretation, not a parse error. This is exactly the failure mode found in review during
  #132, where inserting a criterion mid-`oneof` shifted `TextCriterion`'s tag and would have let
  a stale client's full-text search decode as an exact-name match. The lesson carried forward:
  a breaking release makes stale *source* fail loudly at compile time, and does nothing at all
  to stop stale *bytes* — whether from an old client or from the archive — being misread.
- The *name* matters for JSON/text-format encodings and for anyone reading the proto: reusing
  `valueStatus` for something structurally different would make old JSON payloads and old
  documentation quietly wrong.

The nested `ValueStatus` message type and its `StatusCode` / `Severity` enums need no
reservation. `reserved` in protobuf reserves field numbers and field names within a message,
not nested type names, and a nested type carries no wire identity of its own — it is reachable
only through the field being removed. Deleting them outright is correct. This is the first use
of `reserved` in these protos; the block is commented so the reason survives the next reader.

**D3 — Accept that historical embedded status becomes unreachable.** Archived data containing
field 15 keeps the bytes, but nothing in the API can surface them after the removal. This is
accepted rather than mitigated: the information was already effectively unqueryable — no
server-side selection on `valueStatus` ever existed, and the only way to see it was to fetch
buckets and inspect values client-side. No migration path is offered and none is required for
the archive to keep functioning. Producers that want this information retained going forward
write it through `saveSampleStatuses()`, where it is queryable and correctable.

**D4 — No compatibility shim, no transitional accessor.** There is no interim release that
keeps the field with a `[deprecated = true]` annotation and no client-side helper that reads
tag 15 back out of unknown fields. Both were considered and rejected: the API is beta, only the
latest release is supported, and a shim would preserve exactly the pattern the ticket exists to
close off. Callers that need the old data have the raw bytes and the field number, which is
enough to write a one-off reader if a real need appears.

**D5 — Separate PR from #132, same release.** #132 is merged; this lands on its own branch
against `main` and rides the same version bump. Keeping the diffs apart gives the removal its
own reviewable change and its own release-notes line, which matters for a breaking change whose
migration guidance is entirely different from #132's.

**D6 — Docs describe it as removed, not deprecated.** Four passages currently say
"deprecated" and describe a field that will no longer exist. All four are reworded in the same
PR as the proto change, so the docs never describe a field the protos do not have. The
`DataValue` comment keeps its pointer to the Sample Status API — that pointer becomes *more*
important after removal, not less, because it is the only place a reader coming from an older
version learns where the mechanism went.

## Proto design

In `src/main/proto/common.proto`, message `DataValue` (currently at line ~594):

Delete the `valueStatus` field declaration and its comment block:

```proto
  /*
   * Status of Value
   *
   * Represents the condition of the value or associated hardware and software at
   * acquisition time.
   */
  ValueStatus valueStatus = 15;
```

Delete the entire nested `message ValueStatus { ... }`, including its `StatusCode` and
`Severity` enums and their comments.

In their place, inside `DataValue`, after the `oneof value` block:

```proto
  /*
   * Field 15 held 'valueStatus' (nested message ValueStatus), removed in this release.
   * Acquisition-time alarm and status information is expressed through the Sample Status
   * API in annotation.proto instead; see the message comment above.
   *
   * The number and name are reserved permanently.  Archived DataValue records written
   * before the removal still contain field 15; those bytes now decode as an unknown field.
   * Assigning 15 to any future field would cause that archived data to be silently
   * misread as the new field rather than rejected.
   */
  reserved 15;
  reserved "valueStatus";
```

The `oneof value` arms (tags 1–13) are untouched. Tag 14 was never assigned and stays free.

The `DataValue` message comment is rewritten. Dropped: the opening sentence pairing "a data
field 'value' and a status field 'valueStatus'", the paragraph describing the `valueStatus`
structure, and the clause in the deprecation note explaining why `ValueStatus` is unsuitable
for post-ingestion cleaning tools. Kept: the `oneof`-as-union description, the
ingestion-deprecation note about per-sample allocation, and the pointer to the Sample Status
API as where acquisition status now lives.

Nothing else in the protos references `ValueStatus`. `DataValue` itself is referenced by
`Structure.Field.value`, `Array.dataValues`, `DataColumn.dataValues`,
`ingestion_stream.proto`, and the Query V2 `ColumnTable` — all unaffected, since none of them
touch field 15.

`doc/proposed/common.proto.cka` also contains a `ValueStatus` message. It is a design document,
not a compiled source, and is left alone.

## Blast radius

Verified 2026-08-27 during #132 triage; see [`../132/dp-service-handoff.md`](../132/dp-service-handoff.md)
for the detail. Re-confirm against dp-service `main` before opening the PR there, since that
verification predates this work by a day and dp-service moves independently.

| Consumer | Impact |
|---|---|
| dp-grpc protos | `common.proto` only — one field, one nested message, one comment |
| dp-service `src/main` | `IngestionClient.java` only, a client-side helper that builds `DataValue`s; its `valuesStatus` parameter support is deleted. No server query, export, or storage path interprets the field — `DataColumn` blobs are handled opaquely |
| dp-service tests | **Four files; the removal PR does not build until they are updated.** `QueryDataValueStatusIT.java` (179 lines, 15 references) is a dedicated ingest/query round-trip test for `ValueStatus` and is **deleted outright** rather than adapted. `IngestionClientTest.java` and `IngestionTestBase.java` reference it in test-data construction. `QueryTestBase.java` is a comment reference only |
| Stored data | Archived blobs with field 15 still parse; the field becomes unknown and invisible. No migration |
| dp-python-lib | Stub regeneration only |
| dp-desktop-app | Unknown; check alongside the #132 check in that repo's step |

## Work breakdown

Steps 1–4 are one PR against `main`.

1. Proto edit: `common.proto` `DataValue` — delete the field, delete the nested message and its
   two enums, add the commented `reserved 15;` / `reserved "valueStatus";` block, rewrite the
   message comment per [Proto design](#proto-design).
2. `mvn compile`; confirm the generated `DataValue` no longer exposes `getValueStatus()` /
   `hasValueStatus()` / the `ValueStatus` nested class, and that nothing else in the generated
   tree fails to build.
3. Docs — reword all four passages from deprecated to removed, in the same PR:
   - `src/main/proto/common.proto` — the `DataValue` message comment (step 1).
   - `README.md`, Sample Status API introduction — currently "the designated replacement for
     the deprecated DataValue ValueStatus mechanism". Becomes the replacement for a mechanism
     that was removed, naming the release.
   - `doc/cookbook/query.md`, "Also worth knowing" — currently states `valueStatus` is
     deprecated, still appears on archived `DataValue`s, and can be filtered client-side. The
     first two clauses change; the "no server-side selection on it" point disappears with the
     field. Say plainly that archived records may still carry the bytes but the API does not
     surface them.
   - `doc/cookbook/sample-status.md`, closing bullet — same rewording, and this is the right
     place for the one-line migration pointer, since a reader here is already holding the
     replacement API.
4. `python3 tools/check-cookbook-snippets.py` — no snippet is expected to reference
   `valueStatus`, so this should be a no-op gate, but run it: it is the check that catches a
   snippet built on a type that no longer exists.
5. Release notes: add the breaking-change entry and its migration guidance. Text is already
   staged in [`../132/release-notes.md`](../132/release-notes.md) under "Also in this release";
   promote it to a first-class breaking-change entry rather than an aside, since it is a
   removal with its own migration story. Migration line: producers that supplied `ValueStatus`
   ingest the same information via `saveSampleStatuses()` in an appropriate status domain — for
   example an EPICS domain whose contract carries severity and status codes — which
   additionally permits post-ingestion correction that the embedded mechanism never could.
6. dp-service: separate ticket and PR in that repo — delete `IngestionClient.java`'s
   `valuesStatus` support, update the two test-support files, delete
   `QueryDataValueStatusIT.java`. This blocks dp-service's upgrade to the new dp-grpc version,
   so file it when this PR merges rather than after the release.
7. dp-python-lib: stub regeneration (tracked in that repo, alongside the #132 regeneration —
   one pass covers both).

## Follow-ons

- **A status domain contract for EPICS acquisition status.** The migration guidance tells
  producers to use "an appropriate status domain", which is deliberately unspecified — domains
  are used by naming them and there is no registration step. If EPICS producers converge on a
  domain, writing that contract down is worth a ticket. Related: the sample status domain
  registry (`saveSampleStatusDomain` / `querySampleStatusDomains`) is still a stub under #121.
- **Recovering historical embedded status.** Out of scope per D3, and no need is known. If one
  appears, the archived bytes and field number 15 are sufficient to write a one-off reader
  against the raw blobs; the reservation comment is what preserves the information needed to
  do so.
