# Ingesting PV Time-Series Data

Worked examples for the Ingestion Service: registering a provider, choosing a time axis and
column type, sending data by unary call or stream, and confirming that what you sent actually
landed in the archive.

> **Verified against:** dp-grpc `rel-1.14.0` (Java `com.ospreydcs:dp-grpc:1.14.0`).
> All methods and messages in this recipe exist in 1.14.0 and are unchanged in 1.15.0.  (The
> Query API V2 methods referenced in passing under *Verifying a round trip* are new in 1.15.0.)

Reference documentation: [Provider API](../../README.md#provider-api),
[PV Data Ingestion Methods](../../README.md#pv-data-ingestion-methods), and
[Ingestion Request Status API](../../README.md#ingestion-request-status-api).
Shared response, criteria, and time conventions are in [conventions.md](conventions.md).

### Imports used by the examples

Snippets name generated classes without qualification, for readability.  Two of them are nested
inside their response message and need the full path:

```java
import com.ospreydcs.dp.grpc.v1.ingestion.IngestDataRequest;
import com.ospreydcs.dp.grpc.v1.ingestion.QueryRequestStatusRequest;
import com.ospreydcs.dp.grpc.v1.common.DataFrame;
import com.ospreydcs.dp.grpc.v1.common.DataTimestamps;
import com.ospreydcs.dp.grpc.v1.common.SamplingClock;
import com.ospreydcs.dp.grpc.v1.common.Timestamp;

// nested inside their enclosing response/request messages
import com.ospreydcs.dp.grpc.v1.ingestion.QueryRequestStatusResponse.RequestStatusResult.RequestStatus;
import com.ospreydcs.dp.grpc.v1.ingestion.QueryRequestStatusRequest.QueryRequestStatusCriterion;
```

## Contents

- [Model](#model) — the data frame, the time axis, and the async contract
- [First ingestion: register, send, confirm](#first-ingestion-register-send-confirm) — start here
- [Choosing a column type](#choosing-a-column-type)
- [Irregular sampling with an explicit timestamp list](#irregular-sampling-with-an-explicit-timestamp-list)
- [High-throughput ingestion with `ingestDataStream`](#high-throughput-ingestion-with-ingestdatastream)
- [Per-request acknowledgment with `ingestDataBidiStream`](#per-request-acknowledgment-with-ingestdatabidistream)
- [Attaching column provenance and tags](#attaching-column-provenance-and-tags)
- [Sweeping for ingestion failures](#sweeping-for-ingestion-failures)
- [Verifying a round trip](#verifying-a-round-trip)
- [Also worth knowing](#also-worth-knowing)

## Model

The unit of ingestion is a **`DataFrame`**.  Think of it as a spreadsheet: `dataTimestamps` is
the row axis, and each column message contributes one column holding exactly one value per
timestamp.  A single `DataFrame` may mix column types freely — `doubleColumns`, `enumColumns`,
`imageColumns`, and the rest all coexist in one frame and all share the one time axis.

**`DataTimestamps`** is a `oneof` with two mutually exclusive modes:

- **`samplingClock`** — a `SamplingClock` of `startTime`, `periodNanos`, and `count`.  The
  timestamps are `t_k = startTime + (k-1) * periodNanos` for `k = 1..count`, so the last sample
  falls at `startTime + (count-1)*periodNanos` and both endpoints are actual samples.  This is
  three fields on the wire regardless of sample count, and is what you want for regularly-sampled
  PVs.
- **`timestampList`** — a `TimestampList` with an explicit ordered `timestamps` list, one
  `Timestamp` per sample.  Necessary for event-driven or jittered acquisition, and far more
  expensive on the wire.

Note that a `SamplingClock` enumerates a sample set — both endpoints are real samples — whereas
query time ranges are half-open `[beginTime, endTime)` filter bounds.  These are different kinds
of thing; do not carry intuitions from one to the other.

**Every column vector must have exactly one value per timestamp.**  With a sampling clock that
means `values.size() == count`; with a timestamp list it means `values.size() ==
timestamps.size()`.  Mismatched dimensions are an explicitly documented rejection reason.  The
dense typed columns have no missing-value representation — you cannot express "no sample here"
in a `DoubleColumn`, so a gap must be handled by splitting the frame or by carrying a sentinel
your consumers agree on.

**Ingestion is asynchronous, and this is the single most important thing to understand about
this API.**  An `AckResult` means only that the request passed validation and was queued.
Persistence happens afterward, and a request that was acked can still fail during handling.  The
service writes one document per request to the MongoDB `requestStatus` collection, keyed by
`providerId` + `clientRequestId`, and `queryRequestStatus()` is the only API surface onto it.  A
client that never calls `queryRequestStatus()` has no way to learn that its data was dropped.

Providers must be registered; PVs must not.  PV names are created implicitly by ingestion.

## First ingestion: register, send, confirm

The minimal end-to-end path.  It is short, but do not stop at step 3 — step 4 is what makes it
correct.

### 1. Register the provider

`registerProvider()` is a prerequisite for all ingestion, and it is safe (and recommended) to
call on every client startup.  If a provider already exists with the given `providerName`, its
attributes are updated and the existing id is returned.

```java
RegisterProviderRequest.newBuilder()
    .setProviderName("linac-bpm-daq")          // required; uniquely identifies the provider
    .setDescription("Linac BPM data acquisition front end")
    .addAllTags(List.of("linac", "bpm"))
    .addAttributes(Attribute.newBuilder().setName("facility").setValue("linac"))
    .build();
```

Read the id and cache it for the process lifetime:

```java
String providerId = response.getRegistrationResult().getProviderId();
```

`RegistrationResult` also carries `providerName` (echoed) and `isNewProvider`.

Because registration is an update for an existing `providerName`, an impoverished call will
**overwrite** a previously registered description, tags, and attributes.  Send the complete set
you want recorded every time, exactly as you would for a `save*` method
([full-replace semantics](conventions.md#save-semantics-full-replace)).

### 2. Build the data frame

```java
SamplingClock clock = SamplingClock.newBuilder()
    .setStartTime(ts(t0))
    .setPeriodNanos(1_000_000L)     // 1 kHz
    .setCount(1000)
    .build();

DoubleColumn column = DoubleColumn.newBuilder()
    .setName("LINAC:BPM01:X")       // PV name; no pre-registration required
    .addAllValues(values)           // values.size() must equal clock count (1000)
    .build();

DataFrame frame = DataFrame.newBuilder()
    .setDataTimestamps(DataTimestamps.newBuilder().setSamplingClock(clock))
    .addDoubleColumns(column)
    .build();
```

### 3. Ingest

```java
IngestDataRequest.newBuilder()
    .setProviderId(providerId)          // required; must be the id from registerProvider()
    .setClientRequestId(nextRequestId())// required; YOU must make this unique
    .setIngestionDataFrame(frame)
    .build();
```

On success, `IngestDataResponse.AckResult` echoes `numRows` and `numColumns` as the service
parsed them from the frame.  Comparing those against what you built is a cheap way to catch a
frame you assembled wrong, and it is easy to skip:

```java
IngestDataResponse.AckResult ack = response.getAckResult();
assert ack.getNumRows() == 1000 && ack.getNumColumns() == 1;
```

`clientRequestId` uniqueness is **not enforced by the service** — deliberately, for performance.
Duplicate ids collide in the `requestStatus` collection and make step 4 ambiguous.  Generate them
client-side (a UUID, or provider-scoped monotonic counter) and record every one you send.

### 4. Confirm it persisted

After a short delay, ask for the status of that specific request:

```java
QueryRequestStatusRequest.newBuilder()
    .addCriteria(QueryRequestStatusCriterion.newBuilder()
        .setProviderIdCriterion(ProviderIdCriterion.newBuilder().setProviderId(providerId)))
    .addCriteria(QueryRequestStatusCriterion.newBuilder()
        .setRequestIdCriterion(RequestIdCriterion.newBuilder()
            .setRequestId(clientRequestId)))   // note: field is requestId, not clientRequestId
    .build();
```

Each `QueryRequestStatusCriterion` is itself a `oneof`, so combining criteria means adding
several entries; separate entries are ANDed, per
[the standard criteria rules](conventions.md#query-criteria).

```java
for (RequestStatus status : response.getRequestStatusResult().getRequestStatusList()) {
    status.getIngestionRequestStatus();   // INGESTION_REQUEST_STATUS_SUCCESS / _REJECTED / _ERROR
    status.getStatusMessage();
    status.getIdsCreatedList();           // ids in the MongoDB "buckets" collection
}
```

`idsCreated` lists one bucket id per **column** in the frame, not one per request.

Two traps here.  First, the status document is written asynchronously, so an immediate query may
return **no rows at all** — absence of a `RequestStatus` is not the same as failure.  Poll, or
defer the check.  Second, `INGESTION_REQUEST_STATUS_SUCCESS` is the **zero value** of the enum,
so an unset or defaulted status field reads as success.  Never treat "field absent" as "no status
yet"; treat "no row returned" as "not known yet".

## Choosing a column type

This is the main modeling decision in the ingestion API, and it is made per PV, once, when you
write the client.  All of these column lists live side by side in one `DataFrame`.

| Data | Column type | `DataFrame` field |
|---|---|---|
| float64 / float32 scalars | `DoubleColumn`, `FloatColumn` | `doubleColumns`, `floatColumns` |
| integer scalars | `Int64Column`, `Int32Column` | `int64Columns`, `int32Columns` |
| booleans | `BoolColumn` | `boolColumns` |
| free-form text | `StringColumn` | `stringColumns` |
| small fixed vocabulary (alarm state, mode) | `EnumColumn` | `enumColumns` |
| waveforms, 2D/3D arrays | `DoubleArrayColumn` etc. | `doubleArrayColumns` etc. |
| camera frames | `ImageColumn` | `imageColumns` |
| serialized composite records | `StructColumn` | `structColumns` |
| anything else, or a pre-encoded vector blob | `SerializedDataColumn` | `serializedDataColumns` |

The scalar types keep individual values **visible and queryable in the database**.  The array,
image, struct, and serialized types store their values as an **opaque blob**.  That is the real
trade-off: reach for a scalar type whenever the data fits one.

For a small fixed set of string values, prefer `EnumColumn` over `StringColumn` — the proto
comment explicitly nudges this way for memory and storage efficiency.  `EnumColumn` carries
integer codes plus an `enumId`; the code-to-label mapping lives entirely outside this API.

```java
EnumColumn.newBuilder()
    .setName("LINAC:BPM01:ALARM")
    .setEnumId("epics:alarm_status:v2")   // user-defined contract; MLDP does not validate it
    .addAllValues(codes)
    .build();
```

**Array columns** describe one sample's shape once, then flatten every sample into a single
`values` list of length `sample_count × product(dims)`:

```java
DoubleArrayColumn.newBuilder()
    .setName("LINAC:CAM01:PROFILE")
    .setDimensions(ArrayDimensions.newBuilder().addAllDims(List.of(64, 64)))
    .addAllValues(flattened)              // count × 64 × 64 doubles, sample-major
    .build();
```

The proto comment states dimensions are limited to 3.  The ordering convention *within* the
flattened vector (row-major vs. column-major) is not specified by the proto — agree on it with
your consumers.

**Image columns** carry one `bytes` entry per sample under a field named `images`, not `values`:

```java
ImageColumn.newBuilder()
    .setName("LINAC:CAM01:IMAGE")
    .setImageDescriptor(ImageDescriptor.newBuilder()
        .setWidth(1024).setHeight(768).setChannels(1).setEncoding("png"))
    .addAllImages(frames)                 // ByteString per sample
    .build();
```

One `ImageDescriptor` covers the whole column, so every image in it must share width, height,
channels, and encoding.  Mixed formats need separate columns.

**`StructColumn`** is the same shape — one serialized `bytes` per sample, under `values`, plus a
`schemaId` contract.  **`SerializedDataColumn` is fundamentally different**: its `payload` is a
single `bytes` field holding the *entire* column, not one entry per sample.

`enumId`, `schemaId`, and `encoding` (on both `SerializedDataColumn` and `ImageDescriptor`) are
all user-defined and unvalidated.  Version them — `"beam_position:v3"`, not `"beam_position"` —
because nothing in the platform will do it for you.

`DataColumn` / `DataValue` remain in `DataFrame.dataColumns` but are **deprecated for ingestion**
and may be removed in the next API version: they force per-sample JVM allocation and store even
scalar values as one opaque blob.  Do not use them in new ingestion clients.  The deprecation is
ingestion-only; `DataColumn` is still the supported representation for tabular query results and
Annotation Calculations, where an unset `DataValue` oneof expresses a missing value.  The nested
`Structure`, `Array`, and `Image` types are likewise deprecated for ingestion in favor of
`StructColumn`, the `*ArrayColumn` types, and `ImageColumn`.

## Irregular sampling with an explicit timestamp list

When acquisition is event-driven, triggered, or jittered, there is no clock to describe.

```java
TimestampList timestamps = TimestampList.newBuilder()
    .addAllTimestamps(orderedTimestamps)   // acquisition order
    .build();

DataFrame.newBuilder()
    .setDataTimestamps(DataTimestamps.newBuilder().setTimestampList(timestamps))
    .addDoubleColumns(DoubleColumn.newBuilder()
        .setName("LINAC:TRIG01:CHARGE")
        .addAllValues(values))             // position i pairs with timestamp i
    .build();
```

Column values must be in the **same order** as the timestamps — position `i` in the column
corresponds to timestamp `i`.

`DataTimestamps` is a `oneof` named `value`, so calling `setSamplingClock()` and then
`setTimestampList()` silently discards the first.  Use `hasSamplingClock()` / `hasTimestampList()`
or `getValueCase()` when inspecting a frame you did not build.

Prefer `SamplingClock` whenever sampling is genuinely uniform: a timestamp list costs a full
`Timestamp` message per sample, while a clock costs three fields no matter how many samples.

## High-throughput ingestion with `ingestDataStream`

Client-side streaming is the highest-throughput method, because there is no per-request response
traffic at all.  You send a stream of `IngestDataRequest` and receive exactly **one**
`IngestDataStreamResponse`, delivered when you half-close the stream (or on stream error).

```java
StreamObserver<IngestDataRequest> requests = stub.ingestDataStream(responseObserver);

for (YourBatch window : windows) {          // YourBatch is your own type, not an MLDP message
    String requestId = nextRequestId();
    sentRequestIds.add(requestId);          // record every id you send
    requests.onNext(IngestDataRequest.newBuilder()
        .setProviderId(providerId)
        .setClientRequestId(requestId)
        .setIngestionDataFrame(frameFor(window))   // new SamplingClock startTime per window
        .build());
}

requests.onCompleted();                     // without this you never learn anything
```

Reading the single response takes care, because two of its fields sit **outside** the result
`oneof` and are populated on **both** branches:

```java
List<String> received = response.getClientRequestIdsList();     // all ids the service saw
List<String> rejected = response.getRejectedRequestIdsList();   // the subset it rejected

if (response.hasExceptionalResult()) {
    // At least ONE request was rejected -- not necessarily the whole stream.
    // The rejected ids are in `rejected`; everything else was accepted.
} else {
    int accepted = response.getIngestDataStreamResult().getNumRequests();
    // compare against sentRequestIds.size()
}
```

That first branch is the one people misread.  The payload is an `ExceptionalResult` if *any*
single request in the stream was rejected, even if hundreds succeeded.  Do not interpret it as
"the stream failed" — consult `rejectedRequestIds` to find out what actually happened.  Comparing
`clientRequestIds` against the ids you sent also tells you whether the service saw everything you
believe you transmitted.

Then audit asynchronously with a status sweep (below) rather than per request.  That combination
— no per-request response traffic on the hot path, periodic sweep off it — is the production
shape for a facility DAQ front end.

## Per-request acknowledgment with `ingestDataBidiStream`

Use bidirectional streaming when you need to know *promptly* which individual request was
rejected — to retry it, or to re-buffer that specific window — rather than waiting for a summary
at stream end.  The service validates each request on arrival, immediately replies with one
`IngestDataResponse` per request, then queues the request for async handling.  This is the
reference method whose semantics the other two ingestion methods inherit.

Correlate responses back to requests using the echoed `providerId` + `clientRequestId`:

```java
Map<String, IngestDataRequest> inFlight = new ConcurrentHashMap<>();

StreamObserver<IngestDataResponse> responses = new StreamObserver<>() {
    @Override public void onNext(IngestDataResponse response) {
        IngestDataRequest sent = inFlight.remove(response.getClientRequestId());
        if (response.hasExceptionalResult()) {
            retryOrBuffer(sent, response.getExceptionalResult());
        } else {
            IngestDataResponse.AckResult ack = response.getAckResult();
            // verify ack.getNumRows() / getNumColumns() against the frame that was sent
        }
    }
    // onError / onCompleted omitted
};
```

Half-close the request stream at the end of the run and wait for the response stream to complete.
Then still run the status check: an ack is not persistence, so per-request acknowledgment does
**not** relieve you of `queryRequestStatus()`.

## Attaching column provenance and tags

Every column type carries an optional `ColumnMetadata` at field 10, recording where a column came
from and what was done to it.  The metadata is stored with the bucket and comes back inside the
embedded column message when the data is queried.

```java
ColumnMetadata metadata = ColumnMetadata.newBuilder()
    .setProvenance(ColumnProvenance.newBuilder()
        .setSource("NTTable:bpm01/x")      // omit entirely if unknown -- do not set ""
        .setProcess("normalized"))
    .addAllTags(List.of("commissioning"))
    .addAttributes(Attribute.newBuilder().setName("run").setValue("2026-07-20-A"))
    .build();

DoubleColumn.newBuilder()
    .setName("LINAC:BPM01:X")
    .addAllValues(values)
    .setMetadata(metadata)
    .build();
```

Note `Attribute`'s field is `name`, not `key`.

Use this sparingly.  The proto warns explicitly that overuse of per-request column metadata will
burden the ingestion server, which is optimized for continuous PV ingestion.  Column metadata is
*dynamic*, bucket-level information.  Stable per-PV facts — units, description, aliases — belong
in the Annotation Service's PV metadata API (`savePvMetadata`) instead, where they are stored
once rather than on every request.

## Sweeping for ingestion failures

The operational counterpart to the per-request check, and the "find all ingestion errors for
today" use case called out in the proto.  Put both statuses in **one** `StatusCriterion` — values
within a criterion are ORed, while separate criteria are ANDed:

```java
QueryRequestStatusRequest.newBuilder()
    .addCriteria(QueryRequestStatusCriterion.newBuilder()
        .setStatusCriterion(StatusCriterion.newBuilder()
            .addStatus(IngestionRequestStatus.INGESTION_REQUEST_STATUS_REJECTED)
            .addStatus(IngestionRequestStatus.INGESTION_REQUEST_STATUS_ERROR)))
    .addCriteria(QueryRequestStatusCriterion.newBuilder()
        .setTimeRangeCriterion(TimeRangeCriterion.newBuilder()
            .setBeginTime(ts(startOfDay))
            .setEndTime(ts(now))))
    .build();
```

Add a `ProviderIdCriterion` or `ProviderNameCriterion` to narrow the sweep to one provider.

Two things to watch:

- `TimeRangeCriterion` here uses two flat `Timestamp` fields, `beginTime` and `endTime` — it is
  **not** the `common.TimeRange` message introduced for Query V2.  Do not substitute one for the
  other.
- **`queryRequestStatus()` is not paginated.**  Unlike the Annotation Service query methods, it
  has no `limit`, no `pageToken`, and no `nextPageToken`, so a wide time range with no other
  criteria can return a very large result in a single message.  Bound the time range.

Then report per row:

```java
for (RequestStatus s : response.getRequestStatusResult().getRequestStatusList()) {
    log.warn("{} request {} -> {}: {}",
        s.getProviderName(), s.getRequestId(), s.getIngestionRequestStatus(), s.getStatusMessage());
}
```

The repeated field is named `requestStatus` (singular) in the proto, hence
`getRequestStatusList()` in Java.

## Verifying a round trip

Worth doing during commissioning, and after any change to which column type a PV uses.

1. Ingest a frame with a `clientRequestId` you retain.
2. Poll `queryRequestStatus()` by `ProviderIdCriterion` + `RequestIdCriterion` until a row
   appears — it is written asynchronously, so it may not exist immediately.
3. Assert `ingestionRequestStatus == INGESTION_REQUEST_STATUS_SUCCESS`, and check that
   `idsCreated` has one entry per column in the frame.
4. Query the data back and confirm the `DataBucket` you get is what you sent.

On the way back, data arrives as a `DataBucket` — `pvName`, `dataTimestamps`, `providerId`,
`providerName`, and a `dataValues` field whose `oneof values` carries whichever column type was
ingested:

```java
if (bucket.getDataValues().hasDoubleColumn()) {
    DoubleColumn col = bucket.getDataValues().getDoubleColumn();
    col.getValuesList();
    col.getMetadata();     // ColumnMetadata supplied at ingestion round-trips here
}
```

Use `getDataValues().getValuesCase()` to switch on the type generically.  The same `DataBucket`
shape is what `subscribeData()` delivers, so a subscription is an alternative way to observe your
own ingestion live.

## Also worth knowing

- **Only `registerProvider()` is a prerequisite.**  PVs are created implicitly by ingestion; there
  is no PV pre-registration step.
- **`providerId` is validated.**  Hardcoding one or reusing a stale id from a previous deployment
  causes rejection.  Call `registerProvider()` at startup and use what it returns.
- **Rejection reasons** named in the proto include: `providerId` or `clientRequestId` not
  specified, invalid `providerId`, and inconsistent dimensions between the frame's data
  timestamps and its data vectors.
- **`Timestamp.epochSeconds` and `nanoseconds` are both `uint64`**, so pre-epoch times cannot be
  represented.
- **`Int64Column` / `Int32Column` and their array variants use `sint64` / `sint32`** (zigzag)
  wire encoding, efficient for negative values, while `EnumColumn` uses plain `int32`.  Invisible
  from Java, but relevant to wire-size reasoning and to non-Java clients.
- **Field-number ordering in `DataFrame` is not alphabetical**, and `int32ArrayColumns` (22)
  precedes `int64ArrayColumns` (23) — the reverse of the scalar ordering where `int64Columns` (12)
  precedes `int32Columns` (13).  Cosmetic, but a genuine source of copy-paste errors.
- **Array columns put `values` at field 3**, not 2, because `dimensions` occupies field 2.  Only
  matters if you are hand-encoding, but it is a real asymmetry with the scalar columns.
- The proto does not specify how long `requestStatus` documents are retained, nor how quickly they
  appear after an ack.  Treat both as deployment-specific and build your polling accordingly.
