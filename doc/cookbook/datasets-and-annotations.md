# Data Sets, Annotations, and Export Cookbook

Worked examples for defining DataSets, attaching Annotations and derived Calculations to them,
and exporting the result to HDF5, CSV, or XLSX — all part of the Annotation Service.

Reference documentation: [Data Set API](../../README.md#data-set-api),
[Data Export Methods](../../README.md#data-export-methods),
[Annotation API](../../README.md#annotation-api), and
[Calculations Get Methods](../../README.md#calculations-get-methods).

Shared response-checking, criteria, paging, and time conventions live in
[conventions.md](conventions.md) and are not repeated here.

> The DataSet and Annotation APIs were modernized in 1.16.0 and the changes are **breaking** —
> code written against an earlier release will not compile against these stubs.  See the
> [1.16.0 release notes](https://github.com/osprey-dcs/dp-grpc/releases/tag/rel-1.16.0) for
> what changed and an upgrade checklist.

### Imports used by the examples

```java
import com.ospreydcs.dp.grpc.v1.annotation.Annotation;
import com.ospreydcs.dp.grpc.v1.annotation.DataSet;
import com.ospreydcs.dp.grpc.v1.annotation.DataBlock;
import com.ospreydcs.dp.grpc.v1.annotation.Calculations;
import com.ospreydcs.dp.grpc.v1.annotation.SaveDataSetRequest;
import com.ospreydcs.dp.grpc.v1.annotation.GetDataSetRequest;
import com.ospreydcs.dp.grpc.v1.annotation.DeleteDataSetRequest;
import com.ospreydcs.dp.grpc.v1.annotation.QueryDataSetsRequest;
import com.ospreydcs.dp.grpc.v1.annotation.SaveAnnotationRequest;
import com.ospreydcs.dp.grpc.v1.annotation.GetAnnotationRequest;
import com.ospreydcs.dp.grpc.v1.annotation.DeleteAnnotationRequest;
import com.ospreydcs.dp.grpc.v1.annotation.QueryAnnotationsRequest;
import com.ospreydcs.dp.grpc.v1.annotation.GetCalculationsRequest;
import com.ospreydcs.dp.grpc.v1.annotation.ExportDataRequest;
import com.ospreydcs.dp.grpc.v1.annotation.ExportDataResponse;

import com.ospreydcs.dp.grpc.v1.common.CalculationsSpec;
import com.ospreydcs.dp.grpc.v1.common.Attribute;
import com.ospreydcs.dp.grpc.v1.common.ColumnMetadata;
import com.ospreydcs.dp.grpc.v1.common.ColumnProvenance;
import com.ospreydcs.dp.grpc.v1.common.DataColumn;
import com.ospreydcs.dp.grpc.v1.common.DataValue;
import com.ospreydcs.dp.grpc.v1.common.DataFrame;
import com.ospreydcs.dp.grpc.v1.common.DataTimestamps;
import com.ospreydcs.dp.grpc.v1.common.DoubleColumn;
import com.ospreydcs.dp.grpc.v1.common.SamplingClock;
import com.ospreydcs.dp.grpc.v1.common.TimeRange;
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
- [Recording column-level provenance](#recording-column-level-provenance)
- [Deriving Calculations from other Calculations](#deriving-calculations-from-other-calculations)
- [Catalog search over Annotations](#catalog-search-over-annotations)
- [Reading an annotation's Calculations](#reading-an-annotations-calculations)
- [Deleting DataSets and Annotations](#deleting-datasets-and-annotations)
- [Exporting to CSV or XLSX](#exporting-to-csv-or-xlsx)
- [Exporting a DataSet plus Calculations to HDF5](#exporting-a-dataset-plus-calculations-to-hdf5)
- [Exporting ad-hoc data without saving a DataSet](#exporting-ad-hoc-data-without-saving-a-dataset)
- [Also worth knowing](#also-worth-knowing)

## Model

Three concepts stack on top of each other, and each is the handle for the next.

A **`DataSet`** names a region of the archive.  It is a list of **`DataBlock`** rectangles, each
one a `beginTime`, an `endTime`, and a list of `pvNames`.  Multiple blocks let a single DataSet
cover different PV groups over different windows — for example, RF PVs during a ramp plus
diagnostics PVs during the flat-top that followed.  A DataSet holds *no data*; it is a pointer
into the archive, resolved at query or export time.

An **`Annotation`** attaches meaning to one or more DataSets: a `name`, free-form `description`
text, `tags` for cataloging, key/value `attributes`, links to other Annotations, and optionally a
`Calculations` payload.

**`Calculations`** carries derived values — results you computed, not values the archive
recorded.  The proto's own analogy is an Excel workbook: the `Calculations` object is the
workbook, each `Calculations.CalculationsDataFrame` is a worksheet with its own timestamp axis,
and each column within a frame's `DataFrame` is a column of computed values.

Both entities use **opaque server-generated ids** as their primary key — names are not unique, so
unlike the PV metadata and Configuration APIs there is no natural key.  `getDataSet`,
`deleteDataSet`, `getAnnotation`, `deleteAnnotation`, and `getCalculations` all take an id.

Provenance is recorded at two levels.  At the **document** level, an Annotation's `dataSetIds`
says which archive data a body of work drew on, and its `annotationIds` links to related
Annotations.  At the **column** level, an individual calculated column's `ColumnMetadata` carries
a `ColumnProvenance` whose `derivedFrom` list names the specific source PVs or Calculations
columns it was computed from.  The two are complementary; see
[Recording column-level provenance](#recording-column-level-provenance).

**Query results carry references, not content.**  `queryAnnotations` returns `dataSetIds` and
`calculationsId` — ids only.  Fetch DataSet content with one `queryDataSets` call listing the
ids, and Calculations content with `getCalculations` or `getAnnotation`.

Both `saveDataSet` and `saveAnnotation` are **id-driven upserts**: an empty `id` creates, a
populated `id` replaces in full.

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

### 2. Save it, leaving `id` unset

`SaveDataSetRequest` lists the DataSet's client-settable fields directly — it does not embed a
`DataSet` message.  That is deliberate: `DataSet` now carries server-set audit timestamps, which
must not be accepted as input.

```java
SaveDataSetRequest request = SaveDataSetRequest.newBuilder()
    .setName("2026-07-14 ramp study")           // required
    .setOwnerId("cmcchesney")                   // required
    .setDescription("RF ramp plus flat-top diagnostics for shift 2")
    .addAllDataBlocks(List.of(ramp, flatTop))   // required
    .addAllTags(List.of("ramp-study", "shift-2"))
    .addAttributes(Attribute.newBuilder().setName("runNumber").setValue("4471"))
    .setModifiedBy("cmcchesney")
    .build();

// after checking hasExceptionalResult()
String dataSetId = response.getSaveDataSetResult().getDataSetId();
```

`dataSetId` is the handle for *every* later step — annotating, retrieving, exporting, and
deleting all take it — so persist it rather than re-deriving it by search.

`tags` and `attributes` give DataSets the same cataloging vocabulary the other entities have, and
both are searchable via `queryDataSets`.

## Updating an existing DataSet

There is no implemented `patchDataSet` — the RPC exists as a reserved placeholder and returns an
error today.  To change a DataSet you re-save it with its `id` populated, and the save is
**full-replace**: the `dataBlocks` list you send *replaces* the stored one, it does not merge
with it.

```java
// 1. fetch the current DataSet
DataSet existing = getDataSetById(dataSetId);

// 2. rebuild with the id set and the COMPLETE new state
SaveDataSetRequest updated = SaveDataSetRequest.newBuilder()
    .setId(existing.getId())                          // presence of id => replace
    .setName(existing.getName())
    .setOwnerId(existing.getOwnerId())
    .setDescription(existing.getDescription())        // omit and it is cleared
    .addAllDataBlocks(existing.getDataBlocksList())   // carry forward
    .addDataBlocks(newBlock)                          // then extend
    .addAllTags(existing.getTagsList())               // omit and these are cleared too
    .addAllAttributes(existing.getAttributesList())
    .setModifiedBy("cmcchesney")
    .build();
```

The read-modify-write is not optional.  Sending only the block you want to add silently discards
the others — see [Save semantics](conventions.md#save-semantics-full-replace).

Do not copy `createdTime` or `updatedTime` across; they are server-set and the request has no
fields for them.

Because Annotations reference DataSets by id, an update is visible to every Annotation already
pointing at it.  Widening a DataSet after it has been annotated changes what those Annotations
describe; if that is not what you want, create a new DataSet instead.

## Finding a DataSet someone else made

Search before creating, so that shared regions of interest do not proliferate as near-duplicates.
`queryDataSets` supports seven criteria, each carried by exactly one member of the
`QueryDataSetsCriterion` oneof:

| Criterion | Field(s) | Matches |
|---|---|---|
| `IdCriterion` | `ids` | DataSet id |
| `OwnerCriterion` | `ownerIds` | owner |
| `NameCriterion` | `exact`, `prefix`, `contains` | name |
| `TextCriterion` | `text` | full text over the indexed fields (`name`, `description`) |
| `PvNameCriterion` | `names` | a PV name appearing in any `DataBlock` |
| `TagsCriterion` | `values` | tag value |
| `AttributesCriterion` | `key`, `values` | attribute key and optional value(s) |

Criteria in the list are ANDed; values within one criterion are ORed.

```java
QueryDataSetsRequest.newBuilder()
    .addCriteria(QueryDataSetsRequest.QueryDataSetsCriterion.newBuilder()
        .setPvNameCriterion(QueryDataSetsRequest.QueryDataSetsCriterion.PvNameCriterion
            .newBuilder().addNames("LINAC:RF:AMP")))
    .addCriteria(QueryDataSetsRequest.QueryDataSetsCriterion.newBuilder()
        .setOwnerCriterion(QueryDataSetsRequest.QueryDataSetsCriterion.OwnerCriterion
            .newBuilder().addOwnerIds("cmcchesney")))
    .setLimit(50)
    .build();
```

Then iterate `response.getDataSetsResult().getDataSetsList()` and inspect each DataSet's
`dataBlocks` to confirm the coverage actually matches your window — `PvNameCriterion` matches on
the PV name alone and says nothing about time.

There is no time-range criterion for DataSets, so time filtering is a client-side pass over the
returned blocks.

Results are paged and ordered by `id` ascending; follow `nextPageToken` to retrieve them all.  An
unset `limit` means a server-configured default page size, **not** an unbounded result — see
[Pagination](conventions.md#pagination).

When you already have the id, `getDataSet` is the direct route:

```java
GetDataSetRequest.newBuilder().setDataSetId(dataSetId).build();
// response.getGetDataSetResult().getDataSet()
```

## Attaching a descriptive Annotation

Required fields are `ownerId`, at least one `dataSetIds` entry, and `name`.

```java
SaveAnnotationRequest.newBuilder()
    .setOwnerId("cmcchesney")
    .addDataSetIds(dataSetId)                  // required, at least one
    .setName("RF trip during ramp")
    .setDescription("Amplitude interlock fired at t1; see attributes for run number.")
    .addAllTags(List.of("rf-trip", "shift-2", "reviewed"))
    .addAttributes(Attribute.newBuilder().setName("runNumber").setValue("4471"))
    .addAttributes(Attribute.newBuilder().setName("experimentId").setValue("E-2026-113"))
    .setModifiedBy("cmcchesney")
    .build();

// after checking hasExceptionalResult()
String annotationId = response.getSaveAnnotationResult().getAnnotationId();
```

`Attribute` uses **`name`** for the key, not `key`.  The query-side `AttributesCriterion` uses
`key`.  Mixing these two up is the easiest mistake to make in this area, and because both are
plain strings the compiler will not catch it.

Use `tags` for values you will search by exactly, and `attributes` for structured facts that have
a key.  `description` and `name` are the client-settable fields reachable by the Annotation
`TextCriterion` free-text search.

## Publishing derived Calculations

This is document-level provenance: you computed something from raw PV data and want the result
stored alongside a record of exactly which archive data it came from.

### 1. Create a DataSet describing the *inputs*

Its DataBlocks must reference the PVs and time ranges the computation actually consumed.  That
DataSet is the provenance record; skipping it leaves the calculation unattributable.

### 2. Build the Calculations

A `CalculationsDataFrame` is a name plus a `common.DataFrame` — the same message used as the unit
of ingestion.  Calculation output therefore uses the same typed column types as ingested data:

```java
DoubleColumn rmsColumn = DoubleColumn.newBuilder()
    .setName("rf_amp_rms")                            // calculation name, not a PV name
    .addAllValues(List.of(12.7, 12.8, 12.9))
    .build();

Calculations calculations = Calculations.newBuilder()
    .addCalculationDataFrames(Calculations.CalculationsDataFrame.newBuilder()
        .setName("rf-statistics")                     // required; distinct within the Calculations
        .setFrame(DataFrame.newBuilder()
            .setDataTimestamps(DataTimestamps.newBuilder()
                .setSamplingClock(SamplingClock.newBuilder()
                    .setStartTime(ts(t0))
                    .setPeriodNanos(1_000_000_000L)
                    .setCount(3)))
            .addDoubleColumns(rmsColumn)))
    .build();
```

Things to get right here:

- **The field is `calculationDataFrames` (singular "calculation"), the message type is
  `CalculationsDataFrame` (plural).**  Java: `addCalculationDataFrames()`.
- **The frame's columns live on its `DataFrame`, not on the `CalculationsDataFrame`.**  Set the
  timestamps and the columns on the `DataFrame` you pass to `setFrame()`.
- **Every column must have exactly one value per timestamp** defined by the frame's
  `DataTimestamps` — `SamplingClock.count`, or the size of the `TimestampList`.
- **Frame names must be distinct within a Calculations object.**  Frame names address frames in
  the `CalculationsSpec` filter and in provenance links, so duplicates are unaddressable and are
  rejected.

Use a `SamplingClock` when the output is uniformly spaced and a `TimestampList` when it is not
(event-triggered results, or output that inherits irregular input timestamps).

**Sparse or missing values.**  A calculation that produces results at a different or sparser
cadence than its siblings gets **its own frame with its own time axis** rather than a dense
column padded with gaps — frames are cheap, and every column is dense on its own frame's axis.
When values are genuinely missing at some timestamps of a shared axis, the legacy `DataColumn`
type remains available through `DataFrame.dataColumns` as an escape hatch, because an unset
`DataValue` oneof expresses "no result here" and the dense typed columns cannot:

```java
DataColumn sparse = DataColumn.newBuilder()
    .setName("rf_amp_peak")
    .addDataValues(DataValue.newBuilder().setDoubleValue(14.2))
    .addDataValues(DataValue.newBuilder().build())    // <- MISSING: no oneof member set
    .addDataValues(DataValue.newBuilder().setDoubleValue(14.4))
    .build();
```

On the read side, detect it with `value.getValueCase() == DataValue.ValueCase.VALUE_NOT_SET`.
Prefer the typed columns otherwise.

### 3. Save the Annotation carrying the Calculations

```java
SaveAnnotationRequest.newBuilder()
    .setOwnerId("cmcchesney")
    .addDataSetIds(inputDataSetId)          // the provenance link to archive data
    .setName("RF amplitude RMS, shift 2")
    .setDescription("1 Hz RMS over LINAC:RF:AMP")
    .setCalculations(calculations)
    .build();

// after checking hasExceptionalResult()
String annotationId   = response.getSaveAnnotationResult().getAnnotationId();
String calculationsId = response.getSaveAnnotationResult().getCalculationsId();
```

`saveAnnotation` is the only write path for Calculations — there is no `saveCalculations`.  The
`id` field of the `Calculations` object you send is ignored; the server assigns it and returns it
as `calculationsId`, which is the key `getCalculations`, `CalculationsSpec`, and provenance links
all take.

> **Full-replace applies to calculations.**  Re-saving an Annotation without its `calculations`
> field **clears the stored Calculations**.  When updating an annotation that carries
> calculations, read it back with `getAnnotation` and resend them along with your changes.

## Recording column-level provenance

Document-level provenance says which DataSet a body of work drew on.  Column-level provenance
says which specific columns *this* column was computed from, in a form a client can traverse.  It
rides in the `ColumnMetadata` every column message carries:

```java
ColumnProvenance provenance = ColumnProvenance.newBuilder()
    .setProcess("1 Hz RMS")
    .addDerivedFrom(ColumnProvenance.ColumnSource.newBuilder()
        .setPvName("LINAC:RF:AMP")
        .setTimeRange(TimeRange.newBuilder()
            .setBeginTime(ts(t0))
            .setEndTime(ts(t1))))
    .build();

DoubleColumn rmsColumn = DoubleColumn.newBuilder()
    .setName("rf_amp_rms")
    .addAllValues(List.of(12.7, 12.8, 12.9))
    .setMetadata(ColumnMetadata.newBuilder().setProvenance(provenance))
    .build();
```

To link to a column of another Calculations object rather than to an archived PV, set the other
arm of the `origin` oneof:

```java
ColumnProvenance.ColumnSource.newBuilder()
    .setCalculationsColumn(ColumnProvenance.CalculationsColumn.newBuilder()
        .setCalculationsId(sourceCalculationsId)
        .setFrameName("rf-statistics")
        .setColumnName("rf_amp_rms"))
    .build();
```

Notes:

- The oneof is named **`origin`**, not `source` — `ColumnProvenance.source` is the separate
  free-form string field, which is retained alongside these links.  Human description and
  machine-traversable link are different jobs.
- `derivedFrom` is repeated because a derived column may have several inputs, such as a
  difference of two PVs.
- The per-source `timeRange` is optional and matters mainly for aggregations, whose input
  interval is not implied by the output column's own timestamps — a daily mean stamped at
  midnight consumes the preceding day.
- **Links are stored, never validated.**  Nothing checks that the target exists, and deleting a
  referenced record leaves the link dangling.  A link that resolves to nothing means the target
  was deleted; readers must tolerate that.
- The same mechanism works for ingestion-side derived data, since `ColumnMetadata` is carried by
  every column message type.  As a rule of thumb: one-time analysis products belong in Annotation
  Calculations; continuously-computed derived streams belong in ingestion as ordinary PVs.

## Deriving Calculations from other Calculations

Second-order analysis built on someone else's published calculations.

1. Locate the source Annotation — `IdCriterion` if you have the id, otherwise `TagsCriterion`,
   `NameCriterion`, `TextCriterion`, or `OwnerCriterion`.
2. Read its calculations with `getCalculations(calculationsId)`, using the `calculationsId` the
   query returned.
3. Compute the new values and build a new `Calculations` object as above.
4. Save an Annotation that links back:

```java
SaveAnnotationRequest.newBuilder()
    .setOwnerId("analyst")
    .addDataSetIds(originalDataSetId)          // still REQUIRED, even here
    .addAnnotationIds(sourceAnnotationId)      // <- document-level provenance link
    .setName("Normalized RF amplitude RMS")
    .setCalculations(derivedCalculations)
    .build();
```

`dataSetIds` remains required even though the real subject is another Annotation's Calculations.
Reuse the source Annotation's DataSet id — it already names the underlying archive data, so the
chain stays intact.

For a precise record of *which columns* fed the new ones, add
[column-level provenance](#recording-column-level-provenance) with a `CalculationsColumn` source
alongside the `annotationIds` link.  The document link says "this work built on that work"; the
column links say exactly how.

There is no server-side traversal of the provenance graph.  `annotationIds` is a plain list of
ids; walking a multi-level chain means one `queryAnnotations` per level with an `IdCriterion`, or
one `getAnnotation` per id.

## Catalog search over Annotations

`queryAnnotations` offers eight criteria via the `QueryAnnotationsCriterion` oneof:

| Criterion | Field(s) | Matches |
|---|---|---|
| `IdCriterion` | `ids` | Annotation id |
| `OwnerCriterion` | `ownerIds` | owner |
| `DataSetsCriterion` | `dataSetIds` | id of an associated DataSet |
| `AnnotationsCriterion` | `annotationIds` | id of an associated Annotation |
| `NameCriterion` | `exact`, `prefix`, `contains` | name |
| `TextCriterion` | `text` | full text over the indexed fields (`name`, `description`) |
| `TagsCriterion` | `values` | tag value |
| `AttributesCriterion` | `key`, `values` | attribute key and optional value(s) |

```java
QueryAnnotationsRequest.newBuilder()
    .addCriteria(QueryAnnotationsRequest.QueryAnnotationsCriterion.newBuilder()
        .setTagsCriterion(QueryAnnotationsRequest.QueryAnnotationsCriterion.TagsCriterion
            .newBuilder().addValues("rf-trip")))
    .addCriteria(QueryAnnotationsRequest.QueryAnnotationsCriterion.newBuilder()
        .setAttributesCriterion(QueryAnnotationsRequest.QueryAnnotationsCriterion
            .AttributesCriterion.newBuilder()
                .setKey("runNumber").addValues("4471")))
    .setLimit(50)
    .build();
```

Criteria in the list are ANDed and values within one criterion are ORed, so the query above wants
annotations that carry the `rf-trip` tag **and** have `runNumber=4471`.  Two tags in one
`TagsCriterion` means "either tag"; to require both, add two separate `TagsCriterion` entries.

Results are paged and ordered by `id` ascending; follow `nextPageToken`.

**Results carry ids, not embedded content.**  Each returned `Annotation` has `dataSetIds` and
`calculationsId` populated and its `calculations` field empty.  To render a catalog listing with
each annotation's PV list and time ranges, gather the ids across the page and issue **one**
`queryDataSets` with an `IdCriterion`:

```java
List<String> ids = response.getAnnotationsResult().getAnnotationsList().stream()
    .flatMap(a -> a.getDataSetIdsList().stream())
    .distinct()
    .toList();

QueryDataSetsRequest.newBuilder()
    .addCriteria(QueryDataSetsRequest.QueryDataSetsCriterion.newBuilder()
        .setIdCriterion(QueryDataSetsRequest.QueryDataSetsCriterion.IdCriterion
            .newBuilder().addAllIds(ids)))
    .build();
```

That is one round trip for the whole page.  Fetching them with a `getDataSet` per id instead is
the N+1 this design exists to avoid.

`DataSetsCriterion` runs the relationship the other way: given a DataSet id, find everything that
annotates it.  That is the query behind "what does anyone know about this region of the archive",
and it is also how you find the annotations that block a `deleteDataSet`.

## Reading an annotation's Calculations

`calculationsId` doubles as the presence indicator — an empty one means the Annotation has no
calculations, and a non-empty one paired with an empty `calculations` field means the content was
simply not fetched by the method you called.

Two ways to get the content:

```java
// Just the calculations, no annotation payload -- the click-through case.
GetCalculationsRequest.newBuilder().setCalculationsId(calculationsId).build();
// response.getGetCalculationsResult().getCalculations()

// The whole annotation, with calculations populated inline.
GetAnnotationRequest.newBuilder().setAnnotationId(annotationId).build();
// response.getGetAnnotationResult().getAnnotation().getCalculations()
```

`getAnnotation` is the only method that returns Calculations content inside an `Annotation`.  It
still returns `dataSetIds` as ids.

Calculations have no save, delete, or query method of their own: they are written through
`saveAnnotation`, deleted with their Annotation, and discovered through `queryAnnotations`.  Only
retrieval has a standalone path, so that a client holding a `calculationsId` need not fetch an
annotation to use it.

## Deleting DataSets and Annotations

```java
DeleteAnnotationRequest.newBuilder().setAnnotationId(annotationId).build();
DeleteDataSetRequest.newBuilder().setDataSetId(dataSetId).build();
```

The two have deliberately different referential rules:

- **`deleteDataSet` is rejected while any Annotation references the DataSet** in its
  `dataSetIds`.  Delete or update those annotations first; find them with `queryAnnotations` and
  a `DataSetsCriterion`.  This is a containment-strength association — an annotation without its
  subject is meaningless.
- **`deleteAnnotation` is not blocked by anything.**  Other annotations' `annotationIds` and any
  `ColumnProvenance.derivedFrom` links into its calculations are soft associations and are left
  to dangle.  Deleting an Annotation deletes its Calculations with it.

So the order for tearing down a chain is: annotations first, then the DataSets they referenced.

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

Always set an explicit `outputFormat`.  `EXPORT_FORMAT_UNSPECIFIED` is the zero value, and
therefore the default if you omit the field, and it causes the request to be rejected.

`fileUrl` is populated only when the deployment is configured to publish exported files over
HTTP.  `filePath` is the reliable field; treat an empty `fileUrl` as normal, not as an error.

The tabular formats (CSV, XLSX) produce one row per timestamp across the union of the exported
columns.  HDF5 preserves the bucketed structure instead — prefer it when the data spans many PVs
with differing sampling rates, where a tabular flattening would be mostly empty cells.

> **Tabular formats are scalar-only.**  CSV and XLSX can only represent scalar columns.  Data
> containing array, image, or struct columns — including a Calculations frame using those typed
> columns — exports to HDF5, but a CSV or XLSX request for it is rejected.

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
columns.**  Its key is the `CalculationsDataFrame` *name* — which is why frame names must be
distinct within a Calculations object.

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

Leave `dataSetId` empty and set only `calculationsSpec`.  This is the right call for sharing
derived results without re-exporting bulk archive data.

## Exporting ad-hoc data without saving a DataSet

For a one-off export that does not warrant a saved DataSet, put `DataBlock`s directly on the
request.  The server treats them as a transient dataset:

```java
ExportDataRequest.newBuilder()
    .addDataBlocks(DataBlock.newBuilder()
        .setBeginTime(ts(t0))
        .setEndTime(ts(t1))
        .addAllPvNames(List.of("LINAC:RF:AMP", "LINAC:RF:PHASE")))
    .setOutputFormat(ExportDataRequest.ExportOutputFormat.EXPORT_FORMAT_CSV)
    .build();
```

`dataSetId`, `dataBlocks`, and `calculationsSpec` are each optional individually, but **at least
one must be present** or the request is rejected.  They may be combined freely — an export can
draw on a saved DataSet, some ad-hoc blocks, and a Calculations object at once.

Use `dataSetId` when the selection is worth keeping, sharing, or annotating; use `dataBlocks`
when it is genuinely throwaway.  Ad-hoc blocks leave no record of what was exported.

## Also worth knowing

- **`RESULT_STATUS_REJECT` is the zero value** of `ExceptionalResultStatus`, so a
  default-constructed `ExceptionalResult` reads as a rejection.  Detect failure with the oneof
  case (`hasExceptionalResult()`), never by comparing the status enum against zero.
- **The oneof getters return default instances rather than throwing.**  Reading
  `getSaveDataSetResult()` on an error response yields an empty result with a blank id, not an
  exception — which is exactly how a missing check turns into a confusing downstream failure.
- **An empty query result is an empty list, not an `ExceptionalResult`.**  This holds for both
  `queryDataSets` and `queryAnnotations`, as it does across the API.
- **`patchDataSet` and `patchAnnotation` exist but are not implemented.**  They are reserved
  placeholders per the standard CRUD pattern and return an error today; use the full-replace
  `save*` methods.
- **There is deliberately no `bulkSave*` for either entity**, unlike PV metadata and
  configuration activations — DataSets and Annotations are not bulk-imported from external
  systems.
- **`ownerId` and `modifiedBy` are different fields with different jobs.**  `ownerId` is
  ownership and does not change on edit; `modifiedBy` records who performed the most recent save.
