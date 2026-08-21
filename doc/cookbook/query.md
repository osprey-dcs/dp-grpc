# Querying Archived Time-Series Data

Worked examples for retrieving PV time-series data from the archive with the Query Service —
choosing between the bucket- and sample-oriented methods, selecting PVs by name, pattern, or
metadata, paging large results, and migrating an existing V1 client to V2.

> **Verified against:** dp-grpc `rel-1.15.0` (Java `com.ospreydcs:dp-grpc:1.15.0`).
> The **Query API V2 methods** (`queryBuckets`, `queryBucketsStream`, `querySamples`,
> `querySamplesStream`) were added in issue #123 and are **new in 1.15.0** — they do **not**
> exist in `rel-1.14.0`.  The V1 methods (`queryData`, `queryDataStream`,
> `queryDataBidiStream`, `queryTable`, `queryPvStats`) are present in 1.14.0 and remain
> available in 1.15.0 for backward compatibility.

Reference documentation: [PV Data Query V2 Methods](../../README.md#pv-data-query-v2-methods),
[PV Data Query Methods](../../README.md#pv-data-query-methods) (V1), and
[PV Stats Query Methods](../../README.md#pv-stats-query-methods).  Shared response, paging, and
criteria rules are in [conventions.md](conventions.md).

### Imports used by the examples

Snippets below name generated classes without qualification, for readability.  Several of the V2
criterion types are deeply nested, so here is the full resolution:

```java
import com.ospreydcs.dp.grpc.v1.common.TimeRange;
import com.ospreydcs.dp.grpc.v1.common.Timestamp;
import com.ospreydcs.dp.grpc.v1.common.DataBucket;

import com.ospreydcs.dp.grpc.v1.query.QuerySpec;
import com.ospreydcs.dp.grpc.v1.query.ExecutionOptions;
import com.ospreydcs.dp.grpc.v1.query.ResultRepresentation;
import com.ospreydcs.dp.grpc.v1.query.PvSelector;
import com.ospreydcs.dp.grpc.v1.query.PvNameList;
import com.ospreydcs.dp.grpc.v1.query.PvNamePattern;
import com.ospreydcs.dp.grpc.v1.query.ConfigurationSelector;
import com.ospreydcs.dp.grpc.v1.query.QueryBucketsRequest;
import com.ospreydcs.dp.grpc.v1.query.QuerySamplesRequest;
import com.ospreydcs.dp.grpc.v1.query.QueryPvStatsRequest;
```

`PvSelector`, `ExecutionOptions`, and `ResultRepresentation` are top-level messages in
`query.proto`, not nested inside `QuerySpec`.  The metadata criterion types nest three deep —
`PvSelector.MetadataQuery.Criterion.PvNameCriterion` and likewise for `TagsCriterion`,
`AttributesCriterion`, and `AliasesCriterion`.  Configuration criteria nest one level less:
`ConfigurationSelector.Criterion.ConfigurationNameCriterion`.

## Contents

- [Model](#model) — buckets vs. samples, and the three parts of a V2 request
- [Choosing a query method](#choosing-a-query-method)
- [Discovering PVs before you query](#discovering-pvs-before-you-query)
- [Fetching an aligned table for analysis](#fetching-an-aligned-table-for-analysis) — the
  common case: `querySamples` into a rectangular table
- [Paging a large bucket query](#paging-a-large-bucket-query) — resumable `limit`/`pageToken`
- [Streaming a full time range](#streaming-a-full-time-range) — maximum throughput, no round
  trips
- [Selecting PVs by metadata](#selecting-pvs-by-metadata)
- [Restricting a query to configuration activation intervals](#restricting-a-query-to-configuration-activation-intervals)
- [Migrating a V1 client to V2](#migrating-a-v1-client-to-v2)
- [Also worth knowing](#also-worth-knowing)

## Model

The archive stores time-series data using the **bucket pattern**: all samples for one PV over a
contiguous time range live in a single record, not one record per sample.  Every query method is
ultimately reading buckets; they differ in whether they hand you the buckets or hide them.

**Bucket-oriented** (`queryBuckets`, `queryBucketsStream`) returns `DataBucket` objects that
correspond closely to the storage model.  One `DataBucket` is one PV, one time range, one column
message.  This is the cheapest path — the server does almost no reshaping — so it is what you
want for archive export, infrastructure services, and high-performance Java clients.

The trade-off: **boundary buckets are returned whole, not trimmed.**  A bucket that merely
*overlaps* your `TimeRange` comes back intact, so the first and last buckets may contain samples
outside `[beginTime, endTime)`.  If you need strict containment you must filter client-side, or
use a sample-oriented query.

**Sample-oriented** (`querySamples`, `querySamplesStream`) returns a `ColumnTable`: the server
assembles buckets internally and presents one aligned, column-oriented table over a single
**union timestamp axis**.  Samples are trimmed to the half-open range, so every returned
timestamp satisfies `beginTime <= t < endTime`.  This is the natural shape for pandas, plotting,
and ML feature extraction, and is expected to be the preferred method for the Python client
library.

### The three parts of a V2 request

Every V2 request — `QueryBucketsRequest` and `QuerySamplesRequest` alike — has the same
three-part shape.  This separation is the point of V2: *what* you want is decoupled from *how*
it is delivered.

| Field | Type | Meaning |
|---|---|---|
| `querySpec` | `QuerySpec` | **Required.** What data to retrieve. |
| `executionOptions` | `ExecutionOptions` | Optional. Paging: `limit`, `pageToken`. |
| `resultRepresentation` | `ResultRepresentation` | Optional. Format flags. |

`QuerySpec` carries `timeRange` (required), `pvSelector` (required), and the optional
`configurationSelector` and `sampleStatusSelector`.  A `QuerySpec` without
`sampleStatusSelector` can be handed to any of the four V2 methods — switching from buckets to
samples, or from unary to streaming, changes nothing about your selection logic.
`sampleStatusSelector` is the one exception: it is supported by the sample-oriented methods
only, and a bucket-oriented request with it set is rejected with an `ExceptionalResult` — see
[Filtering a data query by status](sample-status.md#filtering-a-data-query-by-status).

> **Name collision.**  `query.proto` defines both the V2 top-level `QuerySpec`
> (`timeRange` / `pvSelector` / `configurationSelector` / `sampleStatusSelector`) and a
> *nested* V1 `QueryDataRequest.QuerySpec` (`beginTime` / `endTime` / `pvNames`).  In Java these are
> `com.ospreydcs.dp.grpc.v1.query.QuerySpec` and
> `com.ospreydcs.dp.grpc.v1.query.QueryDataRequest.QuerySpec`.  Importing the wrong one is an
> easy and confusing mistake.

### Time ranges

`TimeRange` is half-open: `beginTime` inclusive, `endTime` exclusive — see
[Time in conventions.md](conventions.md#time).  Note the asymmetry described above: sample
queries trim to exactly this range, bucket queries apply it as an *overlap* test, which
`common.proto` documents as `bucket.firstTime < endTime AND bucket.lastTime >= beginTime`.

That formula describes **server-side selection logic**, not fields you can read.  `DataBucket`
itself has no `firstTime` / `lastTime` fields — its fields are `pvName`, `dataTimestamps`,
`providerId`, `providerName`, and `dataValues`.  To recover a bucket's own extent client-side,
derive it from `dataTimestamps` (either the `SamplingClock` or the `TimestampList`).

## Choosing a query method

| You want | Use |
|---|---|
| A rectangular table for analysis, plotting, or ML | `querySamples` |
| The same, too large for one response | `querySamplesStream`, or `querySamples` with paging |
| Raw archive records, bulk export, maximum throughput | `queryBucketsStream` |
| Bulk retrieval that must survive a restart | `queryBuckets` with `limit` + `pageToken` |
| To know which PVs exist and what they cover | `queryPvStats` (V1; no V2 replacement) |

The unary/streaming choice is really a choice about **resumability**:

- **Unary** methods are paged and resumable.  Each response carries a `nextPageToken` you can
  persist; resubmitting the same `QuerySpec` with that token resumes mid-result after a crash
  or restart.
- **Streaming** methods are *fire-and-consume*.  The server streams to completion on its own.
  `nextPageToken` is **always empty** on streamed messages, and `ExecutionOptions.pageToken`
  **must** be empty — a non-empty token is rejected with an `ExceptionalResult` rather than
  silently returning the first page.  Do not write a paging loop around a streaming call.

`ExecutionOptions.limit` means something slightly different in each case, which is worth
internalizing before you tune it:

| Method | `limit` counts |
|---|---|
| `queryBuckets` | `DataBucket`s per page |
| `querySamples` | timestamps (rows) per page |
| `queryBucketsStream` | `DataBucket`s per streamed message (chunk size) |
| `querySamplesStream` | timestamps (rows) per streamed message |

Omitting `limit` (or setting 0) lets the server pick a default.

## Discovering PVs before you query

Before choosing a time range, find out which PVs exist and what the archive actually covers.
`queryPvStats` answers both, and has **no V2 replacement** — it remains the discovery step in
front of a V2 data query.

```java
QueryPvStatsRequest.newBuilder()
    .setPvNamePattern(PvNamePattern.newBuilder()
        .setPattern("^S01-GCC.*"))     // or .setPvNameList(PvNameList...)
    .build();
```

Read `QueryPvStatsResponse.StatsResult.pvStats`.  The two fields that matter most for planning a
query are `firstDataTimestamp` and `lastDataTimestamp` — clamp your `TimeRange` inside them so
you do not silently ask for an uncovered window.  `numBuckets` is a useful rough size estimate
when deciding between a unary paged call and a stream.

> `queryPvStats` was **renamed from `queryPvMetadata`** and returns *archive ingestion
> statistics*, not user-defined metadata.  User-defined PV metadata lives in
> `DpAnnotationService.queryPvMetadata()`.  (Similarly, `queryProviderStats` was renamed from
> `queryProviderMetadata`.)

> **`queryPvStats` does not follow the V2 empty-result convention.**  Its proto comment states
> that an `ExceptionalResult` is returned when the query matches no data.  V2 methods return an
> empty list or empty table instead.  Handle the two differently.

## Fetching an aligned table for analysis

The common case: you know your PVs and a time window, and you want a rectangular table.

### 1. Build the time range

```java
TimeRange timeRange = TimeRange.newBuilder()
    .setBeginTime(ts(t0))     // inclusive
    .setEndTime(ts(t1))       // EXCLUSIVE
    .build();
```

### 2. Select the PVs

```java
PvSelector pvSelector = PvSelector.newBuilder()
    .setPvNameList(PvNameList.newBuilder()
        .addAllPvNames(List.of("S01-GCC01", "S01-GCC02", "S01-BPM01")))
    .build();
```

Exactly one of `pvNameList`, `pvNamePattern`, or `metadataQuery` must be set.  An unset
`PvSelector`, or one with an unset selector oneof, returns an `ExceptionalResult`.

### 3. Assemble the request and page through the result

```java
QuerySpec querySpec = QuerySpec.newBuilder()
    .setTimeRange(timeRange)
    .setPvSelector(pvSelector)
    .build();

String pageToken = "";
do {
    QuerySamplesRequest request = QuerySamplesRequest.newBuilder()
        .setQuerySpec(querySpec)                     // SAME spec on every page
        .setExecutionOptions(ExecutionOptions.newBuilder()
            .setLimit(10_000)                        // rows (timestamps) per page
            .setPageToken(pageToken))                // "" for the first page
        .build();

    QuerySamplesResponse response = stub.querySamples(request);
    if (response.hasExceptionalResult()) { /* see conventions.md */ break; }

    QuerySamplesResponse.SampleQueryResult result = response.getSampleQueryResult();
    process(result.getColumnTable());
    pageToken = result.getNextPageToken();
} while (!pageToken.isEmpty());
```

The paging loop follows the standard convention in
[conventions.md](conventions.md#pagination), with one API-specific wrinkle: **the page token is
not a self-contained cursor.**  You must resubmit the same `QuerySpec` alongside it.

Paging boundaries are placed between timestamps, so all PV values for a given timestamp always
arrive in the same page — you never have to stitch a partial row across two responses.

### 4. Read the ColumnTable

```java
ColumnTable table = result.getColumnTable();

List<Timestamp> rowIndex = table.getTimestampList().getTimestampsList();

for (DataColumn column : table.getDataColumnsList()) {
    String pvName = column.getName();
    for (int row = 0; row < rowIndex.size(); row++) {
        DataValue value = column.getDataValues(row);
        if (value.getValueCase() == DataValue.ValueCase.VALUE_NOT_SET) {
            continue;                                // missing sample for this PV at this row
        }
        double d = value.getDoubleValue();
    }
}
```

Three things to get right here:

- **`timestampList` is the row index.**  It is the ordered *union* of all selected PVs'
  timestamps for this page.  It is deliberately a plain `TimestampList` and never a
  `SamplingClock` — the union of several PVs' samples is generally irregular and cannot be
  expressed as a uniform clock.
- **Every column has exactly as many entries as there are timestamps.**  Columns are padded, not
  sparse; you index them positionally against the row index.
- **A missing sample is a `DataValue` whose `value` oneof is unset** — not a zero, not a NaN, not
  an omitted element.  Calling `getDoubleValue()` without checking `getValueCase()` silently
  yields `0.0` for missing samples.  This is the single most likely way to get quietly wrong
  numbers out of this API.

`DataColumn` and `DataValue` are deprecated for *ingestion* (per-sample allocation is expensive),
but they are the intended, supported representation for query results — precisely because the
unset oneof gives native missing-value support that the dense column types lack.  Do not avoid
them when reading.

## Paging a large bucket query

For an export or infrastructure job that needs bounded memory **and** must survive a restart, use
unary `queryBuckets` with a persisted page token.

```java
QuerySpec querySpec = QuerySpec.newBuilder()
    .setTimeRange(timeRange)
    .setPvSelector(pvSelector)
    .build();

String pageToken = loadCheckpoint();     // "" on a fresh run
do {
    QueryBucketsRequest request = QueryBucketsRequest.newBuilder()
        .setQuerySpec(querySpec)
        .setExecutionOptions(ExecutionOptions.newBuilder()
            .setLimit(500)               // DataBuckets per page
            .setPageToken(pageToken))
        .build();

    QueryBucketsResponse response = stub.queryBuckets(request);
    if (response.hasExceptionalResult()) { /* log and stop */ break; }

    QueryBucketsResponse.BucketQueryResult result = response.getBucketQueryResult();
    for (DataBucket bucket : result.getDataBucketsList()) {
        process(bucket);
    }

    pageToken = result.getNextPageToken();
    saveCheckpoint(pageToken);           // persist BEFORE the next call to make restart safe
} while (!pageToken.isEmpty());
```

Every bucket in a page is complete — paging boundaries always fall *between* buckets, never
inside one.  An empty result is an empty `dataBuckets` list, **not** an `ExceptionalResult`.

Reading a bucket means switching on the `DataValues` oneof, since a bucket carries exactly one
column message:

```java
DataValues values = bucket.getDataValues();
switch (values.getValuesCase()) {
    case DOUBLECOLUMN -> handle(values.getDoubleColumn());
    case INT64COLUMN  -> handle(values.getInt64Column());
    case DATACOLUMN   -> handle(values.getDataColumn());
    // ... plus the array, image, struct, and serialized cases
    default -> { /* unset or a type this client does not handle */ }
}
```

The bucket's own time axis is a `DataTimestamps`, which may be *either* a `SamplingClock` or an
explicit `TimestampList` — check `bucket.getDataTimestamps().hasSamplingClock()` before assuming.
(This is unlike the sample-query `ColumnTable`, which is always an explicit list.)

## Streaming a full time range

For a bulk export or high-performance client that wants the whole result with no round trips and
no cursor bookkeeping:

```java
QueryBucketsRequest request = QueryBucketsRequest.newBuilder()
    .setQuerySpec(querySpec)
    .setExecutionOptions(ExecutionOptions.newBuilder()
        .setLimit(1_000))                       // per-message chunk size
        // NOTE: pageToken deliberately NOT set -- a non-empty token is rejected
    .setResultRepresentation(ResultRepresentation.newBuilder()
        .setUseSerializedColumns(true)          // less gRPC serialization work
        .setExcludeColumnMetadata(true))        // smaller payloads
    .build();

stub.queryBucketsStream(request, responseObserver);   // consume until onCompleted()
```

Stream completion — not a token — signals exhaustion.  `nextPageToken` is always empty on every
streamed message; do not check it.

Two things about `ResultRepresentation`, neither of which changes *which* data are selected:

- **`excludeColumnMetadata` has inverted sense.**  The default (`false`) **includes**
  `ColumnMetadata`; set it `true` to suppress it.  The field is named this way to avoid the
  proto3 "default true" footgun.  `ColumnMetadata` carries `provenance` (a `ColumnProvenance`
  with `source` and `process`), `tags`, and `attributes`.
- **`useSerializedColumns` changes which field is populated.**  For bucket queries each
  `DataBucket.dataValues` carries a `serializedDataColumn` instead of a typed column; for sample
  queries the `ColumnTable` populates `serializedDataColumns` instead of `dataColumns`.  Exactly
  one of the two `ColumnTable` lists is populated per response, so read whichever corresponds to
  the flag you sent.

A `SerializedDataColumn` has `name`, an `encoding` string (the proto documents examples such as
`"Image:v1"`, `"Struct:BeamPosition:v2"`, and `"proto:Image"`), a `payload` of bytes, and an
optional `metadata` (`ColumnMetadata`).  For sample queries the `ColumnTable` proto comment
describes `serializedDataColumns` as the byte-encoded form of the same `DataColumn`s, preserving
the unset-oneof missing-value encoding — so the missing-value rule above still applies once you
decode.

`querySamplesStream` works identically, with `limit` counting rows instead of buckets.

## Selecting PVs by metadata

Rather than maintaining a hardcoded name list, select PVs by their metadata — "all vacuum-gauge
PVs tagged `production` in sector 1":

```java
PvSelector pvSelector = PvSelector.newBuilder()
    .setMetadataQuery(PvSelector.MetadataQuery.newBuilder()
        .addCriteria(PvSelector.MetadataQuery.Criterion.newBuilder()
            .setPvNameCriterion(
                PvSelector.MetadataQuery.Criterion.PvNameCriterion.newBuilder()
                    .addPrefix("S01-")))
        .addCriteria(PvSelector.MetadataQuery.Criterion.newBuilder()
            .setTagsCriterion(
                PvSelector.MetadataQuery.Criterion.TagsCriterion.newBuilder()
                    .addValues("production")))
        .addCriteria(PvSelector.MetadataQuery.Criterion.newBuilder()
            .setAttributesCriterion(
                PvSelector.MetadataQuery.Criterion.AttributesCriterion.newBuilder()
                    .setKey("subsystem")
                    .addValues("vacuum"))))
    .build();
```

(`PvNameCriterion`, `TagsCriterion`, `AttributesCriterion`, and `AliasesCriterion` are all nested
inside `PvSelector.MetadataQuery.Criterion` — fully qualified above; static-import them to
shorten.)

The AND/OR rule is the standard one from
[conventions.md](conventions.md#query-criteria): **separate criteria are ANDed, values within one
criterion are ORed.**  So the above means *(name starts with `S01-`) AND (tagged `production`)
AND (attribute `subsystem` = `vacuum`)*.  To require two tags simultaneously, add two separate
`TagsCriterion` entries.

Available criteria are `pvNameCriterion`, `tagsCriterion`, `attributesCriterion`, and
`aliasesCriterion`.  The name and alias criteria each offer `exact`, `prefix`, and `contains`
sub-lists, all ORed together.  `AttributesCriterion` with an **empty `values` list** is a
key-only existence search — there is deliberately no `keyOnly` flag.

This query language mirrors `DpAnnotationService.queryPvMetadata()`, which is useful: you can
prototype and verify a selection there before wiring it into a data query.  But the criterion
types are **deliberately duplicated, not shared** — `PvSelector.MetadataQuery.Criterion` and
`QueryPvMetadataRequest.QueryPvMetadataCriterion` are distinct Java types and criterion objects
cannot be passed between the two APIs.  You must rebuild them.

## Restricting a query to configuration activation intervals

To retrieve data only from periods when a particular machine configuration was in force, add a
`ConfigurationSelector` rather than hand-assembling the activation intervals yourself:

```java
QuerySpec querySpec = QuerySpec.newBuilder()
    .setTimeRange(timeRange)
    .setPvSelector(pvSelector)
    .setConfigurationSelector(ConfigurationSelector.newBuilder()
        .addCriteria(ConfigurationSelector.Criterion.newBuilder()
            .setConfigurationNameCriterion(
                ConfigurationSelector.Criterion.ConfigurationNameCriterion.newBuilder()
                    .addValues("lattice-2026-A"))))
    .build();
```

The server finds the matching `ConfigurationActivation` records, **unions** their active
intervals, **intersects** that union with `QuerySpec.timeRange`, and retrieves data only within
the resulting — possibly fragmented — intervals.  You get one result set covering several
disjoint windows.  When the spec also carries a `sampleStatusSelector`, the two compose by
intersection: the activation intervals first restrict the time axis as described here, and
status filtering then applies to the samples that survive.

Criteria available: `configurationNameCriterion`, `clientActivationIdCriterion`,
`categoryCriterion`, `tagsCriterion`, and `attributesCriterion`.  The same AND/OR rule applies.
They are matched against both the `Configuration` referenced by each activation and the
activation's own tags and attributes.

The criteria are strictly **non-temporal** — there is no time criterion here.
`QuerySpec.timeRange` is the single time axis for the whole query, so there is no second time
specification to reconcile.  (The `Criterion` field numbers start at 12 because 10–11 are the
temporal arms in the `annotation.proto` message this mirrors, deliberately omitted.)

> **The easiest way to silently get zero rows.**  A `ConfigurationSelector` with an **empty
> `criteria` list matches nothing** and returns an empty result.  To query the full `TimeRange`
> unconditionally, **omit the `ConfigurationSelector` entirely** — do not send an empty one.
> Guard any code that builds the selector conditionally.

See the [Machine Configuration recipe](machine-configuration.md) for finding the configuration or
activation you want to reference.

## Migrating a V1 client to V2

V1 methods remain available and are not deprecated, so migration can be incremental.

| V1 | V2 | Notes |
|---|---|---|
| `queryData` | `queryBuckets` | Add `ExecutionOptions` paging; V1 returned everything in one message. |
| `queryDataStream` | `queryBucketsStream` | Nearly drop-in; add `limit` for chunk sizing. |
| `queryDataBidiStream` | `queryBucketsStream` | Delete all cursor logic — see below. |
| `queryTable` (`TABLE_FORMAT_COLUMN`) | `querySamples` | Different `ColumnTable` type — see below. |
| `queryTable` (`TABLE_FORMAT_ROW_MAP`) | `querySamples` + client-side pivot | Row format not carried forward. |
| `queryPvStats` | *(unchanged)* | No V2 replacement; keep using it. |

**The query spec.**  For the name-list case this is a mechanical 1:1 mapping.  V1's
`QueryDataRequest.QuerySpec{beginTime, endTime, pvNames}` becomes V2's top-level
`QuerySpec{TimeRange, PvSelector.pvNameList}`.  Note that V1's `QuerySpec` has only those three
fields — there is no PV-pattern or metadata selection in V1, so regex selection, metadata
selection, configuration filtering, sample-status filtering, and paging are all additive in V2;
you can adopt them later.

Serialized columns are also new as a *request* flag in V2.  The V1 methods have no serialized-column
option — `QueryDataRequest.QuerySpec` declares only `beginTime`, `endTime`, and `pvNames`, and V1
results always carry regular `DataColumn` objects.  If you query large volumes and want to avoid the
gRPC framework's extra serialization work, that is a reason to move to V2 and set
`ResultRepresentation.useSerializedColumns`.

**Drop the cursor protocol.**  V1's `queryDataBidiStream` required the client to send a
`CursorOperation` with `CURSOR_OP_NEXT` for each additional response.  `queryBucketsStream`
replaces this outright: the server streams to completion on its own, and there is no V2
bidirectional query method.  Delete the request-sending side entirely.  If *resumability* rather
than flow control was your reason for using the cursor, the V2 answer is unary `queryBuckets`
with `limit`/`pageToken`, not a stream.

**Watch the `ColumnTable` collision.**  V1 `queryTable` returns
`QueryTableResponse.ColumnTable{dataTimestamps, dataColumns}`.  V2 `querySamples` returns the
top-level `dp.service.query.ColumnTable{timestampList, dataColumns, serializedDataColumns}`.
Different types, and the row axis changes from a `DataTimestamps` (which could be a
`SamplingClock`) to a plain `TimestampList`.  Code that branched on the timestamps oneof can be
simplified.

**Change your empty-result detection.**  This is the migration step most likely to be missed.
V1 `queryTable` and `queryPvStats` return an `ExceptionalResult` when the query matches no data.
V2 returns a normal success payload with an empty `dataBuckets` list or an empty `ColumnTable`.
Code that treats "exceptional" as "no data" will start reporting real errors as empty results, or
vice versa.

**The row-oriented format is gone.**  V1's `TABLE_FORMAT_ROW_MAP` /
`QueryTableResponse.RowMapTable` is explicitly not carried forward; V2 standardizes on the single
column-oriented representation.  If you need row maps, pivot client-side from the `ColumnTable`.

## Also worth knowing

- **`QuerySpec.sampleStatusSelector` (field 4) filters returned samples by sample status** —
  see the [Sample Status API](../../README.md#sample-status-api) and
  [Filtering a data query by status](sample-status.md#filtering-a-data-query-by-status).
  Sample-oriented methods only: a `queryBuckets()` / `queryBucketsStream()` request with the
  selector set is rejected with an `ExceptionalResult`.
- **`DataValue.valueStatus` is deprecated** in favor of the Sample Status API: capture
  acquisition-time alarm/status information (EPICS severity and status) as sample statuses in a
  status domain instead.  `valueStatus` still appears on archived `DataValue`s that carry it and
  can be filtered client-side; there is no server-side selection on it.
- **Unary responses are bounded by the gRPC maximum message size.**  This is the practical reason
  to set `limit` on unary calls even when you think the result is small — an unbounded unary
  query against a wide PV set can exceed the limit and fail.
- **`ExceptionalResult` statuses:** `RESULT_STATUS_REJECT` (validation rejection),
  `RESULT_STATUS_ERROR` (error handling the request), and `RESULT_STATUS_NOT_READY`, which
  signals an invalid V1 bidi cursor operation and should not appear in V2 traffic.
- **The proto does not specify** whether the ordering of `DataBucket`s within a page, or of
  `DataColumn`s within a `ColumnTable`, is stable or follows the order of PV names in your
  request.  Do not rely on either; key columns by `DataColumn.name` and buckets by
  `DataBucket.pvName`.
- **The proto does not specify** how long a `pageToken` remains valid, or what happens if a
  resumed query is submitted after the underlying data have changed.  If you persist tokens
  across a long restart window, be prepared to fall back to restarting the query.
- `DataBucket` also carries `providerId` and `providerName`, identifying which ingestion provider
  supplied the data — useful for provenance when merging archives.
