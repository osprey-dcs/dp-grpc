# Provider Registration and Discovery

Worked examples for registering an ingestion data provider (`registerProvider()`, Ingestion
Service) and for finding providers and their ingestion statistics after the fact
(`queryProviders()` and `queryProviderStats()`, Query Service).

> **Verified against:** dp-grpc `rel-1.14.0` (Java `com.ospreydcs:dp-grpc:1.14.0`), and re-checked
> against the current `1.15.0` tree.  All three methods in this recipe are V1 methods present in
> 1.14.0; `ingestion.proto` is unchanged between the two releases, and the provider query messages
> (`QueryProvidersRequest`, `ProviderInfo`, `ProviderStats`) are byte-identical in both.  Nothing
> here depends on the Query API V2 (`queryBuckets`, `querySamples`, and the `TimeRange` message)
> added in 1.15.0.

Reference documentation: [Provider API](../../README.md#provider-api) —
[Provider Registration Methods](../../README.md#provider-registration-methods),
[Provider Query Methods](../../README.md#provider-query-methods), and
[Provider Stats Query Methods](../../README.md#provider-stats-query-methods).  For the
follow-on status check, see
[Ingestion Request Status API](../../README.md#ingestion-request-status-api).

Shared response-checking and criteria rules live in [conventions.md](conventions.md).

## Contents

- [Registering on startup and ingesting](#registering-on-startup-and-ingesting) — the mandatory
  bootstrap for every ingestion client
- [Re-registering to keep descriptive metadata current](#re-registering-to-keep-descriptive-metadata-current)
- [Finding a provider you did not register](#finding-a-provider-you-did-not-register)
- [Auditing what a provider has actually written](#auditing-what-a-provider-has-actually-written)
- [Confirming that ingested data was persisted](#confirming-that-ingested-data-was-persisted)

## Model

A **Provider** is the archive's record of *who* sent a given piece of data.  It has a
`providerName` (the natural key you choose), an opaque server-assigned `providerId`, and
optional descriptive fields: `description`, `tags`, and `attributes`.

Registration is an **upsert keyed on `providerName`**.  Calling `registerProvider()` with a name
that already exists returns the *same* `providerId` and updates the descriptive fields to
whatever the request contained.  Calling it with a new name creates a new provider.  There is no
rename operation — registering under a different name simply creates a second provider.

Every ingestion request must carry a valid `providerId`:

```proto
message IngestDataRequest {
  string providerId = 1;         // must match an id returned by registerProvider()
  string clientRequestId = 2;
  dp.service.common.DataFrame ingestionDataFrame = 3;
}
```

The ingestion methods validate `providerId` and reject requests naming an unknown one.  There is
no implicit provider creation on ingest, which is why registration is a hard prerequisite rather
than a convenience.

Two other distinctions are worth fixing in your head before writing code:

- **Registration state and archive state are different things.**  `queryProviders()` returns
  what you *registered* (name, description, tags, attributes).  `ProviderStats` describes what
  the provider has actually *written* — PV names, bucket counts, first and last bucket times.  A
  freshly registered provider that has ingested nothing should be expected to report `numBuckets`
  0 with unset `firstBucketTime` / `lastBucketTime`; the proto does not state this explicitly, so
  code defensively rather than relying on it.
- **The two halves of this recipe live on different services.**  `registerProvider()` is on
  `DpIngestionService` (`com.ospreydcs.dp.grpc.v1.ingestion`); `queryProviders()` and
  `queryProviderStats()` are on `DpQueryService` (`com.ospreydcs.dp.grpc.v1.query`).  A tool
  that does both needs two stubs.

## Registering on startup and ingesting

### 1. Build the registration request

`providerName` is the only required field.  The rest are descriptive and exist so that other
clients can later *find* this provider without knowing its id.

```java
RegisterProviderRequest.newBuilder()
    .setProviderName("linac-bpm-ioc")             // required; the upsert key
    .setDescription("Linac BPM IOC ingestion bridge")
    .addAllTags(List.of("linac", "bpm"))
    .addAttributes(Attribute.newBuilder()         // common.Attribute: name / value
        .setName("facility")
        .setValue("lcls"))
    .build();
```

Note `dp.service.common.Attribute` uses **`name`** and **`value`**.  The provider query's
`AttributesCriterion` uses **`key`** and `value`.  Mixing these two up is the single easiest
mistake in this area.

### 2. Call `registerProvider()` and read the id

```java
RegisterProviderResponse response = ingestionStub.registerProvider(request);

if (response.hasExceptionalResult()) {
    // getExceptionalResult().getExceptionalResultStatus(), .getMessage() -- abort, do not ingest
    return;
}

String providerId = response.getRegistrationResult().getProviderId();
boolean isNew     = response.getRegistrationResult().getIsNewProvider();
```

`RegistrationResult` also echoes `providerName`.  `isNewProvider` is **informational only** —
log it if you like, but do not branch ingestion logic on it and never treat `false` as a failure.
On any restart against an existing archive it will be `false`, and that is the normal case.

### 3. Cache the id for the process lifetime and use it on every ingest

```java
IngestDataRequest.newBuilder()
    .setProviderId(providerId)                    // from step 2
    .setClientRequestId("bpm-2026-07-20-000123")  // must be unique per provider
    .setIngestionDataFrame(frame)
    .build();
```

Hold `providerId` in memory for the run.  **Do not persist or hardcode it** across deployments —
the contract is to call `registerProvider()` each run and use what comes back.  A cached id from
a rebuilt archive will be rejected at ingest time; a fresh registration call costs one round trip
at startup and cannot go stale.

`clientRequestId` uniqueness is **your** responsibility.  The service deliberately does not check
it, for performance reasons, and duplicates make the request-status lookups in the last section
ambiguous.  A provider-scoped monotonic counter or a timestamp-plus-sequence string works well.

### 4. Understand what the ingest response does and does not tell you

`IngestDataResponse` carries either an `exceptionalResult` (the request failed validation — bad
`providerId`, missing `clientRequestId`, mismatched frame dimensions) or an `ackResult` echoing
`numRows` and `numColumns`.  **The ack means accepted, not persisted.**  Ingestion is
asynchronous; see [Confirming that ingested data was persisted](#confirming-that-ingested-data-was-persisted).

## Re-registering to keep descriptive metadata current

There is no separate "update provider" method — re-registration *is* the update path, and the
proto explicitly says it is safe and recommended to call `registerProvider()` on every client
startup.  Because the upsert keys on `providerName`, repeated calls cannot create duplicates.

Treat it as a **full replace of the descriptive fields**, in the same spirit as the `save*`
methods described in [conventions.md](conventions.md#save-semantics-full-replace): send the
complete desired state every time.

```java
// RIGHT -- the complete current descriptive state, every run
RegisterProviderRequest.newBuilder()
    .setProviderName("linac-bpm-ioc")
    .setDescription("Linac BPM IOC ingestion bridge (v2.3)")
    .addAllTags(List.of("linac", "bpm", "production"))
    .addAllAttributes(currentAttributes)
    .build();
```

Building this request from your client's configuration file rather than from a partial in-code
literal is the practical way to avoid silently dropping a tag that someone added later.

## Finding a provider you did not register

An analysis or monitoring client typically knows a provider by name, tag, or attribute rather
than by opaque id.  `queryProviders()` takes a list of criteria, each one a `oneof`:

```java
QueryProvidersRequest.newBuilder()
    // free text over provider name AND description
    .addCriteria(QueryProvidersRequest.Criterion.newBuilder()
        .setTextCriterion(TextCriterion.newBuilder().setText("bpm")))
    // one tag value per criterion
    .addCriteria(QueryProvidersRequest.Criterion.newBuilder()
        .setTagsCriterion(TagsCriterion.newBuilder().setTagValue("linac")))
    // by provider id, if you happen to have one
    // .addCriteria(QueryProvidersRequest.Criterion.newBuilder()
    //     .setIdCriterion(IdCriterion.newBuilder().setId(providerId)))
    // attribute criterion uses key/value, both scalar strings
    .addCriteria(QueryProvidersRequest.Criterion.newBuilder()
        .setAttributesCriterion(AttributesCriterion.newBuilder()
            .setKey("facility")
            .setValue("lcls")))
    .build();
```

The available criterion types are `idCriterion`, `textCriterion`, `tagsCriterion`, and
`attributesCriterion`.  Criteria in the outer list are **ANDed**
([conventions.md](conventions.md#query-criteria)), so the request above means "text matches bpm
AND tagged linac AND facility=lcls".  `TagsCriterion` holds exactly one `tagValue`, so requiring
two tags means adding two separate criteria.

Reading the result:

```java
for (ProviderInfo info : response.getProvidersResult().getProviderInfosList()) {
    String providerId = info.getId();        // this is what you came for
    info.getName();
    info.getDescription();
    info.getTagsList();
    info.getAttributesList();                // common.Attribute -- name/value
}
```

An empty `providerInfos` list means no match, not an error.

Two limitations to plan around, both differences from the metadata CRUD APIs:

- **The provider criteria are simpler than the annotation-service ones.**  There are no
  `exact` / `prefix` / `contains` sub-lists on `TextCriterion`, and the provider
  `AttributesCriterion` takes a scalar `key` *and* `value` rather than a key plus a repeated
  `values` list.  In particular there is **no key-only existence search** for providers.
- **There is no pagination.**  `QueryProvidersRequest` has no `limit` or `pageToken`, and
  `ProvidersResult` has no `nextPageToken`.  Do not write the paging loop from
  [conventions.md](conventions.md#pagination) around this call; you get the whole matching set in
  one response.

The behavior of `queryProviders()` with an **empty criteria list** is not specified in the proto
comments.  Do not assume it means "return every provider" without checking against your server
deployment.

## Auditing what a provider has actually written

Once you have a `providerId`, `queryProviderStats()` answers "is this provider actually writing
data, for which PVs, and how recently?"

```java
QueryProviderStatsRequest.newBuilder()
    .setProviderId(providerId)     // the only field
    .build();
```

The result is a **repeated** list even though the request names exactly one provider:

```java
List<ProviderStats> stats = response.getStatsResult().getProviderStatsList();
if (stats.isEmpty()) {
    // unknown provider id, or no stats available -- handle, do not call get(0)
    return;
}
ProviderStats s = stats.get(0);
s.getId();                  // the provider id these stats belong to
s.getNumBuckets();          // int32
s.getPvNamesList();         // repeated string
s.getFirstBucketTime();     // common.Timestamp; expected unset if nothing ingested
s.getLastBucketTime();
```

Guard the empty case explicitly.  The proto does not state whether an unknown `providerId`
produces an `ExceptionalResult` or simply an empty `providerStats` list, so handle both.

The stalled-provider check is the main reason to call this: compare `lastBucketTime` against now
and alert when the gap exceeds the provider's expected cadence.  Remember that `numBuckets` 0
with unset bucket times is the correct state for a provider that registered but has not yet
ingested — it is not an error condition on its own.

### Prefer the embedded stats when surveying many providers

`ProviderInfo` carries a `providerStats` field (field 6) holding the same `ProviderStats`
message.  For a dashboard with one row per provider, issue a single `queryProviders()` call and
read the embedded stats rather than making an N+1 round trip per provider:

```java
for (ProviderInfo info : response.getProvidersResult().getProviderInfosList()) {
    ProviderStats s = info.getProviderStats();
    render(info.getName(), s.getNumBuckets(), s.getLastBucketTime());
}
```

Reach for `queryProviderStats()` only when you already hold a `providerId` and need nothing but
the statistics.

## Confirming that ingested data was persisted

Because the ingest ack is acceptance-only, the sole way to learn whether the data actually landed
is `DpIngestionService.queryRequestStatus()`, which reads the archive's request-status records.

```java
QueryRequestStatusRequest.newBuilder()
    .addCriteria(QueryRequestStatusCriterion.newBuilder()
        .setProviderIdCriterion(ProviderIdCriterion.newBuilder()
            .setProviderId(providerId)))
    .addCriteria(QueryRequestStatusCriterion.newBuilder()
        .setStatusCriterion(StatusCriterion.newBuilder()
            .addStatus(IngestionRequestStatus.INGESTION_REQUEST_STATUS_REJECTED)
            .addStatus(IngestionRequestStatus.INGESTION_REQUEST_STATUS_ERROR)))
    .addCriteria(QueryRequestStatusCriterion.newBuilder()
        .setTimeRangeCriterion(TimeRangeCriterion.newBuilder()
            .setBeginTime(ts(windowStart))
            .setEndTime(ts(now))))
    .build();
```

That shape is the **failure sweep**: all criteria are ANDed, and the multiple values inside the
single `StatusCriterion` are ORed, so it means "requests from this provider, in this window, that
were rejected or errored".  Running it periodically is cheaper than checking every request
individually.

To check one specific request instead, AND a `ProviderIdCriterion` (or `ProviderNameCriterion`)
with a `RequestIdCriterion`.  Note the naming seam: the field you set on the ingest request is
`clientRequestId`, but the criterion field and the returned status field are both named
`requestId`.  They hold the same value.

```java
for (RequestStatus rs : response.getRequestStatusResult().getRequestStatusList()) {
    rs.getRequestId();                 // == the clientRequestId you sent
    rs.getIngestionRequestStatus();    // SUCCESS / REJECTED / ERROR
    rs.getStatusMessage();
    rs.getIdsCreatedList();            // bucket ids written for this request
}
```

`RequestStatus` also carries `requestStatusId`, `providerId`, `providerName`, and `updateTime`.

As a coarse cross-check, `queryProviderStats()` should show `numBuckets` and `lastBucketTime`
advancing to reflect newly written buckets — useful as a health signal, though it cannot tell you
*which* request failed.

## Also worth knowing

- **`registerProvider()` is idempotent by `providerName`, and only by `providerName`.**  Two
  clients configured with the same name share one provider record and one id, and each
  re-registration overwrites the other's description and tags.  Give each independent ingestion
  process a distinct name.
- **There is no delete or rename for providers** in this API.  A misnamed provider stays in the
  archive; registering the correct name creates a second one.
- **The `oneof` field numbers in `QueryProvidersRequest.Criterion` are non-contiguous** —
  `idCriterion = 10`, then `textCriterion = 14`, `tagsCriterion = 15`, `attributesCriterion = 16`.
  Numbers 11–13 are unused but not formally reserved.  This matters only if you are editing the
  proto: do not renumber.
- **`queryProviderStats()` was renamed from `queryProviderMetadata()`.**  No RPC by the old name
  exists any longer; it survives only in a note on the `queryProviderStats()` comment in
  `query.proto`.  The rename was deliberate: the method returns archive-derived *ingestion
  statistics*, not user-defined provider metadata.  The user-defined metadata is on
  `ProviderInfo` from `queryProviders()`.
- **`ProviderStats.numBuckets` is `int32`**, not `uint32` or `int64`.
- All three responses carry `responseTime` outside the `oneof` and must be checked with
  `hasExceptionalResult()` before the success payload is read — see
  [conventions.md](conventions.md#checking-responses).
