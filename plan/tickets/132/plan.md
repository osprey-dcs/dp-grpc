# Plan: Modernize the DataSets and Annotations APIs (issue #132)

- **Ticket**: [osprey-dcs/dp-grpc#132](https://github.com/osprey-dcs/dp-grpc/issues/132) —
  the authoritative scope statement; this plan records the design rationale and work breakdown.
- **Parent epic**: [osprey-dcs/data-platform#83](https://github.com/osprey-dcs/data-platform/issues/83)
- **Companion ticket**: [#143](https://github.com/osprey-dcs/dp-grpc/issues/143) —
  remove `ValueStatus` from `DataValue` (same breaking release)
- **Status**: decisions settled 2026-08-26; revised 2026-08-27 after dp-service
  verification (see [Verified dp-service behavior](#verified-dp-service-behavior));
  implementation not started
- **Companion document**: [`dp-service-handoff.md`](dp-service-handoff.md) — what dp-service
  must implement, written from the verified findings below
- **Supersedes**: dp-grpc #130, #131; dp-service #210, #211, #214 (all closed with pointers)

The datasets and annotations APIs are the oldest generation in `DpAnnotationService`. This
work brings them up to the modern CRUD conventions established by the PV metadata, machine
configuration / activation, and sample status APIs, and extends two adjacent mechanisms the
modernization naturally touches: column provenance and export.

## Contents

1. [Settled decisions and rationale](#settled-decisions-and-rationale)
2. [Proto design](#proto-design)
3. [Verified dp-service behavior](#verified-dp-service-behavior)
4. [Work breakdown](#work-breakdown)
5. [Follow-ons](#follow-ons)

## Settled decisions and rationale

**D1 — Breaking changes in place.** Method names are retained; message shapes and semantics
change incompatibly. The API is effectively beta and only the latest release is supported.
"No usage that matters" is a deliberate finding, not an assumption: the dataset and annotation
methods have no production consumers — usage is limited to dp-service's own tests and to demo
code. Known consumers to coordinate: dp-service (handler and test updates), dp-python-lib (stub
regeneration and client library), and dp-desktop-app (confirm whether it consumes `Annotation`,
`comment`, or the nested read-side type; see work breakdown step 10). A Query-V2-style "new
methods alongside old" approach was rejected because the modern method names are already taken
by these methods. Release notes flag the breakage.

**D2 — Complete the CRUD set; no `bulkSave*`.** Add `getDataSet` / `getAnnotation` /
`deleteDataSet` / `deleteAnnotation` (implemented) and `patchDataSet` / `patchAnnotation`
(deferred stubs per the standard pattern). `bulkSave*` is omitted deliberately rather than
stubbed: datasets and annotations are not bulk-imported from external systems, unlike PV
metadata and configuration activations. This is not a one-way door — adding a `bulkSave*` RPC
later is additive and wire-compatible, so the omission should not be re-litigated on the
grounds that this is the last breaking release for a while.

**D3 — Opaque server-generated ids remain the primary key.** Names are not unique for either
entity, so the natural-key approach of the other metadata APIs does not apply, and the
`clientActivationId`-style optional client key has no external-system use case here.
`get*` / `delete*` / `patch*` take the id.

**D4 — Entity field additions.** Both entities gain server-set `createdTime` / `updatedTime`
and last-writer `modifiedBy` (parity with every other entity). `DataSet` gains `tags` /
`attributes` for cataloging parity. `ownerId` is kept on both — ownership is a distinct
concept from last-writer identity. `Annotation.comment` is renamed `description`
(consistency), and `Annotation` is hoisted from its response nesting to a top-level message
(required for reuse by `getAnnotation`).

**D5 — Query results carry references, not embedded content.** The denormalized
`repeated DataSet dataSets` content field in annotation query results is dropped, as is the
embedded `Calculations` content (see D14); `queryAnnotations` returns `dataSetIds` and
`calculationsId` only. `getDataSet` / `getCalculations` retrieve content on demand, and
`getAnnotation` returns calculations inline as a one-hop convenience.

This is the largest performance fix in the ticket, not a normalization tidy-up. Verified
current behavior: `QueryAnnotationsDispatcher` issues one `findDataSet` round-trip *per dataset
id per annotation* — serially, with no `$in` batching, no caching, and no de-duplication across
annotations sharing a dataset — and one `findCalculations` per annotation, then embeds every
data frame, column, and value into each returned annotation. Combined with `queryAnnotations`
having no paging at all today, a broad query fans out into thousands of point lookups and one
unbounded protobuf message.

Batch retrieval replaces the denormalization: `queryDataSets`'s `IdCriterion` becomes
`repeated`, so a client listing N annotations fetches the referenced datasets in one call
rather than N. State this explicitly in the cookbook and the dp-service handoff — without it,
implementors will reach for N+1.

**D6 — Flat save requests.** `SaveDataSetRequest` stops embedding the `DataSet` domain
message (which now contains server-set audit fields) and lists client-settable fields
explicitly, per the pattern. Both save requests carry the full-replace warning and the
server-set-timestamps `Note:`.

**D7 — Paging semantics unified across all six paged annotation queries** (resolves the
decision recorded in dp-service#210). The count is six, not five: `querySampleStatuses` is also
paged and already documents `0 = server-selected default`, which is the precedent this decision
generalizes rather than a new invention.

Verified current state, which differs from the "unbounded ×3, default-100 ×2" recorded in
dp-service#210:

| Query | Paged today | Unset/zero `limit` |
|---|---|---|
| `queryPvMetadata` | yes | **unbounded** |
| `queryConfigurations` | yes | default 100 |
| `queryConfigurationActivations` | yes | default 100 |
| `querySampleStatuses` | yes | server-selected default (already documented) |
| `queryDataSets` | **no paging fields at all** | n/a |
| `queryAnnotations` | **no paging fields at all** | n/a |

So this is three distinct kinds of change: a behavior change for `queryPvMetadata`, a
documentation fix for the two configuration queries (none of the three currently document what
unset `limit` means), and **new API surface** for datasets and annotations.

- Unset/zero `limit` = server-configured default page size; clients must follow
  `nextPageToken`. This changes `queryPvMetadata` from unbounded — acceptable in a breaking
  release — and bounds the server-side result materialization problem.
- Malformed `pageToken` = rejected with an `ExceptionalResult`, matching `DpQueryService`,
  replacing the current silent restart-at-page-one. **This requires changing the token format.**
  Tokens are currently Base64 of a decimal skip offset, so any Base64-decodable integer string is
  structurally valid and there is nothing to reject. Adopt the opaque token type
  `querySampleStatuses` already uses (`SampleStatusPageToken`) across all paged queries; without
  that, narrow the claim to "undecodable tokens are rejected."
- `querySampleStatusesStream` keeps its distinct rule — `pageToken` must be empty, and a
  non-empty token is rejected. The blanket malformed-token rule must not be worded so as to
  contradict it.

**D8 — Ordering is API contract for all six queries** (resolves #130 and its open question).
This is mostly *documenting behavior that already exists*: every query verified already applies
an explicit ascending sort — `_id` for datasets and annotations, `pvName` for PV metadata,
`name` for configurations, `startTime` for activations. There are currently zero `Ordering:`
comment blocks in the protos, so the work is comment-level.

- `pvName` / `configurationName` ascending — both backed by unique indexes, stable under
  skip-paging.
- **`id` ascending** for datasets and annotations (unique key, safe for skip-paging,
  approximately insertion order) — matches the existing `_id` sort.
- `startTime` ascending for configuration activations — **`startTime` is not unique**, and with
  skip-based paging ties can drop or duplicate rows at page boundaries. Add a deterministic
  tiebreaker (`startTime`, then `configurationName`, then id) rather than documenting an
  unstable sort as contract.

Offset paging is only stable under a deterministic sort, so each query gets the standard
`Ordering:` comment block.

**D9 — Delete referential integrity mirrors `deleteConfiguration`.** `deleteDataSet` is
rejected while annotations reference the dataset in `dataSetIds` (a containment-strength
association). `deleteAnnotation` is not blocked by incoming `annotationIds` or
column-provenance references — those are soft associations and may dangle.

Because D11 introduces a new class of dangling reference (a provenance link to a
`calculationsId` whose owning annotation was deleted), the proto comments must state the
resolution contract rather than merely noting that dangling is permitted: **a soft link that
resolves to nothing means the referenced record was deleted, and readers must tolerate it.**
Applies to `annotationIds` and to `ColumnProvenance.derivedFrom` links alike. Deleting an
annotation deletes its Calculations with it (D14), so provenance links into a deleted
annotation's calculations dangle by the same rule.

**D10 — Calculations adopt `common.DataFrame`.** `CalculationsDataFrame` becomes `name` +
`DataFrame`, gaining the typed scalar/array/image/struct/serialized columns and per-column
`ColumnMetadata`. Sparsity model: a sparse calculation gets its own frame with its own
(sparse) time axis — frames are cheap, and columns are dense on their frame's axis.
`DataColumn` remains reachable through `DataFrame.dataColumns` as an escape hatch for
heterogeneous or missing-value columns. `CalculationsSpec` keeps its `calculationsId` key and
its name-based column selection, which D14 makes reachable in one hop. Calculations remain
owned by the annotation — one-time analysis products belong with their descriptive context,
outside the PV namespace; continuously-computed derived streams belong in ingestion as ordinary
PVs — but they are separately stored and separately readable (D14).

**This obligates export-side work in dp-service; it is not a proto-only change.** Once a client
can put a `DoubleColumn` in a calculation, the storage and export paths must accept it.
`CalculationsDataFrameDocument` stores `List<DataColumnDocument>` with no typed arm, and both
export writers assume that shape. Three files change:

- `CalculationsDataFrameDocument` — adopt the polymorphic `ColumnDocumentBase` the bucket path
  already uses. Nothing new needs inventing: `BucketDocument` solved this, and HDF5 export
  already writes `toProtobufColumn().toByteArray()` with an encoding tag.
- `TabularDataUtility.addCalculationsToTable` — needs the scalar-vs-non-scalar narrowing that
  `addBucketToTable` already performs, throwing `NonScalarColumnException` for array / image /
  struct columns.
- `CalculationsDocument.frameColumnNamesMap()` and its diff helpers — typed equivalents, since
  they drive `ExportDataJobBase`'s filter validation.

Proto-visible consequence to document on `exportData` rather than surfacing as a runtime error:
**a calculation containing array / image / struct columns can be exported to HDF5 but not to
CSV or XLSX.** This is already true for datasets, so the restriction is consistent rather than
new.

**D11 — Column provenance extends `common.ColumnProvenance`.** A structured, repeated
`derivedFrom` link list rides inside the `ColumnMetadata` already carried by every column
message, so one mechanism serves annotation-calculations columns and ingestion-side derived
data alike. Calculations columns are addressed by **calculationsId** + frameName + columnName,
the same key `CalculationsSpec` uses and the same key `queryAnnotations` now returns (D14), so
provenance and export share one addressing scheme resolvable in a single `getCalculations` hop.

An earlier draft addressed them by `annotationId`, on the rationale that the annotation was the
only retrievable unit. D14 removes that constraint, and `calculationsId` is the more direct link
— it resolves without loading the annotation's descriptive payload. The counter-argument, that
an `annotationId` link carries ownership context and degrades more informatively when the target
is deleted, is weak given D9 already accepts dangling soft links; consistency wins.

Links are stored, not validated or interpreted — the existing provenance stance. Free-form
`source` / `process` are retained (human description vs. machine-traversable link). No wire
or memory cost when unused: absent message fields and empty repeated fields encode to zero
bytes, and the generated Java holds null / shared-empty references until populated. The
extension is a single edit to `ColumnProvenance` that reaches all 16 column message types
carrying `ColumnMetadata` — that reach is the point of siting it there.

**D12 — Ad-hoc export via inline `DataBlock`s.** `ExportDataRequest` gains
`repeated DataBlock dataBlocks` — the same building block a DataSet contains — treated
server-side as a transient dataset. At least one of `dataSetId` / `dataBlocks` /
`calculationsSpec` required; sources combine in a single export. Full V2-`QuerySpec`-driven
export is deferred (see Follow-ons): it embeds query execution inside export and raises the
question of where `QuerySpec` lives (query.proto vs. common.proto).

**D13 — `ValueStatus` removal is a separate ticket (#143), same release.** Keeps this diff
reviewable and gives the removal its own release-notes line. Blast radius in production code is
small, as assumed: in dp-service only `IngestionClient.java` references it, no server-side code
reads or writes `valueStatus` (it rides opaquely inside serialized `DataValue`s), and archived
blobs containing field 15 still parse (unknown field). `reserved 15;` and
`reserved "valueStatus";` prevent reuse.

Verification added one thing the original estimate missed: **four test files also use it**, and
the removal PR will not build until they are updated. `IngestionClientTest.java`,
`IngestionTestBase.java`, `QueryTestBase.java` (comment only), and
`QueryDataValueStatusIT.java` — the last being a dedicated ingest/query round-trip integration
test for `ValueStatus` that should be deleted outright rather than adapted. List these in the
#143 handoff.

**D14 — Calculations become a first-class readable entity.** Calculations are already stored in
their own MongoDB collection with their own id; the annotation document holds a `calculationsId`
reference, and the query dispatcher re-embeds the full object into the response. The anomaly was
never the storage — it was that a separately-stored entity had no API of its own, which is what
forced both the embedding (no way to fetch it) and the cookbook's persist-the-id-out-of-band
workaround (no way to obtain it without a round-trip).

Resolution: expose the storage that already exists, and make `calculationsId` the single
addressing key across the API.

- `getCalculations(calculationsId)` — **new**, implemented. Fetches one Calculations object
  standalone. This is the GUI case: list annotations, click one, fetch exactly that calculation
  without loading anything else.
- `queryAnnotations` returns `calculationsId` only (D5). It is already a stored reference on the
  annotation document, so it costs one string and zero round-trips, and it doubles as the
  presence indicator — strictly better than a `bool hasCalculations`.
- `getAnnotation` returns calculations content inline, as a one-hop convenience for the common
  "open this annotation" case.
- `CalculationsSpec` is unchanged, keyed on `calculationsId` (D10). The inconsistency flagged in
  review resolves not by changing `CalculationsSpec` but by making its key reachable.
- `ColumnProvenance` links use `calculationsId` (D11). One key, three consumers.

Deliberately **not** added, so the asymmetry reads as intentional rather than incomplete — state
each in the proto comments:

- No `saveCalculations` — calculations are created and replaced through `saveAnnotation`.
- No `deleteCalculations` — lifecycle stays with the owning annotation. A standalone delete
  would leave an annotation pointing at nothing; D9's rules cover removal.
- No `queryCalculations` — discovery goes through annotations. The motivating use case is
  click-through from a listing, which `getCalculations` covers alone. Adding the RPC later is
  additive; it is omitted rather than stubbed for the same reason as `bulkSave*` in D2.

Ownership and transfer granularity are separate concerns. Calculations do not stand alone
*semantically* — they are meaningless without the annotation's descriptive context, which is why
the annotation owns their lifecycle. That does not imply a client fetching 50 annotations wants
50 full column sets inline. Conflating the two produced the current shape.

**D15 — Criteria combination becomes uniformly AND; this is a real semantic change.** The
per-criterion "Or" comments in the current protos were assumed stale. They are accurate.
dp-service uses a two-bucket scheme — a global bucket ANDed internally, a criteria bucket ORed
internally, and the two ANDed together — with *different* bucket assignments per method:

- `queryDataSets`: `(id AND owner) AND (text OR pvName)`
- `queryAnnotations`: `(id AND owner AND dataSet AND text) AND (annotationIds OR tags OR attributes)`

`TextCriterion` is ORed for datasets and ANDed for annotations. Moving to the modern all-ANDed
convention is therefore a behavior change, not a comment correction. Most consequential: two
`TagsCriterion` entries currently OR together, so a client asking for `tag=A, tag=B` gets
"either" today and "both" afterward — silently, with no error. Accepted per D1 (no production
consumers), but it needs its own release-notes line and a prominent callout in the dp-service
handoff rather than a footnote.

**D16 — `TextCriterion` is a MongoDB `$text` index search, with consequences for the contract.**
Both text criteria compile to `Filters.text(...)` against a collection-level text index, not a
per-field regex. Two structural consequences the proto comments must reflect:

- **`$text` cannot be field-scoped at query time.** Describing `TextCriterion` as searching
  "name + description" is not implementable as a per-field contract — it searches whatever the
  index covers. The annotations index today covers `name` + `comment` + **`event.description`**,
  so the existing "name and comment fields" comment is already stale in a third way — and
  `event.description` corresponds to the `eventMetadata` field that was **removed from the
  proto**, so the index is searching a field the API no longer exposes. Drop it in the rebuild.
- **MongoDB permits one text index per collection**, so changing the searchable field set is an
  index migration, not an additive change. The `comment` → `description` rename (D4) forces an
  annotations text-index rebuild regardless; fold the field-set decision into that migration and
  document it in the handoff.

## Proto design

### Service methods after modernization

| Method | Change |
|---|---|
| `saveDataSet` / `saveAnnotation` | modernized: flat request, full-replace semantics documented |
| `getDataSet` / `getAnnotation` | **new**: lookup by id; not-found → `ExceptionalResult` |
| `queryDataSets` / `queryAnnotations` | modernized: criteria conventions, pagination, ordering |
| `deleteDataSet` / `deleteAnnotation` | **new**: delete by id (referential rules per D9) |
| `patchDataSet` / `patchAnnotation` | **new**: deferred stubs (NOT YET IMPLEMENTED) |
| `getCalculations` | **new**: lookup by `calculationsId` (D14); not-found → `ExceptionalResult` |
| `exportData` | extended: inline `dataBlocks` source (D12); typed-column support (D10) |

No `saveCalculations` / `deleteCalculations` / `queryCalculations` — see D14 for why each is
omitted rather than stubbed.

### Entities

```proto
message DataSet {
  string id = 1;                 // server-generated primary key
  string name = 2;               // required; not unique
  string ownerId = 3;            // required
  string description = 4;        // optional
  repeated DataBlock dataBlocks = 5;             // required
  repeated string tags = 6;                      // NEW
  repeated dp.service.common.Attribute attributes = 7; // NEW
  dp.service.common.Timestamp createdTime = 8;   // NEW, server-set
  dp.service.common.Timestamp updatedTime = 9;   // NEW, server-set
  string modifiedBy = 10;                        // NEW, last writer
}

message Annotation {             // hoisted to top level
  string id = 1;                 // server-generated primary key
  string ownerId = 2;            // required
  repeated string dataSetIds = 3;    // required, ids only (D5)
  string name = 4;               // required
  repeated string annotationIds = 5; // optional soft associations
  string description = 6;        // renamed from comment (D4)
  repeated string tags = 7;
  repeated dp.service.common.Attribute attributes = 8;
  string calculationsId = 9;     // reference; content via getCalculations (D5, D14)
  Calculations calculations = 13; // populated by getAnnotation only; empty in query results
  dp.service.common.Timestamp createdTime = 10;  // NEW, server-set
  dp.service.common.Timestamp updatedTime = 11;  // NEW, server-set
  string modifiedBy = 12;                        // NEW, last writer
}
```

(Field numbering above is indicative; final numbering assigned at implementation. Both
messages stay in annotation.proto — no cross-service need.)

One `Annotation` message serves both `queryAnnotations` and `getAnnotation`, with `calculations`
populated only by the latter (D5). The alternative — separate summary and detail messages —
was rejected as more surface for the same information; `calculationsId` is always present, so a
client can tell "no calculations" from "not fetched" by whether the id is empty. State this
explicitly in the field comment, since a populated id with empty content is otherwise
ambiguous.

### Save requests

`SaveDataSetRequest` flat fields: `id` (optional: absent = create, present = full-replace
update), `name`, `ownerId`, `description`, `dataBlocks`, `tags`, `attributes`, `modifiedBy`.
`SaveAnnotationRequest`: as today, with `comment` → `description` and `modifiedBy` added, and
`calculations` retained — calculations are written through `saveAnnotation`, since D14 adds no
`saveCalculations`. Full-replace applies to them as it does to every other field: an update
omitting `calculations` clears them. Call this out specifically in the full-replace warning,
because silently discarding a calculation is the most costly instance of the general rule.

`SaveAnnotationResult` should return `calculationsId` alongside `annotationId` when the request
carried calculations, so the export and provenance key is available without a round-trip — the
gap that produced the cookbook's persist-it-out-of-band advice.

Both carry the standard full-replace warning and server-set-audit `Note:`. Get/delete/patch
request and response messages follow the PV metadata shapes mechanically (id in, id or
record out, `oneof result` throughout).

### Query criteria

Standard semantics (criteria ANDed — a change from current server behavior, see D15; values
within a criterion ORed; name criteria with `exact` / `prefix` / `contains` sub-lists all ORed;
`AttributesCriterion` with empty `values` = key-only search):

- `queryDataSets`: `IdCriterion` (repeated — the batch-fetch path that replaces the dropped
  `dataSets` denormalization, D5), `OwnerCriterion` (repeated), `NameCriterion`
  (exact/prefix/contains), `TextCriterion`, `PvNameCriterion` (repeated), `TagsCriterion`,
  `AttributesCriterion`.
- `queryAnnotations`: `IdCriterion` (repeated), `OwnerCriterion`, `DataSetsCriterion`
  (repeated), `AnnotationsCriterion` (repeated), `NameCriterion`, `TextCriterion`,
  `TagsCriterion`, `AttributesCriterion`.

`TextCriterion` is deliberately described without a field list: it is a collection-level
`$text` index search and cannot be scoped to named fields at query time (D16). Document it as
"full-text search over the record's indexed text fields" and state which fields the index
covers, rather than implying per-field control the implementation cannot provide.

Requests gain `uint32 limit` + `string pageToken`; results gain `string nextPageToken`; no
`totalCount`. All six paged annotation queries get `Pagination:` and `Ordering:` comment
blocks documenting D7/D8 — including `querySampleStatuses`, which is already paged and needs
only the `Ordering:` block and wording alignment.

### ColumnProvenance extension (common.proto)

```proto
message ColumnProvenance {
  string source = 1;   // existing free-form origin description (kept)
  string process = 2;  // existing free-form processing description (kept)

  // Structured links to the column(s) this column was derived from.
  // Repeated because a derived column may have multiple inputs
  // (e.g., a difference of two PVs).  Stored, not validated or
  // interpreted by the MLDP — same stance as source/process.
  repeated ColumnSource derivedFrom = 3;

  message ColumnSource {
    // Named "origin", not "source": ColumnProvenance already has a
    // string field named source, and a nested oneof of the same name
    // yields a confusing provenance.getSource() / getOriginCase() pair
    // in the generated Java.
    oneof origin {
      string pvName = 1;                         // archived PV time-series data
      CalculationsColumn calculationsColumn = 2; // a column of a Calculations object
    }
    TimeRange timeRange = 3; // optional: the source interval consumed
  }

  message CalculationsColumn {
    string calculationsId = 1; // the Calculations object (D11, D14)
    string frameName = 2;
    string columnName = 3;
  }
}
```

Field numbering here is literal, not indicative: `timeRange` is 3, closing the unexplained 3-4
gap in the earlier draft.

The optional per-source `TimeRange` matters for aggregations: a daily-mean column consumes
source intervals not implied by its own output timestamps.

### Calculations (annotation.proto)

```proto
message Calculations {
  string id = 1;  // server-generated; the addressing key for getCalculations,
                  // CalculationsSpec, and provenance links (D14)
  repeated CalculationsDataFrame calculationDataFrames = 2;

  message CalculationsDataFrame {
    string name = 1;                          // required; distinct within a Calculations
    dp.service.common.DataFrame frame = 2;    // replaces dataTimestamps + repeated DataColumn
  }
}
```

`CalculationsSpec.dataFrameColumns` is a map keyed by frame name, so duplicate frame names are
unaddressable. The current proto does not require distinctness; make it a documented validation
rule now that the same names carry provenance links.

### ExportDataRequest (annotation.proto)

Add `repeated DataBlock dataBlocks`; document "at least one of dataSetId / dataBlocks /
calculationsSpec; sources combine"; fix the contradictory "Required" comment on `dataSetId`.
Document the format restriction from D10: calculations (or datasets) containing array / image /
struct columns export to HDF5 but not to CSV or XLSX.

## Verified dp-service behavior

Checked 2026-08-27 against dp-service `cbcd522`. All query logic for these APIs lives in
`MongoSyncAnnotationClient`; the dispatchers only marshal results into protobuf. Both original
open items are resolved — one *against* the plan's assumption — and the check surfaced six
further findings that changed the decisions above.

| # | Question | Finding |
|---|---|---|
| 1 | Criteria combination | Two-bucket AND/OR scheme; the "Or" comments are **accurate**, not stale. All-AND is a behavior change → D15 |
| 2 | Empty results | Empty list, never `ExceptionalResult` — as assumed. Proto comments are stale drift; safe to reword |
| 3 | Paging | `queryDataSets` / `queryAnnotations` have **no paging at all**; `queryPvMetadata` unbounded; tokens are Base64 skip offsets, so "malformed" is undetectable → D7 |
| 4 | Ordering | All five already sort ascending; `startTime` is non-unique and unstable under skip-paging → D8 |
| 5 | `TextCriterion` | MongoDB `$text` index search, not field-scopable; annotations index also covers `event.description` → D16 |
| 6 | `ValueStatus` | `src/main` as assumed; **four test files** also affected → D13 |
| 7 | Denormalized `dataSets` | N+1 per dataset per annotation, serial, unbatched; calculations embedded whole → D5 |
| 8 | Export column types | Calculations path is `DataColumn`-only; bucket path already polymorphic → D10 |

Two items found in passing, neither in this ticket's scope, both worth filing against
dp-service:

- **`QueryAnnotationsDispatcher` double-completes the observer.** On a missing dataset or
  calculations document it calls `sendQueryAnnotationsResponseError(...)` without returning, then
  continues the loop and calls `sendQueryAnnotationsResponse` on an already-completed observer.
  D5 deletes the code path that triggers it.
- **`queryConfigurationActivations` calls `.skip(skip)` unconditionally**, so a negative decoded
  page token reaches the driver; the other two paged queries guard with `skip > 0`. Fixed
  incidentally by the opaque-token change in D7.

## Work breakdown

Step 1 is no longer "check dp-service behavior" — that is done and recorded above. The handoff
document moves early, because its content is now established and it is what unblocks dp-service.

1. **Done (2026-08-27)** — [`dp-service-handoff.md`](dp-service-handoff.md), written from the
   verified findings while they were fresh. Contents: new/changed methods including `getCalculations`; the paged-List conversion
   steps preserved from dp-service#211; D7 semantics (default page size, opaque page tokens,
   `queryPvMetadata`'s unbounded→capped change, new paging for datasets and annotations); D8
   ordering including the `startTime` tiebreaker; D9 delete rules and the dangling-link
   contract; D5's N+1 removal and the `repeated IdCriterion` batch-fetch path; D10 typed-column
   export work (`CalculationsDataFrameDocument`, `TabularDataUtility.addCalculationsToTable`,
   `CalculationsDocument` helpers); D15 criteria semantic change with the tags callout; D16
   annotations text-index rebuild forced by `comment` → `description`. Remaining: file the fresh
   dp-service implementation ticket from it, and settle the three open questions it lists
   (default page size and its config key, opaque-token scope, `deleteDataSet` rejection message).
2. Proto edits: annotation.proto (methods, entities, requests, criteria, export, `Calculations`),
   common.proto (`ColumnProvenance`). Note this reaches beyond the dataset/annotation sections:
   D7/D8 add `Pagination:` and `Ordering:` blocks to the PV metadata, configuration, activation,
   and sample status queries too.
3. #143 in parallel: `ValueStatus` removal (separate PR, same release), including the four
   dp-service test files listed in D13.
4. `mvn compile`; regenerate and sanity-check stubs.
5. `README.md` reference sections for all new/changed methods and messages, plus the
   `Data Set API` / `Annotation API` prose describing provenance and calculations.
6. Cookbook: rework `doc/cookbook/datasets-and-annotations.md`. Its "Where this area departs
   from the conventions" section is **deleted outright** — every departure it documents
   (no pagination, the empty-result contradiction, the ambiguous AND/OR comments, the missing
   delete/patch, the asymmetric field numbers) is fixed by this work. The same section doubles
   as a completeness checklist for the proto edits; it also flags the stale `DataSet.id` comment
   referencing a nonexistent `createDataSet()` method, which is not otherwise tracked here.
   Update recipe tables; confirm `conventions.md` still holds; run
   `tools/check-cookbook-snippets.py`.
7. Update the `CLAUDE.md` service summary and Key Concepts (`DataColumn` role note,
   `ColumnMetadata` / provenance description, `Calculations` as a readable entity).
8. Release notes: breaking-changes list (message shapes, criteria semantics per D15 with the
   tags-AND callout, paging defaults, `comment`→`description`, dropped `dataSets` and
   `calculations` denormalization, #143).
9. dp-python-lib: stub regeneration and client-library updates (tracked in that repo).
10. dp-desktop-app: confirm whether it consumes `Annotation`, `comment`, or the nested read-side
    type, and file an update ticket if so. Recording "not a consumer" is an acceptable outcome —
    the point is that it is checked rather than assumed.

## Follow-ons

- **QuerySpec-driven export** (own ticket when taken up): regex/metadata PV selection and
  configuration/status filtering at export time; requires deciding where `QuerySpec` lives.
- **Sample status domain registry**: already stubbed under #121; unaffected here.
- **`queryCalculations`**: omitted per D14; add if a use case appears for finding calculations
  without going through annotations. Additive, so it needs no reservation now.
- **Column filtering on retrieval**: `CalculationsSpec.dataFrameColumns` filters columns at
  export time only. If `getCalculations` on a large calculation proves too heavy, the same
  filter could apply to retrieval. Not built now — no evidence it is needed.
