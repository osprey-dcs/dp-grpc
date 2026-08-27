# dp-service handoff: modernized DataSets and Annotations APIs (dp-grpc #132)

- **Proto ticket**: [osprey-dcs/dp-grpc#132](https://github.com/osprey-dcs/dp-grpc/issues/132) —
  authoritative scope statement for the API change.
- **Design rationale**: [`plan/tickets/132/plan.md`](plan.md) — decisions D1–D16, with the
  reasoning behind each. This document does not restate the rationale; it says what dp-service
  must do.
- **Companion**: [osprey-dcs/dp-grpc#143](https://github.com/osprey-dcs/dp-grpc/issues/143) —
  `ValueStatus` removal, same release, separate PR.
- **Supersedes**: dp-service #210, #211, #214 (closed with pointers here). The parts of #211
  worth keeping are preserved in [Paging conversion](#3-paging-conversion) below.
- **Status**: written 2026-08-27, before the proto change lands. Verified against dp-service
  `cbcd522`.

Read this alongside the proto diff once it merges; where the two disagree, the protos win.

## Reading the line references

Every code reference here was verified against dp-service `cbcd522`. **Line numbers in the
superseded tickets (#210, #211) no longer match the file** — `MongoSyncAnnotationClient` has
changed since they were written. Use the references in this document, and re-verify before
editing if the branch has moved on.

Paths are abbreviated below. Unless stated otherwise:

| Shorthand | Full path under `src/main/java/com/ospreydcs/dp/service/` |
|---|---|
| `AnnotationServiceImpl` | `annotation/service/AnnotationServiceImpl.java` (1675 lines) |
| `MongoAnnotationHandler` | `annotation/handler/mongo/MongoAnnotationHandler.java` (602) |
| `MongoSyncAnnotationClient` | `annotation/handler/mongo/client/MongoSyncAnnotationClient.java` (1584) |
| `MongoClientBase` | `common/mongo/MongoClientBase.java` (476) |
| `TabularDataUtility` | `common/utility/TabularDataUtility.java` (359) |
| `DataExportHdf5File` | `annotation/handler/mongo/export/DataExportHdf5File.java` (334) |
| jobs | `annotation/handler/mongo/job/` |
| dispatchers | `annotation/handler/mongo/dispatch/` |
| documents | `common/bson/` |

### The pattern to copy for every new method

`getConfiguration` is the cleanest fully-worked example of the modern five-layer pattern. Copy
it rather than the legacy dataset/annotation methods, which predate it:

| Layer | Location |
|---|---|
| Sender helpers | `AnnotationServiceImpl:922-960` — one `…ExceptionalResult(msg, status)` builder, not one per status |
| RPC handler | `AnnotationServiceImpl:962-970` — logs and delegates; **no inline validation** |
| Handler dispatch | `MongoAnnotationHandler:389-405` — construct job, `requestQueue.put(job)` |
| Job | `job/GetConfigurationJob.java` (54 lines) — validation, client call in try/catch, dispatch |
| Dispatcher | `dispatch/GetConfigurationDispatcher.java` (40) — `handleValidationError` / `handleError` / `handleResult` |
| Client | `com/ospreydcs/dp/client/AnnotationClient.java:991-1021, 1219-1263` |

Companions: `deleteConfiguration` senders `AnnotationServiceImpl:1025-1062`, handler `:1064-1072`;
`DeleteConfigurationJob.java` (47). For the deferred `patch*` stubs, copy `patchConfiguration`
(`AnnotationServiceImpl:1078-1093`) — returns an ERROR `ExceptionalResult` reading
"…is not yet implemented".

The legacy handlers to replace sit at `AnnotationServiceImpl:117-144` (`saveDataSet`),
`:207-280` (`queryDataSets`), `:353-380` (`saveAnnotation`), `:443-556` (`queryAnnotations`),
`:632-654` (`exportData`). The two query handlers carry 60- and 90-line inline `switch`
validation blocks that the modern pattern pushes down into the job. Note also that several
legacy reject branches (`:125-128`, `:216-219`, `:452-456`) do not `return` after sending the
rejection — do not carry that bug forward.

`AnnotationHandlerInterface` (`annotation/handler/interfaces/`, 96 lines) gains one method per
new RPC; existing dataset/annotation signatures are at lines 14-27, modern ones at 45-79.

## 1. What changes, in one table

| Area | Change | Decision |
|---|---|---|
| New RPCs | `getDataSet`, `getAnnotation`, `deleteDataSet`, `deleteAnnotation`, `getCalculations` | D2, D14 |
| New deferred RPCs | `patchDataSet`, `patchAnnotation` — return `RESULT_STATUS_ERROR` "not implemented" | D2 |
| Paging | `queryDataSets` / `queryAnnotations` gain `limit` / `pageToken` / `nextPageToken` | D7 |
| Paging | Unset `limit` = server default page size, on all six paged queries | D7 |
| Paging | Opaque page tokens replace Base64 skip offsets | D7 |
| Ordering | Documented as contract; activation sort gains a tiebreaker | D8 |
| Query results | `dataSets` content and `calculations` content dropped from `queryAnnotations` | D5 |
| Criteria | All criteria AND together; the two-bucket AND/OR scheme is removed | D15 |
| Criteria | `IdCriterion` becomes repeated on both queries | D5 |
| Entities | `createdTime` / `updatedTime` / `modifiedBy` on both; `tags` / `attributes` on `DataSet` | D4 |
| Entities | `Annotation.comment` → `description`; `Annotation` hoisted to top level | D4 |
| Calculations | Storage adopts typed columns via `common.DataFrame` | D10 |
| Export | Typed-column support; inline `dataBlocks` as a transient dataset | D10, D12 |
| Provenance | `ColumnProvenance.derivedFrom` links, stored not interpreted | D11 |
| Indexes | Annotations text index rebuilt for the `comment` → `description` rename | D16 |

## 2. Semantic changes that alter existing behavior

These change results for queries that are valid today. All are accepted per D1 (no production
consumers — usage is dp-service's own tests and demo code), but each needs a release-notes line
and a test update.

### 2.1 Criteria combine with AND (D15) — highest-risk change

Current behavior is a two-bucket scheme: a global bucket ANDed internally, a criteria bucket
ORed internally, and the two ANDed together.

- `queryDataSets` today: `(id AND owner) AND (text OR pvName)`
- `queryAnnotations` today: `(id AND owner AND dataSet AND text) AND (annotationIds OR tags OR attributes)`

After: every criterion ANDs. Multiple values *within* one criterion still OR.

**The consequential case is tags.** Today two `TagsCriterion` entries OR together, so a client
asking for `tag=A, tag=B` gets annotations with either tag. After the change it gets only
annotations with both. This fails silently — no error, just different results — so it must be
called out explicitly in the release notes rather than buried in a list of message-shape changes.

Note also that `TextCriterion` currently sits in the OR bucket for datasets and the AND bucket
for annotations. That inconsistency disappears; both become AND.

Change sites: `MongoSyncAnnotationClient:194-278` (`executeQueryDataSets` — criterion switch
`:202-243`, bucket combination `:251-264`) and `:408-523` (`executeQueryAnnotations` — switch
`:415-488`, combination `:490-509`). Both build a `globalFilterList` and a `criteriaFilterList`;
the change collapses them to one ANDed list. Both currently return `null` when no criteria are
supplied (`:245-249`), which the callers treat as a rejection — preserve that behavior.

### 2.2 `queryPvMetadata` becomes bounded (D7)

Today an omitted `limit` returns every match, unbounded — `MongoSyncAnnotationClient:681` reads
`request.getLimit() > 0 ? request.getLimit() : 0`, then skips the `.limit()` call entirely at
`:700-705`. After the change it returns one server-default page. Any caller that omits `limit`
and ignores `nextPageToken` silently sees partial results. This is the change dp-service#210
flagged as wanting deliberate rollout; D1 accepts it.

### 2.3 Empty results (no change, but fix the comments)

Verified: both dispatchers already return an empty result list, never an `ExceptionalResult`
(`dispatch/QueryDataSetsDispatcher.java:35-62`, `dispatch/QueryAnnotationsDispatcher.java:40-103`).
The proto comments claiming otherwise are stale and are corrected in the proto change. **No
dp-service change is required here** — this note exists so the discrepancy is not "fixed" in the
wrong direction.

## 3. Paging conversion

Preserved from dp-service#211, which is otherwise closed.

`executeQueryDataSets` (`MongoSyncAnnotationClient:194-278`, cursor returned at `:268-271`) and
`executeQueryAnnotations` (`:408-523`, cursor at `:513-516`) are the last cursor-based queries;
the other four materialize a `List` and page with a skip offset. Both currently end in
`.find(filter).sort(ascending(_id)).cursor()` — no `skip`, no `limit`, no token.

**Reference implementation: `executeQueryConfigurations` (`:899-996`).** It shows the whole
idiom — limit resolution `:962`, token decode `:963-971`, sort `:973-975`, `.skip(skip)` `:977`,
the `limit + 1` probe `:981`, and trim-plus-re-encode `:987-993`, returning a
`ConfigurationQueryResult(documents, nextPageToken)` at `:995`.

Convert both to the paged pattern:

1. Read `limit` / `pageToken` from the request (fields added by the proto change).
2. Decode `pageToken`; apply `skip` and `limit + 1` to the query.
3. Trim the probe document and emit `nextPageToken` when a further page exists.
4. Return a `List`-based result object rather than a cursor — cf. `PvMetadataQueryResult`,
   `ConfigurationQueryResult`.
5. Update the dispatchers and handler jobs to the new result type — `job/QueryDataSetsJob.java`
   (45 lines) and `job/QueryAnnotationsJob.java` (45), plus their dispatchers. Note
   `QueryDataSetsDispatcher` has no `handleError` / `handleValidationError` methods at all;
   add them to match `QueryConfigurationsDispatcher` (52 lines). `job/QueryConfigurationsJob.java`
   (99) is the paged-job template.

**The streaming-to-List tradeoff #211 raised is now bounded.** #211 noted that moving these two
off cursors adopts the unbounded-materialization shape flagged for `queryPvMetadata`. Because
D7 settles unset-`limit` as a server default cap, materialization is bounded by the page size
in every case — the concern that made #211 wait is resolved by the decision, not deferred.

### Opaque page tokens (D7)

Tokens today are Base64 of a decimal skip offset, so the requirement to reject a malformed token
is not implementable as written: any Base64-decodable integer string is structurally valid.
Adopt the opaque token type `querySampleStatuses` already uses
(`annotation/handler/model/SampleStatusPageToken.java`; resume filter at
`MongoSyncAnnotationClient:1451-1468`) across all paged annotation queries, so a token can be
validated and rejected.

If that is deferred, say so and narrow the proto claim to "undecodable tokens are rejected" —
do not document a rejection the implementation cannot perform.

Two existing defects fixed incidentally by this work:

- All three currently-paged queries catch a bad token, log at warn, and silently restart at page
  one (`MongoSyncAnnotationClient:683-690`, `:963-971`, `:1239-1245`). That becomes an
  `ExceptionalResult`.
- `queryConfigurationActivations` applies `.skip(skip)` unconditionally at `:1253`, so a negative
  decoded token reaches the driver; the other two guard with `skip > 0`.

### `querySampleStatusesStream` keeps its own rule

Its `pageToken` must be empty and a non-empty token is rejected. Do not fold it into the general
malformed-token rule.

## 4. Ordering (D8)

Mostly already true — every query applies an explicit ascending sort today. The work is making
it contract and fixing one instability.

| Query | Sort | Action |
|---|---|---|
| `queryDataSets` | `_id` asc (`:270`) | none — already correct |
| `queryAnnotations` | `_id` asc (`:515`) | none — already correct |
| `queryPvMetadata` | `pvName` asc (`:694`) | none — unique index, stable |
| `queryConfigurations` | `name` asc (`:975`) | none — unique index, stable |
| `queryConfigurationActivations` | `startTime` asc (`:1252`) | **add a tiebreaker** |

Line references are `MongoSyncAnnotationClient`. Uniqueness is backed by the indexes at
`MongoClientBase:269-271` (`pvName`) and `:283-285` (`configurationName`).

`startTime` is not unique. Under skip-based paging, ties can drop or duplicate rows across page
boundaries. Sort on `startTime`, then `configurationName`, then id, so the order is total.

## 5. Denormalization removal (D5)

This is the largest performance change in the ticket.

**Current behavior**: for every annotation returned, `QueryAnnotationsDispatcher.handleResult`
(`dispatch/QueryAnnotationsDispatcher.java:40-103`) issues one `findDataSet` round-trip *per
dataset id* in a loop at `:61-71` — serially, with no `$in` batching, no caching, and no
de-duplication across annotations sharing a dataset — plus one `findCalculations` per annotation
at `:74-85`. `AnnotationDocument.toAnnotation` then inlines full DataSet bodies
(`common/bson/annotation/AnnotationDocument.java:139-141`) and the full Calculations
(`:144-146`) into each returned annotation. With no paging on `queryAnnotations` today, a broad
query fans out into thousands of point lookups and one unbounded protobuf message.

The underlying lookups are `MongoSyncAnnotationClient.findDataSet` (`:65-75`, wrapping the real
`lookupDataSet` at `:77-99`) and `findCalculations` (`:547-568`). Both swallow exceptions to
`null`, collapsing "absent" and "query failed" — worth separating if these stay in use anywhere.

**After**: `queryAnnotations` returns `dataSetIds` and `calculationsId` only. No per-annotation
lookups at all — both are already fields on the annotation document. Content comes from
`getDataSet` / `getCalculations` / `getAnnotation` on demand.

**Do not replace the N+1 with a batched N+1.** The client-side batch path is `queryDataSets`
with a repeated `IdCriterion`: a client listing N annotations fetches all referenced datasets in
one call. Make sure `IdCriterion` accepts a list and compiles to `$in`.

Deleting this code path also removes a latent bug: `QueryAnnotationsDispatcher` calls
`sendQueryAnnotationsResponseError(...)` on a missing dataset or calculations document **without
returning** (`:68`, `:83`, `:96`), then continues the loop and calls
`sendQueryAnnotationsResponse` on an already-completed observer — a double
`onNext`/`onCompleted`. Worth confirming it is gone rather than relocated.

## 6. Calculations as a readable entity (D14)

Calculations are already stored in their own collection (`MongoClientBase:42`) with their own
id; `AnnotationDocument` holds a `calculationsId` reference (field at
`common/bson/annotation/AnnotationDocument.java:18-25`). Nothing about the storage model changes
here — the change is that the API now exposes what storage already does.

`getCalculations` wraps the existing `MongoSyncAnnotationClient.findCalculations` (`:547-568`),
which currently catches all exceptions to `null`; the new job should distinguish not-found from
query-failure the way `GetConfigurationJob` does.

Note the calculations collection has **no indexes at all** (`MongoClientBase:263-265` returns
`true` without creating any). Lookup by `_id` needs none, but add one if `getCalculations` ever
grows other access paths.

- **`getCalculations(calculationsId)`** — new, implemented. Single-record lookup, not-found
  returns `ExceptionalResult`. Follows the `getPvMetadata` shape.
- **No `saveCalculations`** — calculations are written through `saveAnnotation`.
- **No `deleteCalculations`** — lifecycle stays with the owning annotation. `deleteAnnotation`
  deletes the annotation's calculations with it.
- **No `queryCalculations`** — discovery goes through annotations.

`saveAnnotation` full-replace applies to calculations like every other field: an update omitting
them clears them, and the stored Calculations document should be deleted rather than orphaned.
`SaveAnnotationJob` (`job/SaveAnnotationJob.java`, 103 lines) currently inserts a
`CalculationsDocument` and threads its id into `AnnotationDocument.fromSaveAnnotationRequest`;
it has no delete-the-previous path, so replacing an annotation's calculations orphans the old
document today. Fix that with this work.

**`SaveAnnotationResult` returns `calculationsId`** alongside `annotationId` when the request
carried calculations, so callers get the export and provenance key without a round-trip.

## 7. Delete referential integrity (D9)

- **`deleteDataSet`** is rejected while any annotation references the dataset in `dataSetIds`.
  Mirrors `deleteConfiguration`'s rejection when activations exist — copy
  `MongoSyncAnnotationClient.activationsExistForConfiguration` (`:787-796`) and its use in
  `deleteConfiguration` (`:998-1052`). An index already supports the reverse lookup:
  `MongoClientBase:236` indexes `dataSetIds` ascending. The error message should name at least
  one referencing annotation id so the caller can act on it.
- **`deleteAnnotation`** is not blocked by incoming `annotationIds` or by column-provenance
  references. Those are soft associations and may dangle.
- **Dangling links resolve to nothing, and readers must tolerate it.** A soft link that does not
  resolve means the referenced record was deleted. This applies to `annotationIds` and to
  `ColumnProvenance.derivedFrom` links. Do not add cascade deletion, and do not add validation
  that would reject a save carrying an unresolvable provenance link — links are stored, not
  interpreted (D11).

## 8. Typed columns in Calculations and export (D10)

Once `CalculationsDataFrame` carries a `common.DataFrame`, a client can put a `DoubleColumn` in
a calculation. The storage and export paths must accept it or the write silently loses data.

The bucket path already solved this problem; the calculations path should adopt the same
machinery rather than inventing a parallel one.

Work, in dependency order:

1. **`CalculationsDataFrameDocument`** (`common/bson/calculations/`, 82 lines) — field
   `List<DataColumnDocument> dataColumns` at `:14-16` becomes the polymorphic
   `ColumnDocumentBase`. Conversions at `:42-64` (`fromCalculationsDataFrame`) and `:66-80`
   (`toCalculationsDataFrame`) change with it.

   The hierarchy to adopt already exists at `common/bson/column/` (22 files):
   `ColumnDocumentBase` (96 lines, `@BsonDiscriminator` at `:14`, abstract `toProtobufColumn()`
   at `:46`), intermediates `ScalarColumnDocumentBase` / `ArrayColumnDocumentBase` /
   `BinaryColumnDocumentBase`, and 16 concrete subclasses. `BucketDocument` shows the pattern:
   `private ColumnDocumentBase dataColumn` at `common/bson/bucket/BucketDocument.java:29`, with
   per-type factory dispatch at `:131-233`.

2. **`CalculationsDocument.frameColumnNamesMap()`** (`common/bson/calculations/CalculationsDocument.java:76-87`)
   and `diffCalculations` (`:56-74`) — typed equivalents. `frameColumnNamesMap` drives
   `ExportDataJobBase`'s column-filter validation, so it must handle the new shape before export
   works.

3. **HDF5 export** — the bucket writer already does this correctly at
   `DataExportHdf5File:200-211`: `getDataColumn().toProtobufColumn()`, serialize, then write a
   self-describing `"proto:" + simpleName` discriminator at `DATA_COLUMN_ENCODING`. The
   calculations writer `writeCalculations` (`:245-330`) does not — it iterates
   `DataColumnDocument` at `:294` and calls `toByteArray()` at `:315`. Give it the same
   treatment, including the encoding tag.

4. **Tabular export (`TabularDataUtility.addCalculationsToTable`, `:289-357`)** — the column
   loop at `:331-343` calls `frameColumnDocument.toDataColumn()`, again `DataColumnDocument`-typed.
   It needs the narrowing `addBucketToTable` already performs at `:149-181`: `ScalarColumnDocumentBase`
   → `.toDataColumn()` (`:162-164`), legacy `DataColumnDocument` (`:165-167`), else throw
   `NonScalarColumnException` (`:168-173`).

Filter validation in `ExportDataJobBase` (`job/ExportDataJobBase.java`, 273 lines) resolves
`dataSetId` at `:83-94` and `calculationsSpec` at `:96-113`, then validates the requested frame
and column names against `frameColumnNamesMap()` at `:115-148`. The abstract hook subclasses
implement is `exportData_(...)` at `:60-64`.

**Contract consequence, documented in the proto**: a calculation containing array / image /
struct columns exports to HDF5 but not to CSV or XLSX. This already holds for datasets via
`NonScalarColumnException`, so the restriction is consistent rather than new — but it must
surface as a documented rejection, not an unhandled exception.

## 9. Inline `dataBlocks` export (D12)

`ExportDataRequest` gains `repeated DataBlock dataBlocks`, treated server-side as a transient
dataset — the same building block a stored DataSet contains, so it should reuse the same
resolution path rather than a parallel one. `ExportDataJobBase:83-94` currently requires a
stored `DataSetDocument`; the cleanest change is to construct one in memory from the inline
blocks and let everything downstream proceed unchanged. Note `exportObjectId` (set in that same
block) feeds the output filename, so inline exports need a filename source — the request has no
id to use.

- At least one of `dataSetId` / `dataBlocks` / `calculationsSpec` is required; reject a request
  with none.
- Sources combine in a single export when more than one is supplied.
- Nothing is persisted: inline blocks produce no DataSet record.

## 10. Text index rebuild (D16)

`TextCriterion` compiles to a collection-level MongoDB `$text` search, not a per-field regex.
Two consequences:

- The `comment` → `description` rename (D4) **forces an annotations text-index rebuild** — the
  index names the field. MongoDB permits only one text index per collection, so this is a drop
  and recreate, not an addition.
- The current annotations text index (`MongoClientBase:252-258`) covers `name` + `comment` +
  **`event.description`**. `event.description` (`common/bson/BsonConstants.java:10`) corresponds
  to the `eventMetadata` field that was **removed from the proto** — the index has been searching
  a field the API no longer exposes. **Drop it in the rebuild.**

Target index: `name` + `description`, matching the datasets index at `MongoClientBase:217-222`
and the documented contract. Keep the compound-index shape — the text keys are wrapped in an
inner `compoundIndex` with `ownerId` ascending outside it, and the comment at `:214-216` explains
the ordering constraint that requires this.

Related index work in the same file: `createMongoIndexesDataSets()` `:208-228` and
`createMongoIndexesAnnotations()` `:230-261`; creation is invoked from `:431-467`. If a unique
index on either collection is wanted, note there is **no `…WithOptions` hook** for datasets or
annotations today — only PvMetadata (`:64`, `:71`), Configurations (`:74`), and activations
(`:77`) have one. Adding a unique index means adding the hook first.

Because `$text` cannot be scoped to named fields at query time, the proto documents
`TextCriterion` as full-text search over the record's indexed text fields, naming which fields
those are. Keep the index and that comment in sync — they are the same contract.

## 11. Entity and audit fields (D4)

Both `DataSet` and `Annotation` gain `createdTime` / `updatedTime` (server-set) and `modifiedBy`
(last writer, unvalidated free-form). `DataSet` additionally gains `tags` and `attributes`.

**Less new storage than it looks.** `DpBsonDocumentBase` (`common/bson/`, 58 lines) already
supplies `tags` (`:10`), `attributes` (`:11`), `createdAt` (`:12`), `updatedAt` (`:13`), plus
`addCreationTime()` `:49-51` and `addUpdatedTime()` `:55-57`, and both documents already extend
it. What is missing is narrower:

- `DataSetDocument` (`common/bson/dataset/`, 129 lines): inherits `tags` / `attributes` but
  **nothing ever sets them** — `fromSaveRequest` (`:59-75`) sets only dataBlocks / name /
  ownerId / description. `createdAt` / `updatedAt` are persisted by `saveDataSet` but **not
  emitted** by `toDataSet()` (`:77-93`).
- `AnnotationDocument` (233 lines): `tags` / `attributes` **are** wired (set at `:96-106`,
  emitted at `:128-136`), but `createdAt` / `updatedAt` are again persisted and not emitted by
  `toAnnotation` (`:115-149`).
- **Neither document has a `modifiedBy` field** — that one is genuinely new on both.

So the work is: add `modifiedBy`, wire `tags` / `attributes` through `DataSetDocument`, and emit
the audit timestamps in both `toDataSet()` and `toAnnotation()`. The persistence side is already
correct — `saveDataSet` (`MongoSyncAnnotationClient:101-192`) and `saveAnnotation` (`:315-406`)
already call `addCreationTime()` on insert and preserve `getCreatedAt()` across a replace
(`:154-156`).

- Audit timestamps are **server-set and must not be accepted as input**. The save requests list
  client-settable fields only; reject or ignore any attempt to set them.
- `modifiedBy` reflects the last writer only; no history is maintained. Same semantics as
  `PvMetadata` and `Configuration`.
- `ownerId` is retained and is distinct from `modifiedBy` — ownership is not last-writer
  identity.
- On create, `createdTime` and `updatedTime` are equal; on full-replace update, `createdTime` is
  preserved from the existing record.

## 12. Test impact

Expect updates across the annotation test surface. The criteria change (2.1) affects any test
asserting multi-criterion results; the paging change affects any test asserting a full result
set; the denormalization removal (D5) affects any test reading `dataSets` or `calculations` off
a query result.

Two files carry most of the weight and should be budgeted for directly:

| File | Lines | Why |
|---|---|---|
| `src/test/java/…/annotation/AnnotationTestBase.java` | **2467** | Params records, response observers, and request builders for every legacy method — `buildSaveDataSetRequest` `:641`, `buildQueryDataSetsRequest` `:682`, `buildSaveAnnotationRequest` `:742`, `buildQueryAnnotationsRequest` `:775`, `buildExportDataRequest` `:876` |
| `src/test/integration/java/…/integration/annotation/GrpcIntegrationAnnotationServiceWrapper.java` | **1745** | Per-API send/verify helpers; every new RPC needs one |

Other affected integration tests: `AnnotationCalculationsIT.java` (1260 — the main casualty of
the typed-column change), `QueryAnnotationsIT.java` (345), `QueryDataSetsIT.java` (185),
`ExportDataIT.java` (133), `ExportDataBucketSpanIT.java` (175), `SaveAnnotationIT.java` (128),
`SaveDataSetIT.java` (98), `AnnotationIntegrationTestIntermediate.java` (339). For how a modern
get/delete/paged-query IT is written, copy `ConfigurationIT.java` (1223) or `PvMetadataIT.java`
(544).

Separately, **#143 (`ValueStatus` removal) will not build until four test files are updated.**
One is a dedicated `ValueStatus` test; the other three are shared bases that merely reference it:

- `src/test/integration/java/…/integration/query/QueryDataValueStatusIT.java` (179 lines, 15
  references) — a dedicated ingest/query round-trip test for `ValueStatus`; **delete outright**
  rather than adapting it. This is the only file in the tree named for `ValueStatus`.
- `src/test/java/com/ospreydcs/dp/client/IngestionClientTest.java` (387, 10 refs)
- `src/test/java/…/service/ingest/IngestionTestBase.java` (1071, 6 refs)
- `src/test/java/…/service/query/QueryTestBase.java` (904, 1 ref — a comment)

In production code #143 touches only `IngestionClient.java`. No server-side code reads or writes
`valueStatus` — it rides opaquely inside serialized `DataValue`s — and archived blobs containing
field 15 still parse as an unknown field, so no data migration is needed.

## 13. Suggested sequencing

The proto change must land first; everything here depends on generated stubs.

1. Regenerate stubs against the new dp-grpc release.
2. Entity and document model: audit fields, `comment` → `description`, `DataSet` tags/attributes.
3. Text index rebuild (section 10) — pairs with the rename, and is a migration.
4. New CRUD methods: `getDataSet`, `getAnnotation`, `deleteDataSet`, `deleteAnnotation`,
   `getCalculations`, plus the two deferred `patch*` stubs.
5. Paging conversion and opaque tokens (section 3), then ordering (section 4).
6. Criteria AND semantics (2.1) and repeated `IdCriterion`.
7. Denormalization removal (section 5).
8. Typed calculations columns and export (section 8), then inline `dataBlocks` (section 9).
9. Test updates throughout; #143 test cleanup with that PR.

Steps 2–3 and 4 are largely independent and can go in parallel. Step 8 is the largest single
chunk and is independent of 5–7.

## Open questions for the implementor

These are genuinely undecided, not decisions omitted by accident:

1. **Server default page size** — mostly answered by existing precedent; what remains is
   choosing values. The mechanism exists and is already used by the two newest paged APIs:

   | Setting | Key | Default | Defined |
   |---|---|---|---|
   | Sample status page size | `AnnotationHandler.sampleStatusQueryDefaultPageSize` | 10000 | `MongoAnnotationHandler:30-32`, `application.yml:165` |
   | Sample status max | `AnnotationHandler.sampleStatusQueryMaxPageSize` | 100000 | `:33-35`, `application.yml:169` |
   | Query V2 page size | `QueryHandler.queryV2DefaultPageSize` | 10000 | `MongoQueryHandler:32`, `application.yml:134` |
   | Query V2 max | `QueryHandler.queryV2MaxPageSize` | 100000 | `MongoQueryHandler:34`, `application.yml:138` |

   `MongoAnnotationHandler.sampleStatusQueryPageSize(int)` (`:40-52`) is the canonical resolver:
   requested `0` → configured default, then clamped by `Math.min(limit, maxPageSize)`. Its doc
   comment states it is deliberately consistent with Query API V2.

   The three currently-paged annotation queries bypass all of this — the `100` literals at
   `MongoSyncAnnotationClient:962` and `:1246-1247` are hardcoded, and none of the three applies
   a max clamp. **Open: the default and max values for the annotation metadata queries, and
   whether they get one shared key pair or one per query.** Following the existing naming, one
   pair such as `AnnotationHandler.metadataQueryDefaultPageSize` / `…MaxPageSize` would cover
   all five. Note 10000 is a plausible default for sample statuses but likely too large for
   record-shaped results like annotations.
2. **Opaque token scope** — adopt `SampleStatusPageToken` across all six paged queries in this
   ticket, or convert datasets/annotations only and leave the others for a follow-on? The proto
   wording depends on the answer (see section 3).
3. **`deleteDataSet` rejection message** — how many referencing annotation ids to name. One is
   enough to act on; all of them could be a large message.
4. **Orphaned Calculations documents** — `SaveAnnotationJob` has no delete path for a replaced
   annotation's previous calculations (section 6). Fixing that forward is clear; whether to
   clean up documents already orphaned in existing deployments is a separate call.
