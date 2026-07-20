# Data Sets, Annotations, and Export Cookbook

Worked examples for defining DataSets, attaching Annotations and derived Calculations to them,
and exporting the result to HDF5, CSV, or XLSX — all part of the Annotation Service.

> **Verified against:** dp-grpc `rel-1.14.0` (Java `com.ospreydcs:dp-grpc:1.14.0`).
> All five methods used here (`saveDataSet`, `queryDataSets`, `saveAnnotation`,
> `queryAnnotations`, `exportData`) exist in 1.14.0 and their field sets are unchanged in 1.15.0.

Reference documentation: [Data Set API](../../README.md#data-set-api),
[Data Export Methods](../../README.md#data-export-methods), and
[Annotation API](../../README.md#annotation-api).

Shared response-checking, criteria, and time conventions live in [conventions.md](conventions.md)
and are not repeated here — but see [Where this area departs from the
conventions](#where-this-area-departs-from-the-conventions), because these are older methods and
they do depart in three places.

### Imports used by the examples

```java
import com.ospreydcs.dp.grpc.v1.annotation.DataSet;
import com.ospreydcs.dp.grpc.v1.annotation.DataBlock;
import com.ospreydcs.dp.grpc.v1.annotation.Calculations;
import com.ospreydcs.dp.grpc.v1.annotation.SaveDataSetRequest;
import com.ospreydcs.dp.grpc.v1.annotation.QueryDataSetsRequest;
import com.ospreydcs.dp.grpc.v1.annotation.SaveAnnotationRequest;
import com.ospreydcs.dp.grpc.v1.annotation.QueryAnnotationsRequest;
import com.ospreydcs.dp.grpc.v1.annotation.ExportDataRequest;

import com.ospreydcs.dp.grpc.v1.common.CalculationsSpec;
import com.ospreydcs.dp.grpc.v1.common.Attribute;
import com.ospreydcs.dp.grpc.v1.common.DataColumn;
import com.ospreydcs.dp.grpc.v1.common.DataValue;
import com.ospreydcs.dp.grpc.v1.common.DataTimestamps;
import com.ospreydcs.dp.grpc.v1.common.SamplingClock;
import com.ospreydcs.dp.grpc.v1.common.Timestamp;
```

Two things worth noting: `DataBlock` is a top-level message in `annotation.proto`, not nested
inside `DataSet`; and `CalculationsSpec` lives in `common.proto` while `Calculations` itself is in
`annotation.proto`.  Query criterion types are nested one level under their request —
`QueryDataSetsRequest.QueryDataSetsCriterion`, `QueryAnnotationsRequest.QueryAnnotationsCriterion`
— and the snippets below write those out in full.

## Contents

- [Model](#model)
- [Defining a DataSet for a region of interest](#defining-a-dataset-for-a-region-of-interest)
- [Updating an existing DataSet](#updating-an-existing-dataset)
- [Finding a DataSet someone else made](#finding-a-dataset-someone-else-made)
- [Attaching a descriptive Annotation](#attaching-a-descriptive-annotation)
- [Publishing derived Calculations](#publishing-derived-calculations)
- [Deriving Calculations from other Calculations](#deriving-calculations-from-other-calculations)
- [Catalog search over Annotations](#catalog-search-over-annotations)
- [Exporting to CSV or XLSX](#exporting-to-csv-or-xlsx)
- [Exporting a DataSet plus Calculations to HDF5](#exporting-a-dataset-plus-calculations-to-hdf5)
- [Where this area departs from the conventions](#where-this-area-departs-from-the-conventions)
- [Also worth knowing](#also-worth-knowing)

## Model

Three concepts stack on top of each other, and each is the handle for the next.

A **`DataSet`** names a region of the archive.  It is a list of **`DataBlock`** rectangles, each
one a `beginTime`, an `endTime`, and a list of `pvNames`.  Multiple blocks let a single DataSet
cover different PV groups over different windows — for example, RF PVs during a ramp plus
diagnostics PVs during the flat-top that followed.  A DataSet holds *no data*; it is a pointer
into the archive, resolved at query or export time.

An **`Annotation`** attaches meaning to one or more DataSets: a `name`, a free-form `comment`,
`tags` for cataloging, key/value `attributes`, links to other Annotations, and optionally a
`Calculations` payload.

**`Calculations`** carries derived values — results you computed, not values the archive
recorded.  The proto's own analogy is an Excel workbook: the `Calculations` object is the
workbook, each `Calculations.CalculationsDataFrame` is a worksheet with its own timestamp axis,
and each `DataColumn` within a frame is a column of computed values.

Provenance is expressed by association rather than by a dedicated field.  A Calculations derived
from archive data is recorded by pointing its Annotation at a DataSet describing the source PVs
and time ranges.  A Calculations derived from *another* Calculations is recorded by listing that
Annotation's id in `annotationIds`.

Both `saveDataSet` and `saveAnnotation` are **id-driven upserts**: an empty `id` creates, a
populated `id` updates.  There is no separate create/update method, and no delete method for
either type.

## Defining a DataSet for a region of interest

### 1. Build one DataBlock per (time range, PV list) rectangle

```java
DataBlock ramp = DataBlock.newBuilder()
    .setBeginTime(ts(t0))
    .setEndTime(ts(t1))
    .addAllPvNames(List.of("LINAC:RF:AMP", "LINAC:RF:PHASE"))
    .build();

DataBlock flatTop = DataBlock.newBuilder()
    .setBeginTime(ts(t1))
    .setEndTime(ts(t2))
    .addAllPvNames(List.of("LINAC:BPM:X", "LINAC:BPM:Y"))
    .build();
```

`DataBlock` predates `common.TimeRange` and uses two separate `Timestamp` fields — you cannot
pass a `TimeRange` here.  Note also that the proto does **not** state whether a DataBlock's
interval is half-open the way `TimeRange` is; that is genuinely unspecified.  If a sample sitting
exactly on `endTime` matters to your analysis, do not rely on either interpretation — nudge the
boundary rather than guessing.

### 2. Build the DataSet, leaving `id` unset

```java
DataSet dataSet = DataSet.newBuilder()
    .setName("2026-07-14 ramp study")       // required
    .setOwnerId("cmcchesney")               // required
    .setDescription("RF ramp plus flat-top diagnostics for shift 2")
    .addAllDataBlocks(List.of(ramp, flatTop))   // required
    .build();
```

### 3. Save it and retain the id

```java
SaveDataSetRequest request = SaveDataSetRequest.newBuilder()
    .setDataSet(dataSet)
    .build();

// after checking hasExceptionalResult()
String dataSetId = response.getSaveDataSetResult().getDataSetId();
```

`SaveDataSetRequest` is the one request in this area that embeds the full domain message rather
than listing flat fields.  `dataSetId` is the handle for *every* later step — annotating,
querying, and exporting all take it — so persist it rather than re-deriving it by search.

## Updating an existing DataSet

There is no `patchDataSet`.  To change a DataSet you re-save it with its `id` populated, and the
save is **full-replace**: the `dataBlocks` list you send *replaces* the stored one, it does not
merge with it.

```java
// 1. fetch the current DataSet
DataSet existing = queryById(dataSetId);

// 2. rebuild with the id set and the COMPLETE new block list
DataSet updated = DataSet.newBuilder()
    .setId(existing.getId())                        // presence of id => update
    .setName(existing.getName())
    .setOwnerId(existing.getOwnerId())
    .setDescription(existing.getDescription())      // omit and it is cleared
    .addAllDataBlocks(existing.getDataBlocksList())  // carry forward
    .addDataBlocks(newBlock)                         // then extend
    .build();
```

The read-modify-write is not optional.  Sending only the block you want to add silently discards
the others — see [Save semantics](conventions.md#save-semantics-full-replace).

Because Annotations reference DataSets by id, an update is visible to every Annotation already
pointing at it.  Widening a DataSet after it has been annotated changes what those Annotations
describe; if that is not what you want, create a new DataSet instead.

## Finding a DataSet someone else made

Search before creating, so that shared regions of interest do not proliferate as near-duplicates.
`queryDataSets` supports four criteria, each carried by exactly one member of the
`QueryDataSetsCriterion` oneof:

| Criterion | Field | Matches |
|---|---|---|
| `IdCriterion` | `id` | DataSet id |
| `OwnerCriterion` | `ownerId` | owner |
| `TextCriterion` | `text` | full text over `name` and `description` |
| `PvNameCriterion` | `name` | a PV name appearing in any `DataBlock` |

```java
QueryDataSetsRequest.newBuilder()
    .addCriteria(QueryDataSetsRequest.QueryDataSetsCriterion.newBuilder()
        .setPvNameCriterion(QueryDataSetsRequest.QueryDataSetsCriterion.PvNameCriterion
            .newBuilder().setName("LINAC:RF:AMP")))
    .addCriteria(QueryDataSetsRequest.QueryDataSetsCriterion.newBuilder()
        .setOwnerCriterion(QueryDataSetsRequest.QueryDataSetsCriterion.OwnerCriterion
            .newBuilder().setOwnerId("cmcchesney")))
    .build();
```

Then iterate `response.getDataSetsResult().getDataSetsList()` and inspect each DataSet's
`dataBlocks` to confirm the coverage actually matches your window — `PvNameCriterion` matches on
the PV name alone and says nothing about time.

There is no time-range criterion for DataSets, so time filtering is a client-side pass over the
returned blocks.

## Attaching a descriptive Annotation

Unlike `saveDataSet`, `SaveAnnotationRequest` is **flat** — it does not embed an Annotation
message.  Required fields are `ownerId`, at least one `dataSetIds` entry, and `name`.

```java
SaveAnnotationRequest.newBuilder()
    .setOwnerId("cmcchesney")
    .addDataSetIds(dataSetId)                  // required, at least one
    .setName("RF trip during ramp")
    .setComment("Amplitude interlock fired at t1; see attributes for run number.")
    .addAllTags(List.of("rf-trip", "shift-2", "reviewed"))
    .addAttributes(Attribute.newBuilder().setName("runNumber").setValue("4471"))
    .addAttributes(Attribute.newBuilder().setName("experimentId").setValue("E-2026-113"))
    .build();

// after checking hasExceptionalResult()
String annotationId = response.getSaveAnnotationResult().getAnnotationId();
```

`Attribute` uses **`name`** for the key, not `key`.  The query-side
`AttributesCriterion` uses `key`.  Mixing these two up is the easiest mistake to make in this
area, and because both are plain strings the compiler will not catch it.

Use `tags` for values you will search by exactly, and `attributes` for structured facts that have
a key.  `comment` and `name` are the client-settable fields reachable by the Annotation
`TextCriterion` free-text search.

## Publishing derived Calculations

This is the level-1 provenance chain: you computed something from raw PV data and want the result
stored alongside a record of exactly which archive data it came from.

### 1. Create a DataSet describing the *inputs*

Its DataBlocks must reference the PVs and time ranges the computation actually consumed.  That
DataSet is the provenance record; skipping it leaves the calculation unattributable.

### 2. Build the Calculations

```java
DataColumn rmsColumn = DataColumn.newBuilder()
    .setName("rf_amp_rms")                            // calculation name, not a PV name
    .addDataValues(DataValue.newBuilder().setDoubleValue(12.7))
    .addDataValues(DataValue.newBuilder().build())    // <- MISSING: no oneof member set
    .addDataValues(DataValue.newBuilder().setDoubleValue(12.9))
    .build();

Calculations calculations = Calculations.newBuilder()
    .addCalculationDataFrames(Calculations.CalculationsDataFrame.newBuilder()
        .setName("rf-statistics")                     // required frame name; see note below
        .setDataTimestamps(DataTimestamps.newBuilder()
            .setSamplingClock(SamplingClock.newBuilder()
                .setStartTime(ts(t0))
                .setPeriodNanos(1_000_000_000L)
                .setCount(3)))
        .addDataColumns(rmsColumn))
    .build();
```

Three things to get right here:

- **The field is `calculationDataFrames` (singular "calculation"), the message type is
  `CalculationsDataFrame` (plural).**  Java: `addCalculationDataFrames()`.
- **Every column must have exactly one `DataValue` per timestamp** defined by the frame's
  `DataTimestamps` — `SamplingClock.count`, or the size of the `TimestampList`.  Pad with empty
  `DataValue`s; do not shorten the list.
- **`DataColumn` is deprecated for ingestion but is the correct type here.**  That is deliberate:
  a `DataValue` with no oneof member set means "no result at this timestamp", and the dense
  column types have no way to express that.  On the read side, detect it with
  `value.getValueCase() == DataValue.ValueCase.VALUE_NOT_SET`.

Use a `SamplingClock` when the output is uniformly spaced and a `TimestampList` when it is not
(event-triggered results, or output that inherits irregular input timestamps).

### 3. Save the Annotation carrying the Calculations

```java
SaveAnnotationRequest.newBuilder()
    .setOwnerId("cmcchesney")
    .addDataSetIds(inputDataSetId)          // the provenance link to archive data
    .setName("RF amplitude RMS, shift 2")
    .setComment("1 Hz RMS over LINAC:RF:AMP")
    .setCalculations(calculations)
    .build();
```

### 4. Retrieve the server-assigned `Calculations.id`

`saveAnnotation` returns only `annotationId` — it does **not** return the Calculations id.  But
`exportData` needs that id.  The only way to get it is to query the annotation back:

```java
Annotation annotation = queryAnnotationById(annotationId);
String calculationsId = annotation.getCalculations().getId();
```

Do this once and persist `calculationsId` alongside `annotationId`; otherwise every export
becomes a two-round-trip operation.

## Deriving Calculations from other Calculations

Level-2 provenance: second-order analysis built on someone else's published calculations.

1. Locate the source Annotation — `IdCriterion` if you have the id, otherwise `TagsCriterion`,
   `TextCriterion`, or `OwnerCriterion`.
2. Read its frames and columns from
   `response.getAnnotationsResult().getAnnotationsList()`, via `getCalculations()`.
3. Compute the new values and build a new `Calculations` object as above.
4. Save an Annotation that links back:

```java
SaveAnnotationRequest.newBuilder()
    .setOwnerId("analyst")
    .addDataSetIds(originalDataSetId)          // still REQUIRED, even here
    .addAnnotationIds(sourceAnnotationId)      // <- the provenance link
    .setName("Normalized RF amplitude RMS")
    .setCalculations(derivedCalculations)
    .build();
```

`dataSetIds` remains required even though the real subject is another Annotation's Calculations.
Reuse the source Annotation's DataSet id — it already names the underlying archive data, so the
chain stays intact.

There is no server-side traversal of the provenance graph.  `annotationIds` is a plain list of
ids; walking a multi-level chain means issuing one `queryAnnotations` per level with an
`IdCriterion`.

## Catalog search over Annotations

`queryAnnotations` offers seven criteria via the `QueryAnnotationsCriterion` oneof:
`IdCriterion.id`, `OwnerCriterion.ownerId`, `DataSetsCriterion.dataSetId`,
`AnnotationsCriterion.annotationId`, `TextCriterion.text` (free-text search over the `name` and
`comment` fields), `TagsCriterion.tagValue`, and `AttributesCriterion` (`key` plus `value`).

```java
QueryAnnotationsRequest.newBuilder()
    .addCriteria(QueryAnnotationsRequest.QueryAnnotationsCriterion.newBuilder()
        .setTagsCriterion(QueryAnnotationsRequest.QueryAnnotationsCriterion.TagsCriterion
            .newBuilder().setTagValue("rf-trip")))       // field is tagValue, not tag
    .addCriteria(QueryAnnotationsRequest.QueryAnnotationsCriterion.newBuilder()
        .setAttributesCriterion(QueryAnnotationsRequest.QueryAnnotationsCriterion
            .AttributesCriterion.newBuilder()
                .setKey("runNumber").setValue("4471")))  // here the field IS 'key'
    .build();
```

The most useful property of this result is that **the associated DataSets arrive fully
populated**.  `Annotation.dataSets` carries the complete `DataSet` contents alongside the bare
`dataSetIds`, so a catalog browser can render each annotation's PV list and time ranges without a
second `queryDataSets` round trip.

`DataSetsCriterion` runs the relationship the other way: given a DataSet id, find everything that
annotates it.  That is the query behind "what does anyone know about this region of the archive".

## Exporting to CSV or XLSX

```java
ExportDataRequest.newBuilder()
    .setDataSetId(dataSetId)
    .setOutputFormat(ExportDataRequest.ExportOutputFormat.EXPORT_FORMAT_CSV)
    .build();

// after checking hasExceptionalResult()
ExportDataResponse.ExportDataResult result = response.getExportDataResult();
String path = result.getFilePath();     // always populated
String url  = result.getFileUrl();      // may be empty -- see below
```

Always set an explicit `outputFormat`.  Its inline proto comment says "Optional", but
`EXPORT_FORMAT_UNSPECIFIED` (the zero value, and therefore the default if you omit the field) is
documented as causing the request to be **rejected**.  In practice the field is required.

`fileUrl` is populated only when the deployment is configured to publish exported files over
HTTP.  `filePath` is the reliable field; treat an empty `fileUrl` as normal, not as an error.

The tabular formats (CSV, XLSX) produce one row per timestamp across the union of the DataSet's
columns.  HDF5 preserves the bucketed structure instead — prefer it when the DataSet spans many
PVs with differing sampling rates, where a tabular flattening would be mostly empty cells.

## Exporting a DataSet plus Calculations to HDF5

The point of combining them is to deliver raw PV data and the values derived from it in one
self-describing file.

```java
CalculationsSpec spec = CalculationsSpec.newBuilder()
    .setCalculationsId(calculationsId)
    .putDataFrameColumns("rf-statistics",
        CalculationsSpec.ColumnNameList.newBuilder()
            .addAllColumnNames(List.of("rf_amp_rms"))
            .build())
    .build();

ExportDataRequest.newBuilder()
    .setDataSetId(dataSetId)
    .setCalculationsSpec(spec)
    .setOutputFormat(ExportDataRequest.ExportOutputFormat.EXPORT_FORMAT_HDF5)
    .build();
```

`dataFrameColumns` is an optional filter.  **Omit the map entirely to include all frames and all
columns.**  Its key is the `CalculationsDataFrame` *name*, and because a map key is by
construction unique, addressing is by name only — there is no index-based addressing.  The proto
does not explicitly require frame names to be distinct within a `Calculations`, but duplicate
names would be unaddressable through this filter, so keep them distinct in practice.

Two things to be aware of when both a DataSet and Calculations are exported to a tabular format.
Neither is specified by the proto — both are server-side behaviors, so verify them against your
deployment before depending on them:

- Column ordering between DataSet columns and the filtered Calculations columns is not defined in
  the proto.  Do not assume a particular order; address columns by name.
- Calculations values that fall outside the DataSet's time range may or may not be included, and
  the response carries no warning either way.  If your calculation extends past the source
  window — a trailing moving average, say — widen the DataSet or export the Calculations on its
  own rather than relying on the trimming behavior.

### Exporting Calculations alone

Leave `dataSetId` empty and set only `calculationsSpec`.  The message-level proto comment is
explicit that `dataSetId` and `calculationsSpec` are each optional and that one or the other must
be present; the inline comment on `dataSetId` saying "Required" is stale.  This is the right call
for sharing derived results without re-exporting bulk archive data.

## Where this area departs from the conventions

These are older methods than the CRUD families described in [conventions.md](conventions.md), and
three differences will bite you:

**No pagination.**  Neither `queryDataSets` nor `queryAnnotations` has `limit`, `pageToken`, or
`nextPageToken`.  Every match comes back in a single response.  Constrain your criteria — an
`OwnerCriterion` alone against a busy archive can return a very large message.

**Empty results may not follow the empty-list convention.**  The project-wide rule is that an
empty query result is a success payload with an empty list.  But the `QueryDataSetsResponse` and
`QueryAnnotationsResponse` proto comments both say the payload is an `ExceptionalResult` when
"the query result is empty".  These contradict each other and we could not determine from the
protos alone which the server actually does.  Write callers that tolerate **both**: check
`hasExceptionalResult()` first, and also handle a zero-length list.

**Criteria combination is ambiguously documented.**  Within `QueryDataSetsCriterion`, the
`IdCriterion` and `OwnerCriterion` comments say "And" while `TextCriterion` and `PvNameCriterion`
say "Or".  The message-level comment and the README both describe compound queries in AND terms
("an `OwnerCriterion` and `TextCriterion` to find DataSets for the specified owner containing the
specified text").  The per-criterion "Or" comments appear stale, but we cannot confirm that from
the protos.  If a query's exact semantics matter, verify empirically against your deployment
rather than relying on either reading.

## Also worth knowing

- **There is no delete for DataSets or Annotations**, and no `patch*` for either.  Records
  accumulate; plan your naming and tagging accordingly.
- **`RESULT_STATUS_REJECT` is the zero value** of `ExceptionalResultStatus`, so a
  default-constructed `ExceptionalResult` reads as a rejection.  Detect failure with the oneof
  case (`hasExceptionalResult()`), never by comparing the status enum against zero.
- **The oneof getters return default instances rather than throwing.**  Reading
  `getSaveDataSetResult()` on an error response yields an empty result with a blank id, not an
  exception — which is exactly how a missing check turns into a confusing downstream failure.
- **Field numbers are not symmetric between the save and query sides.**  `name` is field 4 in
  `SaveAnnotationRequest` and field 5 in `QueryAnnotationsResponse.AnnotationsResult.Annotation`;
  `calculations` is 10 and 11 respectively.  The two messages are not wire-compatible and there
  is no top-level `Annotation` message — the read-side type is the nested one.
- **Stale proto comments in `DataSet`.**  The `id` comment refers to a `createDataSet()` method
  and a `dataSetId` field, neither of which exists.  The method is `saveDataSet()` and the field
  is `id`.
