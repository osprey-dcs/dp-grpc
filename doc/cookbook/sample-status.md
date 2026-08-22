# Sample Status Cookbook

Worked examples for the Sample Status API, part of the Annotation Service: assigning status
codes to individual PV samples, reading them back, and using them to filter time-series queries.

> **Verified against:** dp-grpc `1.16.0` (Java `com.ospreydcs:dp-grpc:1.16.0`).
> The Sample Status API is **new in 1.16.0**, which is not yet released — it is verified
> against the `main` branch, and exists in no released version.  The domain registry methods
> (`saveSampleStatusDomain()` / `querySampleStatusDomains()`) are reserved placeholders in
> that release and return a "not implemented" error.

Reference documentation: [Sample Status API](../../README.md#sample-status-api) and
[PV Data Query V2 Methods](../../README.md#pv-data-query-v2-methods) (for the
`sampleStatusSelector`).  Response checking, paging, and time-range semantics follow the
patterns in [conventions.md](conventions.md).

### Imports used by the examples

Snippets name generated classes without qualification, for readability:

```java
import com.ospreydcs.dp.grpc.v1.annotation.SaveSampleStatusesRequest;
import com.ospreydcs.dp.grpc.v1.annotation.QuerySampleStatusesRequest;
import com.ospreydcs.dp.grpc.v1.annotation.DeleteSampleStatusesRequest;
import com.ospreydcs.dp.grpc.v1.common.SampleStatusFrame;
import com.ospreydcs.dp.grpc.v1.common.SampleStatusColumn;
import com.ospreydcs.dp.grpc.v1.common.SampleStatusBucket;
import com.ospreydcs.dp.grpc.v1.common.DataTimestamps;
import com.ospreydcs.dp.grpc.v1.common.SamplingClock;
import com.ospreydcs.dp.grpc.v1.common.TimestampList;
import com.ospreydcs.dp.grpc.v1.common.TimeRange;
import com.ospreydcs.dp.grpc.v1.common.Timestamp;
import com.ospreydcs.dp.grpc.v1.query.SampleStatusSelector;
import com.ospreydcs.dp.grpc.v1.query.QuerySpec;
import com.ospreydcs.dp.grpc.v1.query.PvSelector;
import com.ospreydcs.dp.grpc.v1.query.QuerySamplesRequest;
import com.ospreydcs.dp.grpc.v1.query.ExecutionOptions;
```

## Contents

- [Labeling every sample in a range (dense)](#labeling-every-sample-in-a-range-dense)
  — an ML model scores a regularly-sampled PV, one status per sample
- [Flagging individual suspect points (sparse)](#flagging-individual-suspect-points-sparse)
  — an operator marks a handful of samples without touching the rest
- [Reading statuses back](#reading-statuses-back)
- [Re-labeling a range cleanly](#re-labeling-a-range-cleanly) — delete, then save
- [Filtering a data query by status](#filtering-a-data-query-by-status)

## Model

A **sample status** assigns an int32 status code to one PV sample at one timestamp.  Codes are
interpreted within a **domain** — a named contract (e.g. `data_quality`, `ml_anomaly`) agreed
between the producers and consumers of the statuses.  As with `EnumColumn`, the MLDP stores the
codes but does not validate or interpret them; the reserved domain registry methods will
eventually let a domain's code mappings be documented in the archive itself.

A **layer** names the producer stream assigning the statuses (e.g. `ml_model_v1`,
`rule_engine`, `operator_override`), so several independent interpretations of the same samples
can coexist within one domain.  The identity key of an individual status is
**(pvName, timestamp, domain, layer)** — saving again with the same key replaces that status
and no other.

Two properties drive everything below:

- **Absence means "no assertion".**  There is no implicit default status; labeling three
  samples says nothing about the rest.
- **Matching is by exact timestamp.**  A status attaches to a sample only when their
  timestamps are equal at nanosecond precision.  Label using timestamps taken from data query
  results (or exact `SamplingClock` arithmetic) — a recomputed or rounded timestamp will
  silently fail to match.

Examples below use a small `data_quality` contract; the values are the producer's choice, not
the API's:

```java
final int DQ_VALID = 1;
final int DQ_SUSPECT = 2;
final int DQ_BAD = 3;
```

## Labeling every sample in a range (dense)

An ML anomaly detector has scored every sample of a PV archived at 1 kHz.  Because the data is
regularly sampled, a `SamplingClock` expresses the time axis without per-sample timestamps —
the natural fit for dense labeling:

```java
SampleStatusFrame frame = SampleStatusFrame.newBuilder()
    .setDomain("ml_anomaly")                     // names the code contract
    .setLayer("ml_model_v1")                     // names the producer stream
    .setDataTimestamps(DataTimestamps.newBuilder()
        .setSamplingClock(SamplingClock.newBuilder()
            .setStartTime(ts(t0))                // == the data's clock, exactly
            .setPeriodNanos(1_000_000L)          // 1 kHz
            .setCount(1000)))
    .addStatusColumns(SampleStatusColumn.newBuilder()
        .setPvName("S01-BPM01")
        .addAllStatusCodes(codes)                // one int32 per timestamp: 1000 entries
        .addAllConfidence(scores))               // optional; empty, or one float per timestamp
    .build();

SaveSampleStatusesRequest request = SaveSampleStatusesRequest.newBuilder()
    .addFrames(frame)
    .setSource("anomaly-detector build 214")     // free-form provenance, applies to all frames
    .setModifiedBy("ml-pipeline")
    .build();
```

`SaveSampleStatusesResult.savedCount` reports the total number of individual statuses upserted.

Things to get right:

- **One column per PV, shared time axis.**  A frame carries one `DataTimestamps` and any number
  of `SampleStatusColumn`s; every column must supply exactly one code per timestamp.  A PV may
  appear in at most one column per frame.
- **The clock must match the data's clock exactly.**  Same `startTime`, same `periodNanos` —
  matching is exact-timestamp, so an off-by-one-nanosecond period misses every sample after the
  first.
- **`confidence` and `reasons` are all-or-nothing.**  Each is either empty or has exactly one
  entry per timestamp.  Omit an all-empty `reasons` list entirely rather than sending empty
  strings.

## Flagging individual suspect points (sparse)

An operator reviews a plot and flags three samples out of thousands.  Supply only those
timestamps with an explicit `TimestampList`; the unlabeled samples carry no assertion — you do
not mark the rest VALID:

```java
final int DQ_SUSPECT = 2, DQ_BAD = 3;            // the data_quality contract (see Model)

// take the exact timestamps from a data query result (see query.md), not recomputed values
List<Timestamp> suspect = List.of(rowIndex.get(17), rowIndex.get(18), rowIndex.get(41));

SampleStatusFrame frame = SampleStatusFrame.newBuilder()
    .setDomain("data_quality")
    .setLayer("operator_override")
    .setDataTimestamps(DataTimestamps.newBuilder()
        .setTimestampList(TimestampList.newBuilder()
            .addAllTimestamps(suspect)))         // must be strictly increasing
    .addStatusColumns(SampleStatusColumn.newBuilder()
        .setPvName("S01-GCC01")
        .addAllStatusCodes(List.of(DQ_SUSPECT, DQ_SUSPECT, DQ_BAD))
        .addReasons("baseline drift")
        .addReasons("baseline drift")
        .addReasons("spike"))
    .build();
```

Saving is a per-status upsert: flagging these three points later with different codes replaces
exactly these three statuses (same PV, timestamps, domain, and layer) and touches nothing else.

## Reading statuses back

`querySampleStatuses()` returns statuses as `SampleStatusBucket` objects — one PV, one
(domain, layer), one contiguous time axis per bucket:

```java
QuerySampleStatusesRequest request = QuerySampleStatusesRequest.newBuilder()
    .setTimeRange(TimeRange.newBuilder()
        .setBeginTime(ts(t0))
        .setEndTime(ts(t1)))                     // half-open [beginTime, endTime)
    .addPvNames("S01-GCC01")                     // optional filter; empty = all PVs
    .addDomains("data_quality")                  // optional filter; empty = all domains
    .addLayers("operator_override")              // optional filter; empty = all layers
    .setLimit(100)
    .setPageToken(pageToken)                     // "" for the first page
    .build();
```

Filter fields are ANDed; values within a field are ORed — the
[standard criteria rules](conventions.md#query-criteria).  All three filters are optional: an
empty `pvNames` list matches **all** PVs with statuses in the range, which is how you discover
what a layer has labeled (e.g. before retiring it).  Page with the
[standard loop](conventions.md#pagination) over
`QuerySampleStatusesResult.nextPageToken`.

```java
for (SampleStatusBucket bucket : result.getSampleStatusBucketsList()) {
    String pvName = bucket.getStatusColumn().getPvName();   // PV name lives on the column
    String domain = bucket.getDomain();
    String layer = bucket.getLayer();

    // one code per timestamp in bucket.getDataTimestamps()
    List<Integer> codes = bucket.getStatusColumn().getStatusCodesList();

    // last save affecting this bucket -- not per-sample history
    String source = bucket.getSource();
    Timestamp updated = bucket.getUpdatedTime();
}
```

Buckets are ordered by (pvName, domain, layer, bucket start time), and every bucket is complete
— paging boundaries fall between buckets.  As with `queryBuckets()`, bucket selection is the
overlap test and boundary buckets are returned **whole**, so a bucket may contain statuses
outside the requested range.

`querySampleStatusesStream()` takes the same request and streams the result fire-and-consume:
`limit` becomes the per-message chunk size, `nextPageToken` is empty on every message, and a
non-empty `pageToken` is rejected.

## Re-labeling a range cleanly

Upsert replaces a status only at its exact (pvName, timestamp, domain, layer) key.  If a
re-run of your model emits *different* timestamps than the previous run — a shifted window, a
changed sample rate — saving the new output leaves the old statuses in place alongside it.
Delete the range first, then save:

```java
DeleteSampleStatusesRequest request = DeleteSampleStatusesRequest.newBuilder()
    .setTimeRange(TimeRange.newBuilder()
        .setBeginTime(ts(t0))
        .setEndTime(ts(t1)))
    .addPvNames("S01-BPM01")                     // optional; omit entirely = all PVs
    .setDomain("ml_anomaly")                     // required -- exactly one domain
    .setLayer("ml_model_v1")                     // required -- exactly one layer
    .build();
```

Unlike query, deletion is **exact at the sample axis**: only statuses with timestamps inside
`[beginTime, endTime)` are removed, and the server splits or rewrites boundary storage buckets
as needed.  A delete matching nothing is a success with `deletedCount = 0`, not an
`ExceptionalResult`.

The required single (domain, layer) guards against deleting more than one producer's work at
once.  `pvNames` is optional: an empty list is a deliberate wildcard covering every PV the
(domain, layer) has labeled in the range.  To retire an obsolete layer entirely, use a wide
time range and omit `pvNames` — and to see what you are about to delete, run
`querySampleStatuses()` with the same wildcard first.

> **Delete-then-save is two RPCs, not a transaction.**  Between the calls, concurrent readers
> see the range unlabeled — and because absence means "no assertion", a `MODE_EXCLUDE_MATCHING`
> data query in that window stops excluding the affected samples.  If the process fails after
> the delete but before the save, the range *stays* unlabeled: treat delete + save as a unit
> and re-run the save on failure (the per-status upsert makes retries safe).

## Filtering a data query by status

Statuses earn their keep at query time: `QuerySpec.sampleStatusSelector` filters the samples a
Query V2 sample-oriented method returns.  The canonical "drop bad data" query uses
`MODE_EXCLUDE_MATCHING` — samples labeled with a matching code are dropped, and unlabeled
samples pass by definition:

```java
final int DQ_SUSPECT = 2, DQ_BAD = 3;            // the data_quality contract (see Model)

SampleStatusSelector selector = SampleStatusSelector.newBuilder()
    .setDomain("data_quality")                   // required
    .addLayers("operator_override")              // optional; empty = all layers in the domain
    .addStatusCodes(DQ_SUSPECT)                  // optional; codes ORed, empty = any code
    .addStatusCodes(DQ_BAD)
    .setMode(SampleStatusSelector.Mode.MODE_EXCLUDE_MATCHING)
    .build();

QuerySpec querySpec = QuerySpec.newBuilder()
    .setTimeRange(timeRange)
    .setPvSelector(pvSelector)                   // see query.md for building these
    .setSampleStatusSelector(selector)
    .build();

QuerySamplesRequest request = QuerySamplesRequest.newBuilder()
    .setQuerySpec(querySpec)
    .setExecutionOptions(ExecutionOptions.newBuilder()
        .setLimit(10_000))
    .build();
```

The mirror-image query — "return only the anomalies" — uses `MODE_INCLUDE_MATCHING`, under
which unlabeled samples are excluded by definition.  There is no separate switch for how
unlabeled samples are treated; it falls out of the mode.

Leaving `statusCodes` empty matches statuses with **any** code: `MODE_EXCLUDE_MATCHING` with no
codes drops every sample the (domain, layers) labeled at all — and keeps working when the
producer adds new codes — while `MODE_INCLUDE_MATCHING` with no codes returns only labeled
samples.

In the returned `ColumnTable`, a filtered-out sample becomes a missing value (unset `DataValue`
value oneof) at its (PV, timestamp) position, exactly like a sample the PV never archived, and
timestamps at which every selected PV was filtered out are omitted entirely.  Read the table as
shown in [query.md](query.md#4-read-the-columntable).

The selector is accepted by `querySamples()` / `querySamplesStream()` only.  Bucket-oriented
methods return storage buckets whole and cannot represent per-sample filtering — a
`queryBuckets()` / `queryBucketsStream()` request with `sampleStatusSelector` set is rejected
with an `ExceptionalResult`.

## Also worth knowing

- **Saving a key replaces the status in full.**  `statusCodes` entry, `confidence`, and
  `reasons` alike — re-saving a key with an empty `confidence` or `reasons` list clears any
  previously stored values, so supply the complete desired state every time.  Frames are
  processed in request order; a key appearing in two frames takes the later frame's value.
- **The selector composes with `configurationSelector` by intersection.**  The activation
  intervals first restrict the time axis, then status filtering applies to the samples that
  survive; see
  [query.md](query.md#restricting-a-query-to-configuration-activation-intervals).
- **The bucket layout of query results is a storage detail.**  How statuses group into
  `SampleStatusBucket`s (and whether their windows align with data buckets) is not part of the
  contract; consume the statuses, not the bucketing.
- **The service does not validate that status timestamps match archived samples.**  Alignment
  is a producer contract, applied at query time by exact-timestamp matching.  A status at a
  timestamp with no archived sample is stored, returned by `querySampleStatuses()`, and simply
  never matches during selector filtering.
- **`source` and `modifiedBy` are last-writer-only**, recorded at storage-bucket granularity.
  There is no per-sample audit history.  `updatedTime` is server-set and not accepted as input.
  Both apply to the *whole* save request, so batch frames from a single producer per request —
  mixing producers records the same provenance for all of them.
- **Whole-request validation.**  A save is validated and rejected as a whole — no partial save
  on rejection.  A mid-write *error* on a valid request may leave some frames persisted; the
  per-status upsert makes retrying the whole request safe.
- The Sample Status API is the designated replacement for the deprecated `DataValue`
  `ValueStatus` mechanism: capture acquisition-time alarm/status information (e.g. EPICS
  severity and status) as sample statuses in a status domain instead.
