# PV Metadata Cookbook

Worked examples for the PV Metadata API, part of the Annotation Service: cataloguing PVs with
aliases, tags, and attributes, and using that metadata to discover PVs and drive data queries.

Reference documentation: [PV Metadata API](../../README.md#pv-metadata-api).  Shared response,
pagination, criteria, and save-semantics rules live in [conventions.md](conventions.md) and are
not repeated here.

> The final section, [Driving a data query from metadata](#driving-a-data-query-from-metadata),
> uses **Query API V2**, which was added in 1.15.0 and is not available in earlier releases.

### Imports used by the examples

Snippets name generated classes without qualification, for readability.  The query criterion
types nest two levels inside the request:

```java
import com.ospreydcs.dp.grpc.v1.annotation.SavePvMetadataRequest;
import com.ospreydcs.dp.grpc.v1.annotation.QueryPvMetadataRequest;
import com.ospreydcs.dp.grpc.v1.annotation.GetPvMetadataRequest;
import com.ospreydcs.dp.grpc.v1.annotation.DeletePvMetadataRequest;
import com.ospreydcs.dp.grpc.v1.annotation.BulkSavePvMetadataRequest;
import com.ospreydcs.dp.grpc.v1.common.PvMetadata;
import com.ospreydcs.dp.grpc.v1.common.Attribute;

// nested inside the request message
import com.ospreydcs.dp.grpc.v1.annotation.QueryPvMetadataRequest.QueryPvMetadataCriterion;
import com.ospreydcs.dp.grpc.v1.annotation.QueryPvMetadataRequest.QueryPvMetadataCriterion.PvNameCriterion;
import com.ospreydcs.dp.grpc.v1.annotation.QueryPvMetadataRequest.QueryPvMetadataCriterion.TagsCriterion;
import com.ospreydcs.dp.grpc.v1.annotation.QueryPvMetadataRequest.QueryPvMetadataCriterion.AttributesCriterion;
import com.ospreydcs.dp.grpc.v1.annotation.QueryPvMetadataRequest.QueryPvMetadataCriterion.AliasesCriterion;
```

## Contents

- [Model](#model)
- [Cataloguing a newly archived PV](#cataloguing-a-newly-archived-pv) — the create case
- [Updating a PV without losing its existing metadata](#updating-a-pv-without-losing-its-existing-metadata)
  — the single easiest way to destroy data with this API
- [Discovering PVs by tag, attribute, and name](#discovering-pvs-by-tag-attribute-and-name)
- [Auditing which PVs carry an attribute](#auditing-which-pvs-carry-an-attribute)
- [Resolving a legacy name to the canonical PV name](#resolving-a-legacy-name-to-the-canonical-pv-name)
- [Retiring a metadata record](#retiring-a-metadata-record)
- [Bulk-loading a facility PV catalog](#bulk-loading-a-facility-pv-catalog)
- [Driving a data query from metadata](#driving-a-data-query-from-metadata) — Query API V2 (1.15.0+)
- [Also worth knowing](#also-worth-knowing)

## Model

A **`PvMetadata`** record (defined in `common.proto`) is *user-defined* metadata attached to a PV.
It is not derived from the archived samples and it is not required for ingestion — a PV can be
archived and queried with no metadata record at all.  Its purpose is **discovery**: finding the
PVs you care about without knowing their exact canonical names in advance.

`pvName` is the primary key — the canonical PV name.  Around it:

- `aliases` — historical or vendor names for the same PV
- `tags` — keyword labels; the server normalizes these to a **lowercase unique set**
- `attributes` — `Attribute` key/value pairs, where the key field is `Attribute.name`
- `description` — free text
- `createdTime`, `updatedTime` — server-set audit fields
- `modifiedBy` — the *last* writer only; no history is kept

`PvMetadata` is the **read** shape, returned by `queryPvMetadata()` and `getPvMetadata()`.  It is
not the write shape: `SavePvMetadataRequest` lists the client-settable fields flat and
deliberately omits `createdTime` / `updatedTime` so they cannot be forged.

The two ways to read differ in their not-found behavior, and this catches people out:

| Method | Selects by | Nothing matches |
|---|---|---|
| `getPvMetadata()` | `pvNameOrAlias`, a single flat string | **`ExceptionalResult`** |
| `queryPvMetadata()` | `repeated QueryPvMetadataCriterion` | normal result, **empty list** |

Both idioms live in the same API.  Do not assume the query convention ("empty is not an error")
applies to the `get*` call — for `getPvMetadata()`, not-found *is* exceptional.

Note also that `getPvMetadata()` and `deletePvMetadata()` take a plain `string pvNameOrAlias`.
They do **not** use the `oneof key` pattern that `getConfigurationActivation()` uses; do not copy
that shape here.

## Cataloguing a newly archived PV

A PV starts flowing into the archive.  Ingestion works fine without metadata, but nobody can find
the PV except by its exact canonical name.  One `savePvMetadata()` call fixes that.

### 1. Build the record

```java
SavePvMetadataRequest.newBuilder()
    .setPvName("LINAC:VAC:GAUGE:07:PRESSURE")   // required; canonical primary key
    .addAllAliases(List.of("VGC07", "LI_VAC_7"))
    .addAllTags(List.of("vacuum", "linac", "gauge"))
    .addAttributes(Attribute.newBuilder().setName("subsystem").setValue("LINAC"))
    .addAttributes(Attribute.newBuilder().setName("unit").setValue("torr"))
    .setDescription("Cold cathode gauge, linac sector 7")
    .setModifiedBy("pv-catalog-loader")
    .build();
```

Two naming traps in that snippet:

- `Attribute`'s key field is called **`name`**, not `key` — so `setName("subsystem")`.  The
  *criterion* that matches it, however, calls the same thing `key`.  The asymmetry is real.
- Attribute keys must be **unique within a single request**; duplicates are rejected.

Tags are normalized to lowercase, so `"Vacuum"` comes back as `"vacuum"`.  Names and attribute
values are **not** documented as normalized — treat them as case-sensitive.

### 2. Read back the result and verify

`SavePvMetadataResult` carries only `pvName`, echoing the canonical name of the created or
updated record.  To see the full stored record, including the server-set audit fields:

```java
GetPvMetadataRequest.newBuilder()
    .setPvNameOrAlias("LINAC:VAC:GAUGE:07:PRESSURE")
    .build();

// PvMetadata pv = response.getGetPvMetadataResult().getPvMetadata();
// pv.getCreatedTime(), pv.getUpdatedTime(), pv.getTagsList(), pv.getAttributesList()
```

`getPvMetadata()` matches against the canonical `pvName` **or** any alias, so
`setPvNameOrAlias("VGC07")` would return the same record.

## Updating a PV without losing its existing metadata

`savePvMetadata()` is a **full-replace upsert**.  On update, `aliases`, `tags`, `attributes`,
`description`, and `modifiedBy` are *all* replaced by what the request contains.  Fields you omit
are erased, not preserved.  See [full replace](conventions.md#save-semantics-full-replace).

Adding one tag therefore requires read-merge-save:

```java
// 1. read the current record
PvMetadata current = getResponse.getGetPvMetadataResult().getPvMetadata();

// 2. carry EVERY field forward, then add the change
SavePvMetadataRequest.newBuilder()
    .setPvName(current.getPvName())
    .addAllAliases(current.getAliasesList())
    .addAllTags(current.getTagsList())
    .addTags("commissioning")                    // <-- the actual change
    .addAllAttributes(current.getAttributesList())
    .setDescription(current.getDescription())
    .setModifiedBy("ops-console")                // deliberately the new writer
    .build();
```

```java
// WRONG -- erases aliases, existing tags, attributes, and description
SavePvMetadataRequest.newBuilder()
    .setPvName(current.getPvName())
    .addTags("commissioning")
    .build();
```

`modifiedBy` is the one field you normally do *not* copy forward: it should name whoever is making
*this* change.  Because only the last writer is recorded, the previous value is lost either way.

`patchPvMetadata()` exists precisely to remove this read-merge-save dance, but as of 1.14 it is a
reserved placeholder that returns a "not implemented" error, and `PatchPvMetadataRequest`
currently contains only `pvName` — no value fields and no field mask.  Its shape **will** change,
so do not build against it.  Client-side read-merge-save is mandatory today.

There is a race here worth naming: read-merge-save is not atomic, and the API offers no
compare-and-swap, ETag, or optimistic-concurrency field.  Two concurrent updaters can silently
clobber each other's changes.  If several writers maintain the same records, serialize them
yourself.

## Discovering PVs by tag, attribute, and name

This is the API's main event.  Criteria combine per the
[shared rules](conventions.md#query-criteria): **criteria in the outer list are ANDed, values
within one criterion are ORed.**

To find every LINAC vacuum PV whose name starts with `LINAC:VAC:`:

```java
var pvName = QueryPvMetadataCriterion.newBuilder()
    .setPvNameCriterion(PvNameCriterion.newBuilder().addPrefix("LINAC:VAC:"));

var tag = QueryPvMetadataCriterion.newBuilder()
    .setTagsCriterion(TagsCriterion.newBuilder().addValues("vacuum"));

var attr = QueryPvMetadataCriterion.newBuilder()
    .setAttributesCriterion(AttributesCriterion.newBuilder()
        .setKey("subsystem")            // matches Attribute.name
        .addValues("LINAC"));

QueryPvMetadataRequest.newBuilder()
    .addCriteria(pvName)
    .addCriteria(tag)
    .addCriteria(attr)                  // three criteria -> all three must match
    .setLimit(100)
    .setPageToken(pageToken)            // "" for the first page
    .build();
```

Three things the combining rules do not let you say:

- **Two tags simultaneously.**  `TagsCriterion.values` ORs its entries, so one criterion with
  `("vacuum", "linac")` means *either*.  For *both*, emit two separate `TagsCriterion` criteria.
- **`prefix` AND `contains` on the same field.**  Inside `PvNameCriterion` (and the
  identically-shaped `AliasesCriterion`), the `exact` / `prefix` / `contains` sub-lists are ORed
  internally *and* ORed with each other.  For a conjunction, use two `PvNameCriterion` criteria.
- **Negation.**  There is no NOT operator, and no "attribute absent" criterion.

Also: **an empty `criteria` list matches every record.**  It is not an error — it is the
browse-all entry point, for walking the catalog when you have nothing to filter on.  Note that
this is not a way to dump the catalog in a single call: an unset `limit` gets the
server-configured default page size rather than an unbounded result, so browsing everything
means paging through it like any other query.

> Empty-criteria match-all applies from the release paired with
> [dp-service PR #251](https://github.com/osprey-dcs/dp-service/pull/251); earlier releases
> rejected an empty `criteria` list with an `ExceptionalResult`.

Page through the results with the [standard loop](conventions.md#pagination), reading
`getPvMetadataResult().getPvMetadataList()` and continuing while `nextPageToken` is non-empty.
Send the **identical criteria** on every page; changing them mid-pagination is not specified by
the protos, so treat it as undefined.  There is no `totalCount`, so the only way to know the size
of a result set is to page it to the end.

## Auditing which PVs carry an attribute

An `AttributesCriterion` with a `key` and an **empty `values` list** is an existence search: it
matches any record possessing the key regardless of value.  There is deliberately no `keyOnly`
flag.

```java
QueryPvMetadataRequest.newBuilder()
    .addCriteria(QueryPvMetadataCriterion.newBuilder()
        .setAttributesCriterion(AttributesCriterion.newBuilder()
            .setKey("calibration_date")))       // no values -> key-only existence search
    .setLimit(200)
    .build();
```

The flip side is a silent failure mode: if you *meant* to filter by value and the value list ends
up empty — an empty collection passed to `addAllValues()`, say — the query quietly over-matches
every record with the key instead of erroring.

The inverse audit, "which PVs are *missing* `calibration_date`", cannot be expressed: there is no
negation.  Get the set that has the key, and diff it client-side against your known PV list.

## Resolving a legacy name to the canonical PV name

External systems often refer to PVs by an old naming scheme.  Because `getPvMetadata()` matches
aliases as well as canonical names, the common case is one call:

```java
GetPvMetadataRequest.newBuilder()
    .setPvNameOrAlias("VGC07")      // an alias
    .build();

// canonical name for all subsequent data queries:
// response.getGetPvMetadataResult().getPvMetadata().getPvName()
```

Remember that not-found returns an `ExceptionalResult` here.  When that happens, fall back to a
fuzzy search over aliases:

```java
QueryPvMetadataRequest.newBuilder()
    .addCriteria(QueryPvMetadataCriterion.newBuilder()
        .setAliasesCriterion(AliasesCriterion.newBuilder()
            .addPrefix("VGC")
            .addContains("07")))    // sub-lists are ORed: prefix "VGC" OR contains "07"
    .setLimit(50)
    .build();
```

`AliasesCriterion` is a distinct message type from `PvNameCriterion` despite having identical
fields — they are not interchangeable in Java.

The protos do not specify what happens when an alias is ambiguous (the same alias registered on
two PVs), nor whether the server enforces alias uniqueness at save time.  Treat that as
unspecified and avoid relying on either behavior.

## Retiring a metadata record

```java
DeletePvMetadataRequest.newBuilder()
    .setPvNameOrAlias("VGC07")      // canonical name or alias
    .build();

// response.getDeletePvMetadataResult().getPvName()
```

Read the returned `pvName`.  When you deleted by alias, that echo is your only confirmation of
*which* canonical record actually went away — worth checking before assuming the right one did.

Deleting metadata affects **discovery only**.  Archived time-series data for the PV is untouched
and remains queryable by canonical name; a metadata-driven `PvSelector` simply stops selecting
that PV.  If you want an audit trail or rollback path, `getPvMetadata()` first and keep the
record — the API stores no version history.

## Bulk-loading a facility PV catalog

`bulkSavePvMetadata()` is declared but **not yet implemented** as of 1.14; calling it returns an
error response.  Do not design your loader around it.

Today, iterate your source catalog and issue one `savePvMetadata()` per PV — ideally against an
async stub with a bounded number of in-flight requests.  Track failures yourself: each response
identifies only the single `pvName` it concerned.

When the bulk method lands, migration is mechanical, because the request wraps the very same
`SavePvMetadataRequest` objects:

```java
BulkSavePvMetadataRequest.newBuilder()
    .addAllRequests(perPvRequests)   // repeated SavePvMetadataRequest, full-replace each
    .build();
```

Two things to note now so the eventual migration does not surprise you:

- It is a **unary** RPC carrying a repeated list, not a client-streaming call.  There is no
  `StreamObserver` request path, and a very large catalog will run into gRPC message size limits.
- **Partial failure is reported inside the success payload.**  `BulkSavePvMetadataResult` has
  `savedCount` and a `repeated BulkSaveError errors`, each pairing a `pvName` with an
  `ExceptionalResult`.  A caller that checks only `hasExceptionalResult()` will report success
  while records silently failed — you must also assert `getErrorsList().isEmpty()`.

## Driving a data query from metadata

> **Query API V2 (`queryBuckets` / `querySamples` and their streaming forms) was added in 1.15.0.**
> This section does not apply to 1.14 deployments.

The payoff for maintaining PV metadata: `QuerySpec.pvSelector` accepts a
`PvSelector.MetadataQuery` whose criteria mirror `queryPvMetadata()`.  The server resolves the PV
set itself, so you never materialize or ship a name list.

**The criteria types are duplicated, not shared.**  `PvSelector.MetadataQuery.Criterion` (in
`query.proto`) is structurally identical to `QueryPvMetadataRequest.QueryPvMetadataCriterion` (in
`annotation.proto`), but they are distinct Java types — the proto comment states the duplication
is deliberate so each stays self-documenting.  You must rebuild the criteria field by field; you
cannot cast or reuse an instance.  Note too that the nested message is named `Criterion` on the
query side, not `QueryPvMetadataCriterion`.

```java
var criterion = PvSelector.MetadataQuery.Criterion.newBuilder()
    .setTagsCriterion(PvSelector.MetadataQuery.Criterion.TagsCriterion.newBuilder()
        .addValues("vacuum"));

var selector = PvSelector.newBuilder()
    .setMetadataQuery(PvSelector.MetadataQuery.newBuilder()
        .addCriteria(criterion));

var querySpec = QuerySpec.newBuilder()
    .setTimeRange(TimeRange.newBuilder()
        .setBeginTime(ts(shiftStart))
        .setEndTime(ts(shiftEnd)))       // half-open [begin, end)
    .setPvSelector(selector)             // exactly one selector arm must be set
    .build();

QuerySamplesRequest.newBuilder()
    .setQuerySpec(querySpec)
    .setExecutionOptions(ExecutionOptions.newBuilder().setLimit(10_000))
    .build();
```

Page via `getSampleQueryResult().getNextPageToken()` fed back into
`ExecutionOptions.pageToken`.  For the streaming forms (`querySamplesStream()`,
`queryBucketsStream()`), **`pageToken` must be empty** — a non-empty token is rejected with an
`ExceptionalResult`, and streamed responses always carry an empty `nextPageToken` since the
stream itself signals completion.

### One step or two?

`PvSelector` also accepts `pvNameList` and `pvNamePattern` (a regex over names — note there is no
regex option in the *metadata* criteria language).  So there are two ways to get from metadata to
data:

- **One step — `metadataQuery`.**  Use when the metadata predicate *is* the intent ("all vacuum
  PVs in the linac").  The PV set is resolved at query time, so a PV catalogued after you wrote
  the code is picked up automatically.
- **Two steps — `queryPvMetadata()` → collect `pvName`s → `pvNameList`.**  Use when you need to
  inspect, filter, sort, or display the PV set client-side before querying data, or when you want
  a fixed, reproducible PV set that will not drift as the catalog changes.

## Also worth knowing

- All PV metadata RPCs are **unary and synchronous in effect**.  Unlike ingestion there is no
  deferred persistence step and no `queryRequestStatus()` follow-up — the response reflects the
  outcome.
- Query results have **no defined sort order**.  If you need PVs alphabetically, sort client-side
  after paging.
- Every `QueryPvMetadataCriterion` must have exactly one `oneof` arm set; an unset criterion is
  invalid.
- Metadata records are independent of ingestion.  Saving metadata for a PV that has never been
  archived is not an error, and it does not create or reserve anything on the data side.
- `createdTime` / `updatedTime` are server-set and cannot be supplied on save.  `modifiedBy` is
  free-form and unvalidated — the server does not authenticate it.
- See [conventions.md](conventions.md) for response checking, pagination, criteria combining, and
  full-replace save semantics, all of which this API follows without deviation.
