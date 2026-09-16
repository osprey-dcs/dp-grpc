# dp-grpc 1.16.0 Release Notes

Changes since rel-1.15.0.  This repo publishes the MLDP gRPC API definition and the JAR of
generated Java stubs; the server-side implementation of everything below ships in dp-service
1.16.0, whose release notes cover the behavior each change produces.

**1.16.0 is a breaking release.** Client code written against 1.15.0 stubs will not compile
against these, and two changes alter query results without raising an error. Read
[Upgrading from 1.15.0](#upgrading-from-1150) before rebuilding.

## Contents

- [Upgrading from 1.15.0](#upgrading-from-1150)
- [Sample Status API (dp-grpc #121)](#sample-status-api-dp-grpc-issue-121)
- [Modernized DataSet and Annotation APIs (dp-grpc #132)](#modernized-dataset-and-annotation-apis-dp-grpc-issue-132)
- [`DataValue.ValueStatus` removed (dp-grpc #143)](#api-change-datavaluevaluestatus-removed-dp-grpc-issue-143)
- [Empty criteria list means match-all (dp-service #245)](#behavior-change-an-empty-criteria-list-matches-all-records-dp-service-issue-245)
- [ConfigurationSelector empty-criteria reject (dp-grpc #149)](#configurationselector-rejects-an-empty-criteria-list-dp-grpc-issue-149)
- [Python clients](#python-clients)
- [Documentation](#documentation)
- [Build and release infrastructure (dp-grpc #133)](#build-and-release-infrastructure-dp-grpc-issue-133)

## Upgrading from 1.15.0

The compile errors are the easy half — the compiler finds every one of them. In order:

1. **Rebuild against the new stubs and fix compile errors.** `SaveDataSetRequest` no longer
   embeds a `DataSet`, `Annotation` moved to the top level of `annotation.proto`,
   `Annotation.comment` is now `description`, `CalculationsDataFrame` carries a `common.DataFrame`,
   and `DataValue.ValueStatus` is gone. These account for nearly all of them.
2. **Replace reads of embedded content in `queryAnnotations` results.** `Annotation.dataSets` and
   the embedded `Calculations` are removed; fetch by id with `queryDataSets` (repeated
   `IdCriterion`) and `getCalculations`.
3. **Audit every multi-criterion query.** Criteria now combine with AND across the board. Two
   `TagsCriterion` entries used to match *either* tag and now match *both*. This change is
   **silent** — no error, a different result set.
4. **Add paging loops wherever a result was assumed complete.** An unset `limit` now means a
   server-configured default page size, not an unbounded result, on every paged
   `DpAnnotationService` query — `queryPvMetadata` in particular was previously unbounded.
5. **Check anywhere an empty criteria list was relied on to fail.** It now matches all records
   and returns the first page of the collection instead of being rejected.
6. **Guard conditionally-built `ConfigurationSelector`s.** An empty one is rejected, not ignored.

## Sample Status API (dp-grpc Issue #121)

The Sample Status API assigns status codes to individual PV samples at specific timestamps,
supporting data cleaning, quality assessment, and MLOps workflows — an ML model labeling samples
as anomalous, a rule engine flagging out-of-range values, an operator marking a handful of
suspect points. It is also the designated replacement for the `DataValue.ValueStatus` mechanism
removed in this same release (#143 below).

Reference: [Sample Status API](../../README.md#sample-status-api).
Worked examples: [Sample status cookbook](../cookbook/sample-status.md).

### The model

A status is keyed by **(pvName, timestamp, domain, layer)**. A **domain** names the contract
defining the semantics of the int32 status codes (`data_quality`, `ml_anomaly`); following the
`EnumColumn` precedent, the (domain, code) mapping is a contract between producers and consumers
and is neither validated nor interpreted by the MLDP. A **layer** names the producer stream
(`ml_model_v1`, `rule_engine`, `operator_override`), so several independent interpretations of the
same samples can coexist within one domain.

Sparse labeling is first-class: a save supplies only the timestamps being labeled, and the absence
of a status means **"no assertion"** — there is no implicit default. Statuses are matched to data
samples by exact (pvName, timestamp) equality at **nanosecond precision**, so producers must label
using timestamps taken from query results or exact `SamplingClock` arithmetic; a recomputed or
rounded timestamp silently fails to match.

Three new messages in [`common.proto`](../../src/main/proto/common.proto), paralleling the
existing time-series model:

| Message | Parallels | Role |
|---|---|---|
| `SampleStatusColumn` | `DataColumn` | One PV's int32 status codes, plus optional `confidence` / `reasons` parallel arrays |
| `SampleStatusFrame` | `DataFrame` | The unit of save: one (domain, layer), one `DataTimestamps` axis, one column per PV |
| `SampleStatusBucket` | `DataBucket` | The unit of query results, with last-writer `source` / `modifiedBy` / `updatedTime` |

### New methods

Four methods on `DpAnnotationService`, in
[`annotation.proto`](../../src/main/proto/annotation.proto):

- **`saveSampleStatuses`** — batch upsert. Upsert is per individual status and replaces **in
  full**: re-saving with an empty `confidence` or `reasons` list clears previously stored values.
  Statuses at other timestamps are untouched, so cleanly re-labeling a range means delete, then
  save.
- **`querySampleStatuses`** / **`querySampleStatusesStream`** — query over a `TimeRange`, optionally
  filtered by `pvNames`, `domains`, and `layers` (ANDed across fields, ORed within one; an empty
  list matches all). Bucket selection is the overlap test and **boundary buckets are returned
  whole**, matching `queryBuckets`. The streaming form follows the `queryBucketsStream` model:
  fire-and-consume, `pageToken` must be empty, `nextPageToken` always empty.
- **`deleteSampleStatuses`** — exact at the sample axis over `[beginTime, endTime)` for one
  required (domain, layer), unlike query. An empty `pvNames` list is a deliberate wildcard over
  all PVs.

Two domain-registry methods — `saveSampleStatusDomain` and `querySampleStatusDomains` — are
defined as deferred stubs per the standard CRUD pattern. Calling either returns an error response;
the registry record shape is deferred to the release that implements them.

### `QuerySpec.sampleStatusSelector` on the V2 query methods

`QuerySpec` field 4, reserved in 1.15.0 pending this API, is now `SampleStatusSelector` in
[`query.proto`](../../src/main/proto/query.proto). A selector names a required `domain`, optional
`layers` (empty = all), optional `statusCodes` (empty = any code), and a required `mode`:

- **`MODE_INCLUDE_MATCHING`** — return only samples carrying a matching status. Unlabeled samples
  are excluded by definition. This is "return only the anomalies".
- **`MODE_EXCLUDE_MATCHING`** — drop samples carrying a matching status. Unlabeled samples pass by
  definition. This is "drop the bad data".

The two modes cover both canonical cases without a separate unlabeled-handling flag. An empty
`statusCodes` list matches any code, so "labeled at all" is expressible without enumerating a
domain's codes — which the MLDP itself does not know — and keeps working when a producer adds new
ones.

**Supported by the sample-oriented methods only.** `querySamples` / `querySamplesStream` accept it,
where a filtered-out sample becomes a missing value (unset `DataValue` oneof) at its (PV, timestamp)
position in the `ColumnTable`, and timestamps at which every selected PV is filtered out drop from
the result entirely. `queryBuckets` / `queryBucketsStream` **reject a request carrying it** with an
`ExceptionalResult`: a storage bucket is returned whole and cannot represent per-sample filtering.
Bucket-granularity status selection may be considered in a future release.

When `configurationSelector` is also set, the two compose by **intersection**: activation intervals
restrict the time axis first, then status filtering applies to the samples that survive. A status
attached to a sample outside the activation intervals has no effect, because that sample is already
gone.

## Modernized DataSet and Annotation APIs (dp-grpc Issue #132)

The DataSet and Annotation APIs are the oldest generation of `DpAnnotationService`, and 1.16.0
brings them to the CRUD conventions established by the PV metadata, machine configuration, and
sample status APIs. **Method names are unchanged, but message shapes and query semantics changed
incompatibly.**

Reference: [Data Set API](../../README.md#data-set-api),
[Annotation API](../../README.md#annotation-api).
Worked examples: [Data sets, annotations, export cookbook](../cookbook/datasets-and-annotations.md).
Design record: [`plan/tickets/132/plan.md`](../../plan/tickets/132/plan.md).

### API CHANGE: message shapes

- **`SaveDataSetRequest` is flat.** It no longer embeds a `DataSet`; the client-settable fields —
  `id`, `name`, `ownerId`, `description`, `dataBlocks`, `tags`, `attributes`, `modifiedBy` — are on
  the request itself. This is the house rule for `Save*Request` messages: the domain message
  carries server-set audit fields that must not be accepted as input.
- **`Annotation` is a top-level message.** It was nested as
  `QueryAnnotationsResponse.AnnotationsResult.Annotation`.
- **`Annotation.comment` is renamed `description`**, matching every other entity.
- **`DataSet` and `Annotation` gain audit fields** — server-set `createdTime` / `updatedTime` and a
  last-writer `modifiedBy`. `DataSet` additionally gains `tags` and `attributes`.
- **`DataSet.id` is the primary key.** Names are not unique.
- **`CalculationsDataFrame` is now `name` + `common.DataFrame`**, replacing the previous
  `DataTimestamps` + `repeated DataColumn` pair. Calculation output therefore gets the full set of
  typed scalar / array / image / struct / serialized column types and per-column `ColumnMetadata`.
  Frame names must be distinct within a `Calculations` object, since they are an addressing key.

### API CHANGE: query results carry references, not content

`queryAnnotations` results now carry `dataSetIds` and `calculationsId` only. The denormalized
`repeated DataSet dataSets` field and the embedded `Calculations` content are **removed**. Fetch
DataSet content with a single `queryDataSets` call using the now-`repeated` `IdCriterion`, and
Calculations content with `getCalculations` or `getAnnotation`.

This removes an N+1 fan-out on the server: the previous implementation issued one dataset lookup
per dataset id per annotation, serially and unbatched, then embedded every frame, column, and value
into each returned annotation.

### BEHAVIOR CHANGE: criteria combine with AND — read this one

All query criteria are now combined with **AND**, values within a single criterion with **OR**,
matching the convention used everywhere else in the API. Previously the server used a two-bucket
scheme that ORed some criteria together, with different bucket assignments per method.

The consequential case: **two `TagsCriterion` entries previously matched "either tag" and now match
"both tags"**. This is silent — no error is raised, the result set simply differs. Review any query
supplying multiple criteria. To OR two tag values, list them in one criterion.

`TextCriterion` is also now documented as a full-text search over a record's indexed text fields
rather than a per-field match; it is a collection-level text index search and cannot be scoped to
named fields at query time. Use the new `NameCriterion` to restrict a match to the name.

### Pagination and ordering

- `queryDataSets` and `queryAnnotations` are **now paged** — `limit` / `pageToken` on the request,
  `nextPageToken` on the result. They previously had no paging fields and returned every match in
  one message.
- Across every paged `DpAnnotationService` query, an unset or zero `limit` means a
  **server-configured default page size, not an unbounded result**. This changes `queryPvMetadata`,
  which was previously unbounded: a caller that omitted `limit` and read the whole result in one
  response now receives one page and must follow `nextPageToken`.
- A malformed `pageToken` is **rejected** with an `ExceptionalResult` rather than silently
  restarting at page one.
- **Result ordering is now part of the API contract** for every paged query: `id` ascending for
  DataSets and Annotations, `pvName` for PV metadata, `configurationName` for configurations,
  `startTime` then `configurationName` then id for configuration activations, and `pvName` then
  domain then layer then bucket start time for sample statuses.

### New methods

- **`getDataSet`** / **`deleteDataSet`** — single-record lookup and delete by id.
- **`getAnnotation`** / **`deleteAnnotation`** — single-record lookup and delete by id.
  `getAnnotation` returns Calculations content inline.
- **`getCalculations`** — retrieve a Calculations object by `calculationsId` without loading the
  owning Annotation's descriptive payload.
- **`patchDataSet`** / **`patchAnnotation`** — reserved placeholders per the standard CRUD pattern.
  Not implemented; calling either returns an error response.

There is deliberately no `bulkSave*` for either entity, and no `saveCalculations`,
`deleteCalculations`, or `queryCalculations` — Calculations are owned by an Annotation, written
through `saveAnnotation`, deleted with their Annotation, and discovered through `queryAnnotations`.
The proto comments carry the reasoning in each case.

**Referential rules.** `deleteDataSet` is **rejected** while any Annotation references the DataSet
in `dataSetIds`. `deleteAnnotation` is **not** blocked by incoming references: `annotationIds` and
column-provenance links are soft associations and may dangle after a delete.

### New: column-level provenance

`common.ColumnProvenance` gains a structured `repeated ColumnSource derivedFrom` list naming the
columns a derived column was computed from. Each `ColumnSource` is a `oneof origin` identifying
either an archived PV by name or a Calculations column (`calculationsId` + `frameName` +
`columnName`), plus an optional `TimeRange` for the source interval consumed — which matters for
aggregations, whose source interval is not implied by the derived column's own timestamps.

The oneof is named `origin` rather than `source` because `ColumnProvenance` already has a string
field named `source`; a nested oneof of the same name would produce a confusing
`getSource()` / `getOriginCase()` pair in the generated Java.

This is purely additive: the existing `source` / `process` fields are unchanged, and an absent
`ColumnMetadata`, an absent `ColumnProvenance`, and an empty `derivedFrom` list all encode to zero
bytes. Because `ColumnProvenance` rides inside the `ColumnMetadata` that every column message type
carries, one mechanism serves both Annotation Calculations columns and ingestion-side derived data.
Links are stored as supplied and **never validated** — they may dangle, and readers must tolerate
that.

Document-level provenance remains the coarser level: an Annotation's `dataSetIds` and
`annotationIds`.

### Export

- **`ExportDataRequest` gains `repeated DataBlock dataBlocks`** — an inline, ad-hoc data
  specification treated server-side as a transient dataset, nothing persisted.
- At least one of `dataSetId`, `dataBlocks`, or `calculationsSpec` is now required; sources may be
  combined in one export. The stale "Required" comment on `dataSetId` is corrected.
- **Documented restriction:** the tabular formats (CSV, XLSX) can only represent scalar columns.
  Data containing array, image, or struct columns exports to HDF5 only. This was already true for
  DataSets and now also applies to the typed Calculations columns.

## API CHANGE: `DataValue.ValueStatus` removed (dp-grpc Issue #143)

`DataValue.ValueStatus` and its nested `StatusCode` and `Severity` enums are removed. The Sample
Status API above is the designated replacement: acquisition-time alarm and status information is
captured in a status domain, keyed by (pvName, timestamp, domain, layer), and can be assigned or
updated post-ingestion by automated cleaning tools.

Design record: [`plan/tickets/143/plan.md`](../../plan/tickets/143/plan.md).

The field carried a deprecation note from the moment the Sample Status API landed. Removing it is
what actually closes the mechanism off — while it was present, new producers kept finding it and
populating it, producing status information that no server path read and no query could select on.
It ships in the same release as #132 so the breakage lands once.

**Field 15 and the name `valueStatus` are reserved permanently.** This is the first use of
`reserved` in these protos, and both halves matter:

- The **number** is the wire contract. Archived `DataValue` records written before the removal
  still contain field 15 and still parse — the bytes now decode as an unknown field, invisible to
  the API. Assigning 15 to a future field would cause that archived data to be silently misread as
  the new field rather than rejected, since a length-delimited submessage is not self-describing on
  the wire. A breaking release makes stale *source* fail loudly at compile time and does nothing at
  all to stop stale *bytes* — from an old client or from the archive — being misread.
- The **name** matters for JSON and text-format encodings, and for anyone reading the proto:
  reusing `valueStatus` for something structurally different would make old payloads and old
  documentation quietly wrong.

No migration is required for the archive to keep functioning, and none is offered. Historical
embedded status becomes unreachable through the API; it was already effectively unqueryable, since
no server-side selection on `valueStatus` ever existed. There is no compatibility shim and no
transitional accessor — a shim would preserve exactly the pattern this change exists to close off.
Producers that need this information retained going forward write it through `saveSampleStatuses`,
where it is queryable and correctable.

## BEHAVIOR CHANGE: an empty criteria list matches all records (dp-service Issue #245)

`queryPvMetadata`, `queryConfigurations`, and `queryConfigurationActivations` previously
**rejected** an empty `criteria` list, and no match-all criterion existed, so "list everything" was
unaskable. An empty list is now the **browse-all entry point**: no criteria means no filtering, so
every record is eligible, subject to the pagination bound. A supplied criterion must still be
well-formed.

The proto comments documented the rejection the server no longer performs, which is worse than
saying nothing. This change tracks dp-service #245, which removed the rejection server-side;
there is no dp-grpc issue behind it.

These comments also now state that an unset or zero `limit` means a **server-configured default
page size, not an unbounded result**, which they previously left unsaid. That was harmless while
empty criteria were rejected outright and actively wrong afterwards, since an unset `limit` on
`queryPvMetadata` used to mean "return everything" with an always-blank `nextPageToken`. The
default is documented as **unconditional**: it does not depend on whether criteria were supplied,
so removing the last criterion from a request does not change its page size. Follow
`nextPageToken` to retrieve all matching records.

The protos deliberately do not name the concrete default. Pinning a literal into a shipped
contract falsifies it the moment the server's value changes, and that value is expected to become
configurable — consult your deployment rather than the proto for the current number.

`queryDataSets` and `queryAnnotations` changed the same way, as part of #132 above.

Comment-only change: no wire format or generated Java API change.

## `ConfigurationSelector` rejects an empty criteria list (dp-grpc Issue #149)

`query.proto` documented an empty `ConfigurationSelector.criteria` list as matching nothing and
returning an empty result. The server does the opposite: it **rejects**, deliberately and pinned by
test. The comment was what was wrong — match-nothing is the worst of the three defensible
semantics, since a client that forgot to add criteria gets a plausible-looking empty result instead
of an error.

`ConfigurationSelector`'s comment now leads with the actionable instruction: **to query the full
`TimeRange` unconditionally, omit the selector entirely.** Guard any code that builds one
conditionally, so that dropping the last criterion drops the whole selector rather than leaving an
empty one behind.

This is the opposite of the dp-service #245 rule above, and the comment now says why, so the next
reader of both files does not file the ticket in reverse.

The #245 endpoints are browse-all list queries whose criteria list is the whole request, so empty
has to mean something. `ConfigurationSelector` is an optional restriction on a query whose subject
is already chosen by `pvSelector`, so matching everything would be a no-op indistinguishable from
omitting the field — which makes an empty list far more likely to be a half-built request than an
intent.

In the same change, `PvSelector.MetadataQuery` now documents its own empty-criteria behavior, which
is **match-all** and was previously unstated. Two selectors on one `QuerySpec` with opposite empty
semantics is exactly the kind of thing that has to be written down. It also differs from the other
two arms of that oneof, which reject their empty forms. Prefer stating an all-PV query explicitly
as a `pvNamePattern` of `".*"`, which is visible in the request.

Comment-only change: no wire format or generated Java API change.

## Python clients

The breaking changes above are breaking for Python callers too. These protos are the source of the
Python stubs published by
**[dp-python-lib](https://github.com/osprey-dcs/dp-python-lib)**: a release tag regenerates them
and opens a PR against that repo, and that repo is then tagged to match, so **`dp-python-lib`
1.16.0 carries the stubs from dp-grpc `rel-1.16.0`**. Upgrade that dependency to pick up the Sample
Status API and the reshaped DataSet and Annotation messages, and consult its own release notes for
client-library API changes, which are that repo's to describe.

The reshaped messages reach Python callers as the renamed and re-nested fields described above —
`Annotation.description`, top-level `Annotation`, a flat `SaveDataSetRequest` — and Python's
absence of compile-time checking means these surface at runtime rather than at build time. The
criteria AND/OR change and the unset-`limit` paging change are silent in every language. Steps 2
through 6 of the [upgrade checklist](#upgrading-from-1150) apply unchanged.

For stub layout and how to generate them from a checkout, see
[Generating and importing Python stubs](../cookbook/python-stubs.md).

## Documentation

`README.md` gains full reference sections for the Sample Status API and for the new DataSet,
Annotation, and Calculations methods, and the Data Set / Annotation sections are rewritten for the
reshaped messages. Its Python client-library link pointed at a stale
`craigmcchesney/dp-python-lib` org and now points at `osprey-dcs`, matching every other reference
in the repo.

New cookbook recipe: **[Sample status](../cookbook/sample-status.md)** — labeling samples with
status codes (dense and sparse), querying statuses, re-labeling a range, and filtering data queries
by status. The **[Data sets, annotations, export](../cookbook/datasets-and-annotations.md)** recipe
is substantially rewritten for #132, including column-level provenance.
**[API conventions](../cookbook/conventions.md)** now states the unset-limit and malformed-token
rules once, and calls out server-streaming queries as the exception to the paging scheme.

**Per-recipe "Verified against" headers are gone** (dp-grpc #141). That convention asserts when someone
last checked a recipe, so it decays at every version bump — six of eight recipes were still pinned
to `rel-1.14.0`, and one claimed a `rel-1.17.0` that existed neither in `pom.xml` nor as a tag.
Only the latest release is supported, so recipes now simply describe the current protos on `main`;
the `rel-*` tags remain the authority on what any past release contained. Durable facts are kept as
short in-body notes — "added in 1.15.0 and not available in earlier releases" — which are facts
about the API rather than about when someone last looked, so they never need updating.

**Plan documents are now version-controlled** under `plan/tickets/<N>/`, starting with
[#132](../../plan/tickets/132/plan.md) (plus a dp-service handoff document) and
[#143](../../plan/tickets/143/plan.md). Drafts still live outside the repo; a plan is promoted here
once its decisions are settled, so it gets PR review and a stable URL readable cross-repo. A
committed plan is a point-in-time record, not a living document — see
[`plan/README.md`](../../plan/README.md).

## Build and release infrastructure (dp-grpc Issue #133)

All six GitHub Actions references across both workflows are **pinned to full commit SHAs** with
trailing version comments, per osprey-dcs/data-platform#90. The release job runs with
`contents: write` and publishes the artifacts users download, so a compromised upstream tag there
could replace them. Each floating major resolved to the SHA it was replaced with, so the pinning
itself is behavior-neutral.

A `.github/dependabot.yml` (github-actions ecosystem, monthly, grouped) keeps the pins from going
stale silently.

`generate-python-stubs.yml` gains a `dry_run` dispatch input, defaulting to **true**. Its write-side
steps push a branch and open a PR in dp-python-lib, so before this there was no way to exercise the
workflow without writing to another repo for real — which made the pins untestable short of cutting
a release. The gate is a single job-level env var rather than six step-level conditions, since a
drifted condition would write when it should not. **A `rel-*` tag push is unaffected and always
syncs for real.**
