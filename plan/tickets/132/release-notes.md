# Release notes content: issue #132 breaking changes

Draft text for the GitHub release notes of the release carrying
[#132](https://github.com/osprey-dcs/dp-grpc/issues/132).  Release notes for this repo are
authored on the GitHub release itself; this file is a staging area, not a published artifact.

Companion ticket [#143](https://github.com/osprey-dcs/dp-grpc/issues/143) (`ValueStatus`
removal) ships in the same release and has its own entry below.

## Breaking changes — DataSet and Annotation APIs

The DataSet and Annotation APIs in `DpAnnotationService` have been modernized to the CRUD
conventions used by the PV metadata, machine configuration, and sample status APIs.  Method names
are unchanged, but **message shapes and query semantics changed incompatibly**.  Client code
written against 1.15.0 or earlier will not compile against these stubs and must be updated.

**Message shape changes**

- `SaveDataSetRequest` no longer embeds a `DataSet` message.  It now lists the client-settable
  fields directly: `id`, `name`, `ownerId`, `description`, `dataBlocks`, `tags`, `attributes`,
  `modifiedBy`.
- `Annotation` is now a **top-level message** in `annotation.proto`.  It was previously nested as
  `QueryAnnotationsResponse.AnnotationsResult.Annotation`.
- `Annotation.comment` is renamed **`description`**, for consistency with every other entity.
- `DataSet` and `Annotation` both gain server-set `createdTime` / `updatedTime` and a
  last-writer `modifiedBy`.  `DataSet` additionally gains `tags` and `attributes`.
- `Calculations.CalculationsDataFrame` is now `name` + `common.DataFrame`, replacing the previous
  `DataTimestamps` + `repeated DataColumn` pair.  Calculation columns therefore gain the typed
  scalar / array / image / struct / serialized column types and per-column `ColumnMetadata`.
  Frame names must be distinct within a `Calculations` object.

**Query results no longer embed content**

- `queryAnnotations` results carry `dataSetIds` and `calculationsId` only.  The denormalized
  `repeated DataSet dataSets` field and the embedded `Calculations` content are **removed**.
- Retrieve DataSet content with a single `queryDataSets` call using the now-`repeated`
  `IdCriterion`, and Calculations content with the new `getCalculations` or `getAnnotation`.
- This removes an N+1 query fan-out on the server: the previous implementation issued one dataset
  lookup per dataset id per annotation, serially and unbatched, and embedded every frame, column,
  and value into each returned annotation.

**Criteria semantics — silent behavior change, read this one**

All query criteria are now combined with **AND**, with values within a single criterion combined
with OR, matching the convention used everywhere else in the API.

Previously the server used a two-bucket scheme that ORed some criteria together, with different
bucket assignments per method.  The most consequential difference: **two `TagsCriterion` entries
previously matched "either tag" and now match "both tags"**.  This change is silent — no error is
raised, the result set simply differs.  Review any query that supplies multiple criteria.

`TextCriterion` is now documented as a full-text search over the record's indexed text fields
rather than as a per-field match; it is a collection-level text index search and cannot be scoped
to named fields at query time.  Use the new `NameCriterion` to restrict a match to the name.

**Pagination and ordering**

- `queryDataSets` and `queryAnnotations` are now paged: `limit` / `pageToken` on the request,
  `nextPageToken` on the result.  They previously had no paging fields and returned every match
  in one message.
- Across all six paged `DpAnnotationService` queries, an unset or zero `limit` now means a
  **server-configured default page size, not an unbounded result**.  This changes
  `queryPvMetadata`, which was previously unbounded: a caller that omitted `limit` and read the
  whole result in one response now receives one page and must follow `nextPageToken`.
- A malformed `pageToken` is now rejected with an `ExceptionalResult` rather than silently
  restarting at page one.
- Result ordering is now part of the API contract for all six queries: `id` ascending for
  DataSets and Annotations, `pvName` for PV metadata, `configurationName` for configurations,
  and `startTime` then `configurationName` then id for configuration activations.

## New methods

- `getDataSet` / `deleteDataSet` — single-record lookup and delete by id.
- `getAnnotation` / `deleteAnnotation` — single-record lookup and delete by id.  `getAnnotation`
  returns Calculations content inline.
- `getCalculations` — retrieve a Calculations object by `calculationsId` without loading the
  owning Annotation.
- `patchDataSet` / `patchAnnotation` — reserved placeholders per the standard CRUD pattern.  Not
  implemented; calling either returns an error response.

There is deliberately no `bulkSave*` for either entity, and no `saveCalculations`,
`deleteCalculations`, or `queryCalculations` — see the proto comments for the reasoning in each
case.

Referential rules: `deleteDataSet` is rejected while any Annotation references the DataSet in
`dataSetIds`.  `deleteAnnotation` is not blocked by incoming references; `annotationIds` and
column-provenance links are soft associations and may dangle after a delete.

## Column-level provenance

`common.ColumnProvenance` gains a structured `repeated ColumnSource derivedFrom` list naming the
columns a derived column was computed from.  Each `ColumnSource` identifies either an archived PV
by name or a Calculations column (`calculationsId` + `frameName` + `columnName`), with an
optional `TimeRange` for the source interval consumed.

This is additive — existing `source` / `process` fields are unchanged, and an empty `derivedFrom`
list costs nothing on the wire.  Because `ColumnProvenance` rides inside the `ColumnMetadata`
carried by every column message type, the mechanism serves both Annotation Calculations columns
and ingestion-side derived data.

## Export

- `ExportDataRequest` gains `repeated DataBlock dataBlocks`, an inline ad-hoc data specification
  treated server-side as a transient dataset.
- At least one of `dataSetId`, `dataBlocks`, or `calculationsSpec` is required; sources may be
  combined in a single export.  The stale "Required" comment on `dataSetId` is corrected.
- Documented restriction: the tabular formats (CSV, XLSX) can only represent scalar columns.
  Data containing array, image, or struct columns exports to HDF5 only.  This was already true
  for datasets and now also applies to the typed Calculations columns.

## Also in this release

- **#143 — `ValueStatus` removed from `DataValue`.**  The per-sample status mechanism is
  superseded by the Sample Status API, which captures acquisition-time alarm and status
  information in a status domain and allows it to be assigned or updated post-ingestion.  Field
  15 is reserved; archived data containing it still parses, as an unknown field.

## Upgrade checklist

1. Rebuild against the new stubs and fix compile errors — `SaveDataSetRequest`, the `Annotation`
   import path, and `comment` → `description` account for most of them.
2. Replace reads of `Annotation.dataSets` / `Annotation.calculations` in query results with
   `queryDataSets`-by-ids and `getCalculations`.
3. Audit multi-criterion queries for the AND/OR change, especially repeated `TagsCriterion`.
4. Add paging loops wherever a query result was previously assumed complete, including
   `queryPvMetadata`.
5. Update `Calculations` construction to set a `DataFrame` on each frame.
