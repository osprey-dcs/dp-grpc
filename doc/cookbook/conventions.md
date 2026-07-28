# API Conventions

Patterns that recur throughout the MLDP API.  Recipes in this cookbook link here rather than
repeating them.

For the design rationale behind these conventions, see
[Data Platform API Conventions](../../README.md#data-platform-api-conventions) in the main README.

## Checking responses

Every response message carries a `oneof result` with either an `ExceptionalResult` or a
method-specific success payload.  Always check which is set before reading:

```java
if (response.hasExceptionalResult()) {
    ExceptionalResult error = response.getExceptionalResult();
    // error.getExceptionalResultStatus(), error.getMessage()
    return;
}
// safe to read the success payload
```

An **empty query result is not an error**.  A query that matches nothing returns its normal
success payload with an empty list, not an `ExceptionalResult`.  Reserve exceptional handling for
rejected requests and server errors.

This holds across every query method in the API.  Some older proto comments in `query.proto` and
`annotation.proto` list "no data matching query" among their exceptional-result cases; those
comments predate the current behavior and are stale.

Every response also carries `responseTime`, the time the server generated the response.

## Pagination

Query methods that can return many records use a uniform paging scheme:

- Request: `uint32 limit` and `string pageToken` (empty for the first page)
- Result: `string nextPageToken` — non-empty when more pages are available

```java
// cookbook:partial Foo is a stand-in for any entity type
String pageToken = "";
do {
    var request = QueryFooRequest.newBuilder()
        .addAllCriteria(criteria)
        .setLimit(100)
        .setPageToken(pageToken)
        .build();

    var result = send(request).getQueryFooResult();
    process(result.getFoosList());
    pageToken = result.getNextPageToken();
} while (!pageToken.isEmpty());
```

There is deliberately **no `totalCount` field** — computing it requires an expensive separate
count query.  Do not expect to know the result size in advance.

## Query criteria

Structured queries take `repeated *Criterion criteria`.  The combining rules are uniform:

- **Multiple criteria in the outer list are ANDed**
- **Multiple values within a single criterion are ORed**

So to require two tags simultaneously, use two separate `TagsCriterion` entries rather than one
criterion with two values.

Name and alias criteria typically offer `exact`, `prefix`, and `contains` sub-lists, all ORed
together.

`AttributesCriterion` takes a required `key` and an optional `values` list.  An **empty `values`
list means key-only** (existence) search: match any record possessing the key, regardless of
value.

## Save semantics: full replace

Methods named `save*` are **full-replace upserts**, not partial updates.  Every field is replaced
by what the request contains; omitted fields are cleared, not preserved.

When updating an existing record, read it first and carry forward every field you intend to keep:

```java
// cookbook:partial Foo is a stand-in for any entity type
// WRONG -- erases description, tags, and attributes
SaveFooRequest.newBuilder()
    .setFooId(existing.getFooId())
    .setEndTime(ts(now))
    .build();

// RIGHT -- complete desired state
SaveFooRequest.newBuilder()
    .setFooId(existing.getFooId())
    .setEndTime(ts(now))
    .setDescription(existing.getDescription())
    .addAllTags(existing.getTagsList())
    .addAllAttributes(existing.getAttributesList())
    .build();
```

Corresponding `patch*` methods are defined in the protos to reserve the partial-update pattern,
but are **not yet implemented** — calling one returns an error response.  The same applies to
`bulkSave*` methods.

## Server-set audit fields

`createdTime` and `updatedTime` are set by the server.  They appear on domain messages returned
by `get*` and `query*`, but are **not accepted as input** — `Save*Request` messages deliberately
list only client-settable fields rather than embedding the full domain message.

Most save requests accept an optional `modifiedBy` string identifying the actor or service making
the change.

## Time

`Timestamp` (in `common.proto`) has `epochSeconds` and `nanoseconds` fields.

Time ranges in the API are **half-open**: `[beginTime, endTime)`.  The begin time is included,
the end time excluded.  This makes adjacent intervals compose cleanly — one interval's `endTime`
can equal the next one's `startTime` with no gap and no overlap.

Note that *bucket selection* in data queries is an overlap test rather than containment: a bucket
is returned when `bucket.firstTime < endTime AND bucket.lastTime >= beginTime`, so boundary
buckets may extend past the requested range.  Sample-oriented query methods trim to the exact
range; bucket-oriented ones do not.

## Naming

- Every method takes exactly one request message and returns one response message, named after
  the method: `saveFoo` → `SaveFooRequest` / `SaveFooResponse`.
- The success payload nested inside a response is named `*Result`:
  `SaveFooResponse.SaveFooResult`.
- Messages used by more than one service live in `common.proto`; service-specific messages live
  in that service's proto file.
