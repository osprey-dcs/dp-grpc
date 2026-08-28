# dp-grpc repo

This repo contains the gRPC API definition for the Machine Learning Data Platform (MLDP) Ingestion, Query, Annotation, and Ingestion Stream Services.  The [data-platform repo](https://github.com/osprey-dcs/data-platform) is the project home page and a good place to learn about the bigger picture.

This document includes the following information:

- [gRPC communication framework overview](#grpc-overview)
- [MLDP API overview](#mldp-api-overview)
- [Data Platform gRPC API proto files](#data-platform-grpc-api-proto-files)
- [Service-centric API summary](#service-api-summary)
- [Entity-centric API summary](#entity-api-summary)
- [API use cases and patterns](#api-use-cases-and-patterns)
- [API cookbook: worked examples](#api-cookbook)
- [Entity API details](#entity-api-details)
  - [Provider API](#provider-api)
  - [PV Time-Series Data API](#pv-time-series-data-api)
  - [Ingestion Request Status API](#ingestion-request-status-api)
  - [PV Metadata API](#pv-metadata-api)
  - [Machine Configuration API](#machine-configuration-api)
  - [Configuration Activation API](#configuration-activation-api)
  - [Data Set API](#data-set-api)
  - [Annotation API](#annotation-api)
- [Data Platform API conventions](#data-platform-API-conventions)
- [Example Java code for calling the API](#example-java-grpc-api-code)


---
## gRPC Overview

The Data Platform API is built using the gRPC high-performance communication framework.

[gRPC is a framework](https://grpc.io/docs/what-is-grpc/introduction/) that allows a client application to call a method on a server application.  Defining an API with gRPC consists of identifying the services to be provided by the application, specifying the methods that can be called remotely for each service along with the method parameters and return types.

Underlying the gRPC framework is another Google-developed technology, [Protocol Buffers](https://protobuf.dev/overview), which is an open source mechanism for serializing structured data.  gRPC uses Protocol Buffers as both the Interface Definition Language (IDL), and as the underlying message interchange format.

The gRPC API is defined using "proto" files (a text file with a ".proto" extension).  Proto files contain definitions for services, service methods, and the data types used by those methods.  Data types are called "messages", and each message specifies a series of name-value pairs called "fields".  The definition of one message can be nested within another, limiting the scope of the nested data type to the message it is nested within.

Support is provided for compiling gRPC API code in a variety of [programming languages](https://grpc.io/docs/languages/).  The "protoc" compiler builds a framework of "stubs" in the target programming language for utilizing the API defined in the "proto" files.

See the links above for some simple examples of services, methods, and messages.


---
## MLDP API Overview

The MLDP gRPC API defines APIs for four individual services:

- The Ingestion Service API focuses on high-performance ingestion of process variable (PV) time-series data in a large-scale research facility like a particle accelerator to an archive.
- The Query Service API is used to retrieve PV time-series data from the archive.
- The Annotation Service API provides mechanisms for use by researchers and automated data cleaning tools for managing a PV catalog, describing machine configuration at a given point in time, defining datasets, adding annotations, uploading calculations, marking individual data samples, and exporting data.
- The Ingestion Stream Service provides downstream access to real-time PV time-series data from the PV ingestion stream.

Each service API is described in more detail below.

### Ingestion Service API

The main objective of the Ingestion Service API is to provide a streamlined high-performance pipleline for capturing facility PV time-series data to the archive.  The API defines a set of methods for streaming "bucketed" data to the archive, where each bucket contains PV sample data for a specified time range.  The API offers a number of column-oriented message data structures optimized for handling heterogeneous sample data including scalars, arrays of scalars, strings, enums, stuctures, images, and arbitrary binary data.  Because ingestion requests are processed asynchronously for maximum performance, a query method is provided for determining the status of ingestion requests.  A mechanism for subscribing to PV data from the ingestion stream is also provided.

### Query Service API

The core feature of the Query Service API is retrieval of PV time-series data over a range of time.  There are both unary and streaming query methods, with results that contain either bucketed or tabular data.  Methods are also provided for querying archive ingestion statistics for PVs and data providers.

A second generation of the time-series query API (Query API V2) is also provided (see [PV data query V2 methods](#pv-data-query-v2-methods)).  V2 introduces a common `QuerySpec` shared by all query methods that describes *what* data to retrieve — time range, PV selection (explicit list, name pattern, or PV metadata criteria), machine-configuration filtering, and sample-status filtering — independently of *how* results are returned.  Bucket-oriented methods return the archive's native `DataBucket` objects, while sample-oriented methods return an aligned, column-oriented table suited to Python and analysis workflows.  The original V1 query methods remain available for backward compatibility.

### Annotation Service API

The Annotation Service API provides tools for augmenting the PV time-series data archive with facility-specific information.  The core feature is identifying datasets, each containing blocks of data defined by a list of PVs and a range of time, and adding annotations to those datasets.  An annotation includes descriptive elements like freeform text comment, keywords, and key-value attributes, and may also include user-defined calculations that use links for tracking data provenance.  The API also includes tools for exporting datasets and calculations to common file formats including HDF5, CSV, and XLSX.  A PV metadata API is provided for associating user-defined metadata (aliases, tags, attributes, description) with PVs and using that metadata to discover PVs of interest.  A machine configuration API is also provided for recording and querying the operational state of the accelerator at a point in time, including reusable configuration definitions (e.g., `TopOff`, `3GeV`, `UserOps`) and time-stamped activation intervals that can be loaded from operational calendars or recorded in real time.  Finally, a sample status API allows users and automated systems (e.g., ML anomaly detectors, data cleaning pipelines, or operators) to assign status codes to individual PV samples at specific timestamps, supporting data quality assessment and multiple independent interpretations of the same archived data.

### Ingestion Stream Service API

The Ingestion Stream Service layers tools on top of the PV data subscription mechanism provided by the Ingestion Service.  The initial implementation includes a method for subscribing to PV data events, to receive an event notification when a trigger condition is satisfied optionally to include data for a set of target PVs for a specified time window around the event time.  Under investigation is a means for executing user-defined code as a plugin to the service. 


---
## Data Platform gRPC API Proto Files

The Data Platform API is defined in the following _proto_ files, located in this repo's ___src/main/proto___ directory:

- [___ingestion.proto___](https://github.com/osprey-dcs/dp-grpc/blob/main/src/main/proto/ingestion.proto) - Ingestion Service API
- [___query.proto___](https://github.com/osprey-dcs/dp-grpc/blob/main/src/main/proto/query.proto) - Query Service API
- [___annotation.proto___](https://github.com/osprey-dcs/dp-grpc/blob/main/src/main/proto/annotation.proto) - Annotation Service API
- [___ingestion_stream.proto___](https://github.com/osprey-dcs/dp-grpc/blob/main/src/main/proto/ingestion_stream.proto) - Ingestion Stream Service API
- [___common.proto___](https://github.com/osprey-dcs/dp-grpc/blob/main/src/main/proto/common.proto) - Common data structures shared by  the Service APIs 


---
## Service API Summary
The table below gives an overview of the Data Platform API organized by service.  Links to additional details are provided for each method category.

| Service          | API Methods                                                                                                                                                                                                                                                                                                                                                                                                                              |
|------------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Ingestion        | [Provider&nbsp;registration](#provider-registration-methods)<br>[PV&nbsp;data&nbsp;ingestion](#pv-data-ingestion-methods)<br>[PV&nbsp;data&nbsp;subscription](#pv-data-subscription-methods)<br>[Request&nbsp;Status&nbsp;query](#request-status-query-methods)<br>                                                                                                                                                                      |
| Query            | [PV&nbsp;data&nbsp;query](#pv-data-query-methods)<br>[PV&nbsp;data&nbsp;query&nbsp;V2](#pv-data-query-v2-methods)<br>[PV&nbsp;stats&nbsp;query](#pv-stats-query-methods)<br>[Provider&nbsp;query](#provider-query-methods)<br>[Provider&nbsp;stats&nbsp;query](#provider-stats-query-methods)<br>                                                                                                                                                                                                        |
| Annotation       | [PV&nbsp;metadata&nbsp;save](#pv-metadata-save-methods)<br>[PV&nbsp;metadata&nbsp;query](#pv-metadata-query-methods)<br>[PV&nbsp;metadata&nbsp;get](#pv-metadata-get-methods)<br>[PV&nbsp;metadata&nbsp;delete](#pv-metadata-delete-methods)<br>[Configuration&nbsp;save](#configuration-save-methods)<br>[Configuration&nbsp;query](#configuration-query-methods)<br>[Configuration&nbsp;Activation&nbsp;save](#configuration-activation-save-methods)<br>[Configuration&nbsp;Activation&nbsp;query](#configuration-activation-query-methods)<br>[Sample&nbsp;Status&nbsp;save](#sample-status-save-methods)<br>[Sample&nbsp;Status&nbsp;query](#sample-status-query-methods)<br>[Sample&nbsp;Status&nbsp;delete](#sample-status-delete-methods)<br>[Data&nbsp;Set&nbsp;save](#data-set-save-methods)<br>[Data&nbsp;Set&nbsp;query](#data-set-query-methods)<br>[Data&nbsp;Set&nbsp;get](#data-set-get-methods)<br>[Data&nbsp;Set&nbsp;delete](#data-set-delete-methods)<br>[Data&nbsp;export](#data-export-methods)<br>[Annotation&nbsp;save](#annotation-save-methods)<br>[Annotation&nbsp;query](#annotation-query-methods)<br>[Annotation&nbsp;get](#annotation-get-methods)<br>[Annotation&nbsp;delete](#annotation-delete-methods)<br>[Calculations&nbsp;get](#calculations-get-methods)<br> |
| Ingestion Stream | [Data&nbsp;Event&nbsp;subscription](#pv-data-event-subscription-methods)<br>                                                                                                                                                                                                                                                                                                                                                             |

---
## Entity API Summary

The table below gives an overview of the Data Platform API organized by entity.  A brief description of each entity is provided with links to additional details about API support for that entity.

| Entity   | Description | API Methods                                                                                                                                                                                                                                                                                                                                                                         |
|----------|-------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Provider | An infrastructure component that sends correlated PV time-series data to the archive.  Might be associated with an EPICS IOC. | [Provider&nbsp;registration](#provider-registration-methods)<br>[Provider&nbsp;query](#provider-query-methods)<br>[Provider&nbsp;stats&nbsp;query](#provider-stats-query-methods)<br>                                                                                                                                         |
| PV Time-Series Data | The core of the MLDP archive is correlated PV time-series data captured from devices in an accelerator facility. | [PV&nbsp;data&nbsp;ingestion](#pv-data-ingestion-methods)<br>[PV&nbsp;data&nbsp;query](#pv-data-query-methods)<br>[PV&nbsp;data&nbsp;query&nbsp;V2](#pv-data-query-v2-methods)<br>[PV&nbsp;data&nbsp;subscription](#pv-data-subscription-methods)<br>[Data&nbsp;Event&nbsp;subscription](#pv-data-event-subscription-methods)<br>[PV&nbsp;stats&nbsp;query](#pv-stats-query-methods)<br>      |
| PV Metadata | User-defined metadata associated with a PV, including aliases, tags, key-value attributes, and description.  Used to discover and identify PVs of interest. | [PV&nbsp;metadata&nbsp;save](#pv-metadata-save-methods)<br>[PV&nbsp;metadata&nbsp;query](#pv-metadata-query-methods)<br>[PV&nbsp;metadata&nbsp;get](#pv-metadata-get-methods)<br>[PV&nbsp;metadata&nbsp;delete](#pv-metadata-delete-methods)<br>                                                                               |
| Ingestion Request Status | Data ingestion requests are handled asynchronously to maximize performance, so the disposition of individual requests is recorded in a Request Status record. | [Request&nbsp;Status&nbsp;query](#request-status-query-methods)<br>                                                                                                                                                                                                                                                            |
| Machine Configuration | A reusable named definition of a machine mode or operational state (e.g., `TopOff`, `3GeV`, `UserOps`), belonging to a category, with optional parent hierarchy, tags, and attributes.  Used to describe the accelerator state for interpretation of associated PV data. | [Configuration&nbsp;save](#configuration-save-methods)<br>[Configuration&nbsp;query](#configuration-query-methods)<br>                                                                                                                                                                                    |
| Configuration Activation | A time interval during which a Machine Configuration was active.  Supports both live recording and retroactive loading from operational calendars.  Multiple configurations may be active simultaneously if they belong to different categories. | [Configuration&nbsp;Activation&nbsp;save](#configuration-activation-save-methods)<br>[Configuration&nbsp;Activation&nbsp;query](#configuration-activation-query-methods)<br>                                                                                                                              |
| Sample Status | A status code assigned to an individual PV sample at a specific timestamp, within a named domain (the status code semantics contract) and layer (the producer stream).  Supports data quality flags, ML anomaly labels, and operator overrides; sparse labeling is supported, and unlabeled samples carry no assertion. | [Sample&nbsp;Status&nbsp;save](#sample-status-save-methods)<br>[Sample&nbsp;Status&nbsp;query](#sample-status-query-methods)<br>[Sample&nbsp;Status&nbsp;delete](#sample-status-delete-methods)<br>                                                                                                       |
| Data Set | A Data Set identifies PV data of interest in the archive through the use of Data Blocks, each one identifying a list of PVs and range of time. | [Data&nbsp;Set&nbsp;save](#data-set-save-methods)<br>[Data&nbsp;Set&nbsp;query](#data-set-query-methods)<br>[Data&nbsp;Set&nbsp;get](#data-set-get-methods)<br>[Data&nbsp;Set&nbsp;delete](#data-set-delete-methods)<br>[Data&nbsp;export](#data-export-methods)<br>                                                          |
| Annotation | Annotations are used to annotate Data Sets in the archive with descriptive information, data associations, Calculations, and provenance tracking information. | [Annotation&nbsp;save](#annotation-save-methods)<br>[Annotation&nbsp;query](#annotation-query-methods)<br>[Annotation&nbsp;get](#annotation-get-methods)<br>[Annotation&nbsp;delete](#annotation-delete-methods)<br>                                                                                                            |
| Calculations | User-defined analysis output attached to an Annotation: named data frames of calculated columns, sharing the typed column types and per-column metadata used for ingested PV data.  Owned by the Annotation, but separately stored and separately retrievable by id. | [Calculations&nbsp;get](#calculations-get-methods)<br>[Annotation&nbsp;save](#annotation-save-methods)<br>[Data&nbsp;export](#data-export-methods)<br>                                                                                                                                                                          |



---
## API Use Cases and Patterns
The Data Platform API is intended to support the following use cases and patterns:
- Register ingestion data Providers, query Provider details and archive ingestion statistics.
- Ingest PV time-series data, either in continuous or batch mode.
- Subscribe to PV data and data events from the ingestion stream.
- Monitor ingestion Request Status records for errors and other problems.
- Query PV time-series data and archive ingestion statistics.
- Save and query user-defined PV metadata (aliases, tags, attributes, description) to discover and identify PVs of interest.
- Record machine configurations and the time intervals during which they were active, either in real time or by loading from operational calendars.
- Query which machine configurations were active at a specific point in time or during a time range.
- Correlate PV time-series data with machine configuration state for analysis and comparison (e.g., compare orbit data during TopOff vs UserOps).
- Assign status codes to individual PV samples (e.g., ML anomaly labels, data quality flags, operator overrides), in multiple independent domains and layers.
- Filter time-series query results by sample status (e.g., drop suspect data, or return only samples labeled anomalous).
- Create Data Sets identifying archive data blocks of interest by PVs and time range.
- Annotate Data Sets by adding descriptive information, linking to associated other Data Sets and Annotations, adding user-defined Calculations, and tracking data provenance.
- Query Annotations and identify Data Sets of interest.
- Record column-level provenance for derived data, linking a calculated column to the PVs or Calculations columns it was computed from.
- Retrieve Calculations on their own by id, without loading the owning Annotation.
- Export Data including Data Sets, ad-hoc data blocks, and Calculations.


## API Cookbook

The sections below describe each API method, request, and response in detail.  For task-oriented
worked examples that span multiple calls — "how do I actually do X?" — see the
**[API Cookbook](doc/cookbook/README.md)**.

| Recipe | Covers |
|---|---|
| [API conventions](doc/cookbook/conventions.md) | Patterns shared by every method: `oneof result` handling, paging, criteria AND/OR rules, full-replace `save*`, half-open time ranges |
| [Provider registration](doc/cookbook/provider-registration.md) | Registering before ingesting, re-registering on startup, finding providers, reading archive statistics |
| [Ingesting PV data](doc/cookbook/ingestion.md) | The three ingestion methods, building a `DataFrame`, choosing a column type, and checking async request status |
| [Subscriptions](doc/cookbook/subscriptions.md) | Tailing live PVs, triggering on a PV condition, capturing a window around a trigger |
| [Querying archived data](doc/cookbook/query.md) | Query API V2 — buckets vs. samples, `QuerySpec`, paging, and migrating a V1 client |
| [PV metadata](doc/cookbook/pv-metadata.md) | Cataloguing PVs, discovery by tag/attribute/name, alias resolution, driving queries from metadata |
| [Machine configuration](doc/cookbook/machine-configuration.md) | Creating a configuration, recording activations in real time, closing an open activation, listing activation history |
| [Sample status](doc/cookbook/sample-status.md) | Labeling samples with status codes (dense and sparse), querying statuses, re-labeling a range, filtering data queries by status |
| [Data sets, annotations, export](doc/cookbook/datasets-and-annotations.md) | Defining DataSets, annotating them, publishing Calculations, recording column-level provenance, exporting to HDF5/CSV/XLSX |
| [Generating and importing Python stubs](doc/cookbook/python-stubs.md) | How Python stubs are produced from these protos and published via dp-python-lib |

Recipes use Java, the language whose stubs this repo builds.  Python users should start with
[dp-python-lib](https://github.com/craigmcchesney/dp-python-lib), a client library wrapping this
API.


---
# Entity API Details

## Provider API

A data Provider is an infrastructure component that uses the Data Platform Ingestion Service API to upload data to the archive.  Before sending ingestion requests with data, the Provider must be registered with the Ingestion Service.  Query methods are provided to retrieve details about registered Providers and metadata about the data they have uploaded.

See the [Provider registration cookbook](doc/cookbook/provider-registration.md) for worked examples of registering on startup, finding providers, and reading a provider's archive statistics.

### Provider Registration Methods
<table>
<tr>
<td><pre>
rpc registerProvider (RegisterProviderRequest) returns (RegisterProviderResponse);
</pre></td>
</tr>
<tr>
<td>defined in: ingestion.proto</td>
</tr>
<tr>
<td>
Data providers must be registered with the Ingestion Service before they can send data to the archive via the ingestion API methods.  This is accomplished via the provider registration API method.

This unary method sends a single RegisterProviderRequest and receives a single RegisterProviderResponse.  It is required to call this method to register a data provider before calling one of the data ingestion methods using the id of that provider.

----

Provider name is required in the RegisterProviderRequest, which may also contain optional descriptive fields including description, tags, and key / value attributes.

----

The response message indicates whether the registration was successful.  The response payload is an ExceptionalResult if the request is unsuccessful, otherwise it is a RegistrationResult that includes details about the new provider including providerId (for use in calls to data ingestion methods) and a flag indicating if the provider is new.  On success, if a document already exists in the MongoDB "providers" collection for the provider name specified in the RegisterProviderRequest, the method returns the corresponding provider id in the response, otherwise a new document is created in the "providers" collection and its id returned in the response.

----

It is safe (and recommended) to call this method each time a data ingestion client is run.  If a document already exists in the MongoDB providers collection for the specified provider, the attributes are updated to the values in the RegisterProviderRequest.
</td>
</tr>
</table>


### Provider Query Methods
<table>
<tr>
<td><pre>
rpc queryProviders(QueryProvidersRequest) returns (QueryProvidersResponse);
</pre></td>
</tr>
<tr>
<td>defined in: query.proto</td>
</tr>
<tr>
<td>
The queryProviders() API method is used by clients to retrieve details about ingestion data Providers defined in the archive.  It accepts a single QueryProvidersRequest containing the query parameters and returns a single QueryProvidersResponse.  The response may indicate an exceptional result such as rejection or error in handling the request, otherwise it contains information about each Provider matching the query criteria.

----

A QueryProvidersRequest contains a list of criteria for querying Providers.  Criterion options include 1) IdCriterion for query by unique id, 2) TextCriterion for full text query over Provider name and description, 3) TagsCriterion for query by tag value, and 4) AttributesCriterion for query by attribute key and value.  The list may contain a single criterion or list of multiple criteria.  For example, the query might use both a TagsCriterion and AttributesCriterion to query over tags and attributes, respectively.

----

The response message payload is either an ExceptionalResult indicating rejection or an error handling the request, or a ProvidersResult with a ProviderEntry for each Provider matching the query criteria.
</td>
</tr>
</table>

### Provider Stats Query Methods
<table>
<tr>
<td><pre>
rpc queryProviderStats(QueryProviderStatsRequest) returns (QueryProviderStatsResponse);
</pre></td>
</tr>
<tr>
<td>defined in: query.proto</td>
</tr>
<tr>
<td>
The queryProviderStats() API method is used by clients to retrieve archive ingestion statistics for data Providers defined in the archive.  It accepts a single QueryProviderStatsRequest message containing the query parameters, and returns a single QueryProviderStatsResponse.

----

The request message includes the unique id of a data Provider.

----

The response message payload is either an ExceptionalResult indicating rejection or an error handling the request, or a StatsResult with a ProviderStats entry for the Provider matching the id specified in the request.
</td>
</tr>
</table>



## PV Time-Series Data API

This section describes various concepts helpful for understanding the handling of PV Time-Series data in the Data Platform API, followed by an overview of the API methods for PV data ingestion, query, subscription, and PV metadata query.

For worked examples, see the [ingestion](doc/cookbook/ingestion.md), [query](doc/cookbook/query.md), and [subscriptions](doc/cookbook/subscriptions.md) cookbook recipes.

#### process variables

The core element of the Data Platform is the "process variable" (PV).  In control theory, a process variable is the current measured value of a particular part of a process that is being monitored or controlled.  The primary purpose of the Data Platform Ingestion and Query Services is to store and retrieve PV measurements.

It is assumed that each PV for a particular facility is uniquely named.  E.g., "S01:GCC01" might identify the first vacuum cold cathode gauge in sector one in the storage ring for some accelerator facility.

#### data vectors and handling heterogeneous data

The Ingestion and Query Service APIs for handling data work with vectors of PV samples.  In ___common.proto___, there are a number of column messages optimized for handling a range of heterogeneous data types.

Messages for vectors of individual scalar values include DoubleColumn, FloatColumn, Int64Column, Int32Column, BoolColumn, with corresponding messages for handling samples that are arrays of scalar values DoubleArrayColumn, FloatArrayColumn, Int64ArrayColumn, Int32ArrayColumn, and BoolArrayColumn.  Messages are provided for other data types including StringColumn, EnumColumn, ImageColumn, and StructColumn.  The SerializedDataColumn message is used to contain arbitrary binary data with user-defined encoding.  Each column message includes an optional ColumnMetadata field for per-column provenance, tags, and attributes (see below).

The original implementation includes the message DataColumn which contains a list of DataValue messages, where each DataValue specifies a heterogeneous data type for the sample value.  This feature is deprecated in the Ingestion Service API because 1) it causes per-sample JVM memory allocation in handling ingestion requests and 2) all sample values (including scalars) are stored as opaque binary blobs in the archive.

#### column metadata and provenance

Each column message includes an optional ColumnMetadata field for attaching per-column metadata to an ingestion request.  ColumnMetadata contains a ColumnProvenance message, a list of string tags, and a list of key/value Attribute pairs.

ColumnProvenance records provenance at two levels of detail.  The first is free-form description, in two unconstrained, facility-specific string fields: "source", which identifies the origin of the data (e.g., an NTTable/column identifier), and "process", which describes any processing applied to the source data (e.g., normalization).

The second is structured links.  The "derivedFrom" field is a list of ColumnSource messages naming the specific columns this column was computed from, in a form a client can traverse.  Each ColumnSource identifies either an archived PV (by name) or a column of a Calculations object (by calculationsId, frame name, and column name), and may carry an optional TimeRange giving the source interval consumed — which matters for aggregations, whose input interval is not implied by the derived column's own timestamps.  The list is repeated because a derived column may have several inputs, such as a difference of two PVs.

The MLDP does not constrain, enforce, or otherwise interpret any of these values.  derivedFrom links in particular are stored as supplied and are never validated for existence; a link that resolves to nothing means the referenced record was deleted, and readers must tolerate it.

Because ColumnProvenance rides inside the ColumnMetadata carried by every column message type, one mechanism serves both ingestion-side derived data and the columns of Annotation Calculations.  This is the finer of the two provenance levels in the API; the coarser, document level lives on an Annotation, whose dataSetIds and annotationIds record which archived data and which other annotations a body of work drew on.  As a rule of thumb for where derived data belongs: one-time analysis products belong in Annotation Calculations, atomic with their descriptive context and outside the PV namespace, while continuously-computed derived streams belong in ingestion as ordinary PVs.  Both use the same derivedFrom links.

There is no cost to leaving provenance unused — an absent ColumnMetadata or ColumnProvenance and an empty derivedFrom list all encode to zero bytes.

Column metadata is truly dynamic — it travels with each ingestion request and is stored at the bucket level.  For more static PV information, use the PV metadata query API.  Overuse of bucket-level metadata will burden the ingestion server process, which is optimized for continually ingesting PV time-series data.

#### timestamps

Time is represented in the Data Platform API using the Timestamp message defined in ___common.proto___.  It contains two components, one for the number of seconds since the epoch, and the other for nanoseconds.  As a convenience, the message "TimestampList" is used to send a list of timestamps.

#### data frame

The message DataFrame, defined in common.proto___, is the primary unit of ingestion in the Data Platform API.  It contains the set of data to be ingested using lists of the heterogeneous column messages listed above.  It uses the message DataTimestamps, defined in ___common.proto___, to specify the timestamps for the data values in those vectors.

DataTimestamps provides two mechanisms for specifying the timestamps for the data values.

A TimestampList (described above) may be used to send an explicit list of Timestamp objects.  It is assumed that each PV data vector column message is the same size as the list of timestamps, so that there is a data value specified for each corresponding time value.

A second alternative is to use the SamplingClock message, defined in ___common.proto___.  It uses three fields to specify the data timestamps, with a start time Timestamp, the sample period in nanoseconds, and an integer count of the number of samples.  The size of each data vector (column message) in the DataFrame is expected to match the sample count.

#### bucketed time-series data

We use the ["bucket pattern"](https://www.mongodb.com/blog/post/building-with-patterns-the-bucket-pattern) as an optimization for handling batched time-series data in the MLDP Ingestion and Query Service APIs, as well as for storing vectors of PV samples in MongoDB.  A "bucket" is a record that contains all the sample values for a single PV for a specified time range.

This allows a data vector to be stored in the database and returned in query results as a single unit, as opposed to storing and returning data values individually thus requiring that each record contain both a timestamp and data value (which effectively triples the record size for scalar data).  This leads to a more compact database, smaller gRPC messages to send query results, and improved overall performance.

A simple example of the bucket pattern follows (a slightly modified version of an example taken from the link above), demonstrating bucketing of temperature sensor data.  The first snippet shows three measurements, with one record per measurement:

```
{
   sensor_id: 12345,
   timestamp: ISODate("2019-01-31T10:00:00.000Z"),
   temperature: 40
}

{
   sensor_id: 12345,
   timestamp: ISODate("2019-01-31T10:01:00.000Z"),
   temperature: 40
}

{
   sensor_id: 12345,
   timestamp: ISODate("2019-01-31T10:02:00.000Z"),
   temperature: 41
}
```

With bucketing, we save the overhead of the sensor_id and timestamp in each record:
```
{
    sensor_id: 12345,
    start_date: ISODate("2019-01-31T10:00:00.000Z"),
    sample_period_nanos: 1_000_000_000,
    count: 3
    measurements: [ 40, 40, 41 ]
}
```
Bucketing is used in the API for ingesting time-series data.  The message "IngestDataRequest" contains an "DataFrame" that contains the data for the request as well as a "DataTimestamps" object that describes the timestamps for the frame's data values, either using a "SamplingClock" that specifies the start time and sample period for the values, or with an explicit list of timestamps.  It also includes lists of heterogeneous column messages, each of which is a bucket of data values (e.g., vector) for a particular PV, with a value for each of the frame's timestamps.

Bucketing is also used to send the results of time-series data queries.  The message "QueryDataResponse" in "query.proto" contains the query result in "QueryData", which contains a list of "DataBucket" messages.  Each "DataBucket" contains a vector of data using one of the column message data types for a single PV, along with time expressed using "DataTimestamps" (described above), with either an explicit list of timestamps for the bucket data values, or a SamplingClock with start time and sample period.


### PV Data Ingestion Methods
<table>
<tr>
<td><pre>
rpc ingestData (IngestDataRequest) returns (IngestDataResponse);
rpc ingestDataStream (stream IngestDataRequest) returns (IngestDataStreamResponse);
rpc ingestDataBidiStream (stream IngestDataRequest) returns (stream IngestDataResponse);
</pre></td>
</tr>
<tr>
<td>defined in: ingestion.proto</td>
</tr>
<tr>
<td>
The API provides three methods for data ingestion, including a simple unary single request / response method, a client-side streaming method, and a bi-directional streaming method.  Choice of which method to use depends on the needs of the client.  A simple low-volume client can use the unary method.  We expect the client-side streaming method to perform best, since the clients sends many requests in a stream and only receives a single response.  The bi-directional streaming method is also intended for a high-volume environment, but provides an acknowledgment for each request in the stream in situations where that might be important.

----

All data ingestion methods share the same request message, IngestDataRequest.  An IngestDataRequest contains the data to be ingested to the archive along with some required identifying information and optional descriptive fields.  The unit of ingestion is the DataFrame.  Analogous to a worksheet in an Excel workbook, DataFrame contains 1) a DataTimestamps object specifying the timestamp rows for the worksheet and 2) lists of heterogeneous column messages each of which is a column vector of data values, one for each timestamp row in the worksheet.  Each column message in the DataFrame may optionally include a ColumnMetadata field containing provenance information, tags, and key/value attributes that are stored at the bucket level in the archive.

----

The response message for the unary and bidirectional streaming methods, IngestDataResponse, contains one of two payloads, either an ExceptionalResult indicating an error handling the request or an AckResult indicating the request was accepted and echoing back the dimensions of the request in confirmation.  The response also includes provider id and client request id for matching the response to the corresponding request and a Timestamp indicating the time the message was sent.

The IngestDataStreamResponse message is returned by the client-side streaming ingestDataStream() method and contains an acknowledgment of the number of requests received in the request stream.

----

The Ingestion Service is fully asynchronous, so the response does not indicate if a request is successfully handled, only whether the request is accepted or rejected.  The queryRequestStatus() API method is used to query request status information.
</td>
</tr>
</table>

### PV Data Query Methods
<table>
<tr>
<td><pre>
rpc queryData(QueryDataRequest) returns (QueryDataResponse);
rpc queryDataStream(QueryDataRequest) returns (stream QueryDataResponse);
rpc queryDataBidiStream(stream QueryDataRequest) returns (stream QueryDataResponse);
rpc queryTable(QueryTableRequest) returns (QueryTableResponse);
</pre></td>
</tr>
<tr>
<td>defined in: query.proto</td>
</tr>
<tr>
<td>
The API offers four methods for querying PV time-series data.  The first three differ in the type of streaming employed by the method, including unary single request / response (queryData), server-side streaming (queryDataStream), and bidirectional streaming (queryDataBidiStream).  We expect the server-side streaming method to offer the best performance, and the bidirectional streaming method offers a cursor-like control for fetching the next result for applications that require it.

The fourth query method, queryTable(), is a unary single request / response method that returns a tabular data structure, oriented toward the Data Platform's Web Application and similar use cases.

----

All time-series data query methods accept a QueryDataRequest message.  The message contains one of two payloads, either a QuerySpec or a CursorOperation.

A "QuerySpec" message payload specifies the parameters for a time-series data query and includes begin and end timestamps specifying the time range for the query, and a list of PV names whose data to retrieve for the specified time range.

A CursorOperation payload is a special case and applies only to the queryDataBidiStream() method.  It contains an enum value from CursorOperationType specifying the type of cursor operation to be executed.  Currently, the enum contains a single option CURSOR_OP_NEXT which requests the next message in the response stream.  We may add additional operations, e.g, "fetch the next N buckets".

For queryDataBidiStream(), the client sends a single QueryDataRequest message, receiving a single QueryDataResponse with bucketed time-series data.  The client then requests the next response in the stream by sending a QueryDataRequest containing a CursorOperation method with type set to CURSOR_OP_NEXT until the result is exhausted and the stream is closed by the service.

----

Except for queryDataTable(), all time-series data query methods return QueryDataResponse messages.  A QueryDataResponse contains one of two message payloads, ExceptionalResult if an error is encountered or no data is found (described above) or QueryData with the query results.

A QueryData message includes a list of DataBucket messages.  Each DataBucket contains a vector of data using one of the heterogeneous column messages for a single PV, along with time expressed using a "DataTimestamps" message (described above), with either an explicit list of timestamps for the bucket data values or a SamplingClock with start time and sample period.  If ColumnMetadata (including provenance, tags, and/or key-value attributes) was supplied for the column at ingestion time, it is returned in the embedded column message within the DataBucket.

----

The queryDataTable() time-series data query method returns its result via a QueryTableResponse message.  This is essentially a packaging of the bucketed time-series data managed by the archive into a tabular data structure for use in a client such as a web application.  A QueryTableResponse object contains one of two payloads, an ExceptionalResult if an error is encountered or no data is found (described above) or a TableResult.

A TableResult message contains a list of PV column data vectors, one for each PV specified in the QueryDataRequest.  It also contains a DataTimestamps message with a TimestampList of timestamps, one for each data row in the table.  The column data vectors are the same size as the list of timestamps, and are padded with empty values where a column doesn't contain a value at the specified timestamp.

----

The response message for the unary methods cannot exceed the maximum gRPC message size limit, or an error is returned by the methods.
</td>
</tr>
</table>

### PV Data Query V2 Methods
<table>
<tr>
<td><pre>
rpc queryBuckets(QueryBucketsRequest) returns (QueryBucketsResponse);
rpc queryBucketsStream(QueryBucketsRequest) returns (stream QueryBucketsResponse);
rpc querySamples(QuerySamplesRequest) returns (QuerySamplesResponse);
rpc querySamplesStream(QuerySamplesRequest) returns (stream QuerySamplesResponse);
</pre></td>
</tr>
<tr>
<td>defined in: query.proto</td>
</tr>
<tr>
<td>
Query API V2 provides a second generation of the time-series data query API.  Its central abstraction is a common QuerySpec, shared by all four methods, that describes <em>what</em> data to retrieve independently of <em>how</em> results are represented.  The original V1 query methods (above) remain available for backward compatibility.

Each request bundles three messages: a QuerySpec (the logical query), an optional ExecutionOptions (paging), and an optional ResultRepresentation (result format flags).

A QuerySpec contains a TimeRange (half-open [beginTime, endTime)), a PvSelector, and optional ConfigurationSelector and SampleStatusSelector.  The PvSelector selects PVs by one of an explicit name list, a name regex pattern, or PV metadata criteria (mirroring the PV Metadata query language).  The ConfigurationSelector restricts returned data to intervals during which matching machine configurations were active, by intersecting the matching activations' intervals with the query TimeRange.

The SampleStatusSelector restricts returned samples by sample status (see the [Sample Status API](#sample-status-api)).  It names a required status domain, an optional set of layers (empty means all layers in the domain), an optional set of status codes (empty means any code), and a required mode: MODE_INCLUDE_MATCHING returns only samples having a matching status (unlabeled samples are excluded by definition — "return only anomalies"), while MODE_EXCLUDE_MATCHING drops samples having a matching status (unlabeled samples pass by definition — "drop bad/suspect data").  An empty statusCodes list matches statuses with any code, so "labeled at all by this (domain, layers)" is expressible without enumerating the domain's codes.  A sample is matched only by a status whose timestamp exactly equals the sample's timestamp.  When a ConfigurationSelector is also set, the two compose by intersection: the activation intervals first restrict the time axis, and status filtering then applies to the samples that survive.  The selector is supported by the sample-oriented methods only, where a filtered-out sample becomes a missing value in the ColumnTable; a bucket-oriented request with the selector set is rejected with an ExceptionalResult, since buckets are returned whole and cannot represent per-sample filtering.

ExecutionOptions carries a limit and an opaque pageToken, following the common MLDP paging model (an empty nextPageToken in the response indicates the last page).  ResultRepresentation carries flags controlling whether column metadata is excluded and whether serialized columns are used.

----

The two bucket-oriented methods return QueryBucketsResponse messages containing a BucketQueryResult with a list of DataBucket objects that closely match the archive storage model.  Boundary buckets are returned whole, so the first and last buckets may contain samples outside the requested time range.  These methods are intended for Java applications, archive export, and high-performance retrieval.

The two sample-oriented methods return QuerySamplesResponse messages containing a SampleQueryResult with a ColumnTable.  The service assembles buckets internally into a continuous, aligned, column-oriented table over a single union timestamp axis, trimming samples to the half-open time range; where a PV has no sample at a given timestamp the value is left unset (missing).  These methods are intended for Python, Pandas/NumPy/Polars, machine learning, and visualization use cases.

For both styles, the unary methods (queryBuckets, querySamples) provide resumable, bounded-memory paging via the pageToken.  The streaming methods (queryBucketsStream, querySamplesStream) are fire-and-consume: the server streams to completion using limit as the per-message chunk size, and does not emit continuation tokens.

----

As with the V1 methods, an ExceptionalResult is returned on rejection or error; an empty query result is returned as an empty result payload rather than an ExceptionalResult.
</td>
</tr>
</table>

### PV Data Subscription Methods
<table>
<tr>
<td><pre>
rpc subscribeData(stream SubscribeDataRequest) returns (stream SubscribeDataResponse);
</pre></td>
</tr>
<tr>
<td>defined in: ingestion.proto</td>
</tr>
<tr>
<td>

The subscribeData() API method allows the caller to register a subscription for PV time-series data received in the ingestion stream.  As the Ingestion Service receives new data for subscribed PVs, it publishes that data to subscribers while also persisting it to the archive.

This method allows the client to register a subscription for a list of PVs, and receive new data for those PVs received by the Ingestion Service after the subscription is created.  The method uses bidirectional streaming.  The client sends SubscribeDataRequest messages in the method's request stream, and receives SubscribeDataResponse messages in the response stream.

----

To initiate a new subscription, the client sends a single SubscribeDataRequest message (containing a NewSubscription message payload) to register the new subscription.

The service responds with a single SubscribeDataResponse message, containing either an ExceptionalResult message payload if the request is rejected by the service or an AckResult message if the service accepts the request and registers the subscription.

The service then sends a stream of SubscribeDataResponse messages, each containing a SubscribeDataResult with published data for the registered PVs, until the client cancels the subscription, either by sending a SubscribeDataRequest containing a CancelSubscription payload or by closing the API method's request stream.

The service sends a response with an ExceptionalResult payload if it rejects the subscription request or an error occurs while handling the subscription.  In either case, after sending the ExceptionalResult message the service closes the API method response stream.

If the client sends subsequent NewSubscription messages after registering the initial subscription, the service responds with a reject message and closes the response stream.

----

The client sends SubscribeDataRequest messages in the request stream for the subscribeData() API method.  Each message can contain one of two message payloads, either a NewSubscription message or a CancelSubscription message.

The NewSubscription message contains a list of PVs to be included in the data subscription.

The CancelSubscription message is an empty message that simply indicates the client wishes to end the subscription.

----

The service sends SubscribeDataResponse messages in the response stream for the subscribeData() method.  Each response contains one of three payload messages.  1) An ExceptionalResult payload is sent if the service rejects the subscription request or an error occurs while processing the subscription. 2) An AckResult payload is sent when the service accepts a subscription request.  3) A SubscribeDataResult is sent when the service publishes new data for any of the PVs registered for the subscription.

Each SubscribeDataResult message contains a list of DataBucket messages, each containing a DataTimestamps message and a heterogeneous column message with a vector containing a sample value for each timestamp for one of the PVs registered for the subscription.

----

</td>
</tr>
</table>

### PV Data Event Subscription Methods
<table>
<tr>
<td><pre>
rpc subscribeDataEvent(stream SubscribeDataEventRequest) returns (stream SubscribeDataEventResponse);
</pre></td>
</tr>
<tr>
<td>defined in: <a href="https://github.com/osprey-dcs/dp-grpc/blob/main/src/main/proto/ingestion_stream.proto">ingestion_stream.proto</a></td>
</tr>
<tr>
<td>

Using the subscribeDataEvent() API method, a client registers one or more triggers each specifying a PV name, a condition (e.g., equal to, greater than, less than, etc.), and a trigger data value.  When the condition is triggered by data in the ingestion stream for the specified PV, the client receives an Event notification that specifies the event time, condition that was triggered, and the data value that triggered the event.  The client can optionally register to receive EventData for a list of PVs when an Event is triggered for a window of time offset from the event trigger time.  This is useful for monitoring data conditions in "real-time", and building models and applications that respond to conditions in the data ingestion stream.

This method uses the Ingestion Service data subscription mechanism.  As the Ingestion Service receives new data for subscribed PVs, it publishes that data to subscribers while also persisting it to the archive.

The method uses bidirectional streaming.  The client sends SubscribeDataEventRequest messages in the method's request stream, and receives SubscribeDataEventResponse messages in the response stream.

----

To initiate a new subscription, the client sends a single SubscribeDataEventRequest message (containing a NewSubscription message payload) to register the new subscription.

The service responds with a single SubscribeDataEventResponse message, containing either an ExceptionalResult message payload if the request is rejected by the service or an AckResult message if the service accepts the request and registers the subscription.

The service then sends a stream of SubscribeDataEventResponse messages containing either Event or EventData payloads, until the client cancels the subscription, either by sending a SubscribeDataEventRequest containing a CancelSubscription payload or by closing the API method's request stream.

The service sends a response with an ExceptionalResult payload if it rejects the subscription request or an error occurs while handling the subscription.  In either case, after sending the ExceptionalResult message the service closes the API method response stream.

If the client sends subsequent NewSubscription messages after registering the initial subscription, the service responds with a reject message and closes the response stream.

----

The client sends SubscribeDataEventRequest messages in the request stream for the subscribeDataEvent() API method.  Each message can contain one of two message payloads, either a NewSubscription message or a CancelSubscription message.

The NewSubscription message contains a list of PVConditionTrigger messages (triggers) and a DataEventOperation (operation) message.

Each PvConditionTrigger specifies a PV name, a condition (e.g., equal to, greater than, less than, etc.), and a trigger data value.  When the condition is triggered by data in the ingestion stream for the specified PV, the client receives an Event notification that specifies the event time, condition that was triggered, and the data value that triggered the event.  

The DataEventOperation parameter is used to optionally register to receive EventData for a list of PVs when an Event is triggered for a window of time offset from the event trigger time.  This message includes a list of target PVs (targetPVs) and a DataEventWindow message that specifies the window of time (as a time interval offset from the triggered event time).  When an event is triggered for one of the subscription's PvConditionTriggers, EventData messages are sent in the response stream containing DataBuckets for the list of PVs and time interval specified in the DataEventOperation.

The CancelSubscription message is an empty message that simply indicates the client wishes to end the subscription.

----

The service sends SubscribeDataEventResponse messages in the response stream for the subscribeDataEvent() method.  Each response contains one of four payload messages.  1) An ExceptionalResult payload is sent if the service rejects the subscription request or an error occurs while processing the subscription. 2) An AckResult payload is sent when the service accepts a subscription request. 3) A Event payload is sent each time the condition is met for one of the subscription's PvConditionTriggers. 4) When an Event is triggered for a subscription, messages with EventData payloads are sent for the specified list of PV names and time interval in the subscription's DataEventOperation parameter.

----

</td>
</tr>
</table>

### PV Stats Query Methods
<table>
<tr>
<td><pre>
rpc queryPvStats(QueryPvStatsRequest) returns (QueryPvStatsResponse);
</pre></td>
</tr>
<tr>
<td>defined in: query.proto</td>
</tr>
<tr>
<td>

The queryPvStats() method queries archive ingestion statistics for PVs available in the archive.  It is a unary single request/response method that accepts a QueryPvStatsRequest and returns a QueryPvStatsResponse.

For querying user-defined PV metadata (aliases, tags, attributes, description), see [PV Metadata API](#pv-metadata-api) in the Annotation Service.

----

The QueryPvStatsRequest message contains one of two payloads, PvNameList or PvNamePattern.  A PvNameList message specifies an explicit list of PVs to retrieve stats for.  A PvNamePattern specifies a regular expression pattern for matching against PV names available in the archive.

----

The QueryPvStatsResponse message contains one of two payloads, either an ExceptionalResult if an error is encountered or no data is found, or a StatsResult with the results of the query.

A StatsResult message contains a list of PvStats messages, one for each PV matching the query.  A PvStats message contains archive ingestion statistics for an individual PV, including name, timestamps for the first and last PV measurement in the archive, and stats for the most recent bucket including bucket id, data type information, data timestamps details, total number of data buckets, and sample count/period.

</td>
</tr>
</table>



## Ingestion Request Status API

Because the Ingestion Service handles PV time-series data ingestion requests asynchronously, a separate API is provided to check the disposition of individual requests or identify handling errors for a specified time period.

See [Sweeping for ingestion failures](doc/cookbook/ingestion.md#sweeping-for-ingestion-failures) in the ingestion cookbook for why a production pipeline must check request status, and how.

### Request Status Query Methods
<table>
<tr>
<td><pre>
rpc queryRequestStatus(QueryRequestStatusRequest) returns (QueryRequestStatusResponse);
</pre></td>
</tr>
<tr>
<td>defined in: ingestion.proto</td>
</tr>
<tr>
<td>

For performance reasons, data ingestion requests are handled asynchronously by the Ingestion Service.  Each IngestDataRequest sent via a data ingestion API method is either acknowledged or rejected immediately.  A request that is accepted by the service may subsequently encounter an error during processing.  For that reason, a RequestStatus record is created in the database for each ingestion request received by the service, indicating the disposition of that request (e.g., success, rejected, or error).  This method is used to query request status details for an individual ingestion request or to identify data ingestion errors for a specified time range.

This unary method sends a single QueryRequestStatusRequest and receives a single QueryRequestStatusResponse.

----

The QueryRequestStatusRequest message contains a list of criteria for searching by provider id, provider name, request id, status, and time range. The criteria can be combined arbitrarily, but we envision three primary use cases:

1) Query by provider id or name and request id to find the status of a specific ingestion request.
2) Query by provider id or name, status (e.g., rejected or error) and time range.
3) Query by status and time range without specifying a provider (e.g., "find all ingestion errors for today").

----

The QueryRequestStatusResponse message payload is either an ExceptionalResult containing details about a rejection or error, or a RequestStatusResult containing a list of RequestStatus messages, one for each document in the MongoDB "requestStatus" collection that matches the search criteria.

Each RequestStatus message contains details about the status of an individual ingestion request, including provider id/name, request id, status enum, status message, and list of bucket ids created (documents added to the MongoDB "buckets" collection).

</td>
</tr>
</table>



## PV Metadata API

The PV Metadata API, part of the Annotation Service, provides methods for associating user-defined metadata with PVs and using that metadata to discover PVs of interest.  A PV metadata record stores the canonical PV name as its primary key, along with optional aliases (historical or alternate names), keyword tags, key-value attributes, and a free-text description.  Records also include audit timestamps (`createdTime`, `updatedTime`) and an optional `modifiedBy` field identifying the last writer.

See the [PV metadata cookbook](doc/cookbook/pv-metadata.md) for worked examples of cataloguing PVs, discovery by tag and attribute, alias resolution, and driving data queries from metadata.

No pre-registration of PVs is required — metadata records can be created independently of whether data has been ingested for a PV.

For querying archive ingestion statistics (first/last data timestamp, bucket counts, data types), see [PV Stats Query Methods](#pv-stats-query-methods) in the Query Service.

### PV Metadata Save Methods
<table>
<tr>
<td><pre>
rpc savePvMetadata(SavePvMetadataRequest) returns (SavePvMetadataResponse);
</pre></td>
</tr>
<tr>
<td>defined in: annotation.proto</td>
</tr>
<tr>
<td>

The savePvMetadata() method creates or replaces the metadata record for a PV.  It uses full-replace upsert semantics: if no record exists for the PV name, a new record is created; if a record already exists, all fields are replaced with the contents of the request.

**Warning:** Fields omitted from the request are not preserved on update — callers must supply the complete desired state on every save.  Use patchPvMetadata() (future) for partial updates.

----

A SavePvMetadataRequest includes the required canonical PV name and optional fields: aliases, tags, attributes, modifiedBy, and description.  Data normalization rules applied by the service: tags and aliases are normalized to a lowercase unique set; attribute keys must be unique within the request.

----

The response payload is an ExceptionalResult if the request is rejected or an error is encountered, otherwise a SavePvMetadataResult containing the canonical PV name of the created or updated record.

</td>
</tr>
</table>

### PV Metadata Query Methods
<table>
<tr>
<td><pre>
rpc queryPvMetadata(QueryPvMetadataRequest) returns (QueryPvMetadataResponse);
</pre></td>
</tr>
<tr>
<td>defined in: annotation.proto</td>
</tr>
<tr>
<td>

The queryPvMetadata() method searches PV metadata records using structured criteria and returns a paginated result.

----

A QueryPvMetadataRequest contains a list of QueryPvMetadataCriterion entries and optional pagination parameters (limit, pageToken).  Multiple criteria are combined with logical AND; values within a single criterion are combined with logical OR.  Criterion types include:

- **PvNameCriterion** — match by canonical PV name using exact, prefix, and/or contains sub-lists (all ORed together).
- **AliasesCriterion** — match by alias using the same exact/prefix/contains sub-lists.
- **TagsCriterion** — match records that have any of the specified tags.
- **AttributesCriterion** — match by attribute key and optional value(s); an empty values list matches any record that has the key regardless of value (key-only / existence search).

----

The response payload is an ExceptionalResult if the request is rejected or an error is encountered, otherwise a PvMetadataResult containing a list of PvMetadata records and a nextPageToken for retrieving subsequent pages.  An empty nextPageToken indicates the last page.  An empty result set is returned as a PvMetadataResult with an empty list, not an ExceptionalResult.

</td>
</tr>
</table>

### PV Metadata Get Methods
<table>
<tr>
<td><pre>
rpc getPvMetadata(GetPvMetadataRequest) returns (GetPvMetadataResponse);
</pre></td>
</tr>
<tr>
<td>defined in: annotation.proto</td>
</tr>
<tr>
<td>

The getPvMetadata() method retrieves a single PV metadata record by canonical PV name or alias.  It is a convenience method for the common single-record lookup case, as an alternative to using queryPvMetadata() with a single exact PvNameCriterion.

----

A GetPvMetadataRequest contains the PV name or alias to look up.  The service first searches by canonical PV name; if no match is found it searches aliases.

----

The response payload is an ExceptionalResult if the request is rejected, an error is encountered, or no matching record is found, otherwise the matching PvMetadata record.

</td>
</tr>
</table>

### PV Metadata Delete Methods
<table>
<tr>
<td><pre>
rpc deletePvMetadata(DeletePvMetadataRequest) returns (DeletePvMetadataResponse);
</pre></td>
</tr>
<tr>
<td>defined in: annotation.proto</td>
</tr>
<tr>
<td>

The deletePvMetadata() method deletes the metadata record for the specified canonical PV name.

----

A DeletePvMetadataRequest contains the canonical PV name of the record to delete.  Aliases are not accepted as delete keys.

----

The response payload is an ExceptionalResult if the request is rejected, an error is encountered, or no record exists for the specified PV name, otherwise a DeletePvMetadataResult containing the canonical PV name of the deleted record.

</td>
</tr>
</table>

### PV Metadata Placeholder Methods

Two additional PV metadata methods are defined in the proto but not yet implemented.  Calling either method returns an error response.  They are defined now to reserve their names and establish the standard CRUD pattern for metadata APIs in this service.

<table>
<tr>
<td><pre>
rpc patchPvMetadata(PatchPvMetadataRequest) returns (PatchPvMetadataResponse);
rpc bulkSavePvMetadata(BulkSavePvMetadataRequest) returns (BulkSavePvMetadataResponse);
</pre></td>
</tr>
<tr>
<td>defined in: annotation.proto</td>
</tr>
<tr>
<td>

**patchPvMetadata()** will provide partial-update semantics, allowing individual fields to be updated without replacing the entire record.  Field mask design is deferred to the release that implements this method.

**bulkSavePvMetadata()** will accept a list of SavePvMetadataRequest messages and apply the same full-replace upsert semantics as savePvMetadata() to each record in a single request.  Intended for large initial imports or bulk synchronization use cases.

</td>
</tr>
</table>


## Machine Configuration API

The Machine Configuration API, part of the Annotation Service, provides methods for defining and managing reusable machine configuration records that describe the operational state of the accelerator at a given point in time.  This metadata helps users interpret associated PV time-series data — for example, identifying which machine mode was active during a beam loss event, or comparing orbit data across different energy configurations.

A Configuration record stores `configurationName` as its canonical primary key (no pre-registration required), along with a required `category` (e.g., `beam_mode`, `energy`, `destination`), an optional `parentConfigurationName` for hierarchical organization, keyword tags, key-value attributes, a free-text description, and audit timestamps (`createdTime`, `updatedTime`).

For querying the time intervals during which configurations were active, see the [Configuration Activation API](#configuration-activation-api) below.  For worked examples, see the [Machine Configuration cookbook](doc/cookbook/machine-configuration.md).

### Configuration Save Methods
<table>
<tr>
<td><pre>
rpc saveConfiguration(SaveConfigurationRequest) returns (SaveConfigurationResponse);
</pre></td>
</tr>
<tr>
<td>defined in: annotation.proto</td>
</tr>
<tr>
<td>

The saveConfiguration() method creates or replaces the metadata record for a machine configuration.  It uses full-replace upsert semantics: if no record exists for the configuration name, a new record is created; if a record already exists, all fields are replaced with the contents of the request.

**Warning:** Fields omitted from the request are not preserved on update — callers must supply the complete desired state on every save.  Use patchConfiguration() (future) for partial updates.

----

A SaveConfigurationRequest includes the required `configurationName` and `category`, and optional fields: `description`, `parentConfigurationName`, `tags`, `attributes`, and `modifiedBy`.  Data normalization rules applied by the service: tags are normalized to a lowercase unique set; attribute keys must be unique within the request.  `createdTime` and `updatedTime` are server-set and are not accepted as input.

----

The response payload is an ExceptionalResult if the request is rejected or an error is encountered, otherwise a SaveConfigurationResult containing the canonical configuration name of the created or updated record.

</td>
</tr>
</table>

### Configuration Query Methods
<table>
<tr>
<td><pre>
rpc getConfiguration(GetConfigurationRequest) returns (GetConfigurationResponse);
rpc queryConfigurations(QueryConfigurationsRequest) returns (QueryConfigurationsResponse);
rpc deleteConfiguration(DeleteConfigurationRequest) returns (DeleteConfigurationResponse);
</pre></td>
</tr>
<tr>
<td>defined in: annotation.proto</td>
</tr>
<tr>
<td>

**getConfiguration()** retrieves a single Configuration record by `configurationName`.  It is a convenience method for the common single-record lookup case.  The response payload is an ExceptionalResult if no record is found or an error is encountered, otherwise the matching Configuration record.

----

**queryConfigurations()** searches Configuration records using structured criteria and returns a paginated result.

A QueryConfigurationsRequest contains a list of QueryConfigurationsCriterion entries and optional pagination parameters (`limit`, `pageToken`).  Multiple criteria are combined with logical AND; values within a single criterion are combined with logical OR.  Criterion types include:

- **NameCriterion** — match by configuration name using exact, prefix, and/or contains sub-lists (all ORed together).
- **CategoryCriterion** — match records whose category equals any of the specified values.
- **TagsCriterion** — match records that have any of the specified tags.
- **AttributesCriterion** — match by attribute key and optional value(s); an empty values list matches any record that has the key regardless of value (key-only / existence search).
- **ParentCriterion** — match records whose `parentConfigurationName` equals any of the specified values (direct children only; recursive traversal not yet supported).

The response payload is an ExceptionalResult if the request is rejected or an error is encountered, otherwise a QueryConfigurationsResult containing a list of Configuration records and a `nextPageToken` for retrieving subsequent pages.  An empty result set is returned as a QueryConfigurationsResult with an empty list, not an ExceptionalResult.

----

**deleteConfiguration()** deletes the Configuration record for the specified `configurationName`.  The request is rejected if ConfigurationActivation records exist for the configuration; delete associated activations first.  The response payload is an ExceptionalResult if rejected or an error is encountered, otherwise a DeleteConfigurationResult confirming the name of the deleted record.

</td>
</tr>
</table>

### Configuration Placeholder Methods

Two additional Configuration methods are defined in the proto but not yet implemented.  Calling either method returns an error response.  They are defined now to reserve their names and establish the standard CRUD pattern for metadata APIs in this service.

<table>
<tr>
<td><pre>
rpc patchConfiguration(PatchConfigurationRequest) returns (PatchConfigurationResponse);
rpc bulkSaveConfiguration(BulkSaveConfigurationRequest) returns (BulkSaveConfigurationResponse);
</pre></td>
</tr>
<tr>
<td>defined in: annotation.proto</td>
</tr>
<tr>
<td>

**patchConfiguration()** will provide partial-update semantics, allowing individual fields to be updated without replacing the entire record.  Field mask design is deferred to the release that implements this method.

**bulkSaveConfiguration()** will accept a list of SaveConfigurationRequest messages and apply the same full-replace upsert semantics as saveConfiguration() to each record in a single request.  Intended for large initial imports or bulk synchronization use cases.

</td>
</tr>
</table>


## Configuration Activation API

The Configuration Activation API, part of the Annotation Service, provides methods for recording and querying the time intervals during which machine configurations were active.  A ConfigurationActivation record links a Configuration to a `startTime` and optional `endTime` (absent means the interval is open-ended).

The primary use case is bulk-loading activation history from operational calendars, but live recording is also supported.  Multiple configurations may be active simultaneously as long as they belong to different categories — the server enforces that no two activations for the same configuration name, or within the same category, overlap.

An optional `clientActivationId` field allows callers to supply a stable external identifier for an activation record (e.g., a calendar event ID).  If omitted, the server generates an opaque identifier.  Clients loading activations from external systems should always supply `clientActivationId` to enable future updates without a prior lookup.

See the [Machine Configuration cookbook](doc/cookbook/machine-configuration.md) for worked examples of recording configuration changes in real time, closing an open-ended activation, and listing activation history for a configuration.

### Configuration Activation Save Methods
<table>
<tr>
<td><pre>
rpc saveConfigurationActivation(SaveConfigurationActivationRequest) returns (SaveConfigurationActivationResponse);
</pre></td>
</tr>
<tr>
<td>defined in: annotation.proto</td>
</tr>
<tr>
<td>

The saveConfigurationActivation() method creates or replaces an activation record.  It uses full-replace upsert semantics: the record is matched for update by `clientActivationId` if provided, otherwise by composite key (`configurationName` + `startTime`).

**Warning:** Fields omitted from the request are not preserved on update — callers must supply the complete desired state on every save.  Use patchConfigurationActivation() (future) for partial updates.

To close an open-ended activation, call saveConfigurationActivation() with `endTime` set to the desired close time.

----

A SaveConfigurationActivationRequest includes the required `configurationName` and `startTime`, optional `clientActivationId`, `endTime`, `description`, `tags`, `attributes`, and `modifiedBy`.  `createdTime` and `updatedTime` are server-set and are not accepted as input.

Validation rules: `configurationName` must reference an existing Configuration record; if `endTime` is present it must be >= `startTime`; overlapping activations for the same `configurationName` or within the same category are rejected.

----

The response payload is an ExceptionalResult if the request is rejected or an error is encountered, otherwise a SaveConfigurationActivationResult containing the `clientActivationId` of the created or updated record (client-supplied or server-generated).

</td>
</tr>
</table>

### Configuration Activation Query Methods
<table>
<tr>
<td><pre>
rpc getConfigurationActivation(GetConfigurationActivationRequest) returns (GetConfigurationActivationResponse);
rpc queryConfigurationActivations(QueryConfigurationActivationsRequest) returns (QueryConfigurationActivationsResponse);
rpc deleteConfigurationActivation(DeleteConfigurationActivationRequest) returns (DeleteConfigurationActivationResponse);
rpc getActiveConfigurations(GetActiveConfigurationsRequest) returns (GetActiveConfigurationsResponse);
</pre></td>
</tr>
<tr>
<td>defined in: annotation.proto</td>
</tr>
<tr>
<td>

**getConfigurationActivation()** retrieves a single ConfigurationActivation record by `clientActivationId` or composite key (`configurationName` + `startTime`).  Exactly one key must be set.  The response payload is an ExceptionalResult if no record is found or an error is encountered, otherwise the matching ConfigurationActivation record.

----

**queryConfigurationActivations()** searches ConfigurationActivation records using structured criteria and returns a paginated result.

A QueryConfigurationActivationsRequest contains a list of QueryConfigurationActivationsCriterion entries and optional pagination parameters (`limit`, `pageToken`).  Multiple criteria are combined with logical AND; values within a single criterion are combined with logical OR.  Criterion types include:

- **TimestampCriterion** — match activations in effect at a specific point in time (`startTime <= timestamp` AND (`endTime` is absent OR `endTime > timestamp`)).
- **TimeRangeCriterion** — match activations that overlap a specified window (activation is active at any point during `[startTime, endTime)`).
- **ConfigurationNameCriterion** — match by configuration name (exact match, OR semantics).
- **ClientActivationIdCriterion** — match by client-supplied activation ID (exact match, OR semantics).
- **CategoryCriterion** — match activations whose configuration belongs to any of the specified categories.
- **TagsCriterion** — match activations that have any of the specified tags.
- **AttributesCriterion** — match by attribute key and optional value(s); an empty values list matches any activation that has the key (key-only / existence search).

The response payload is an ExceptionalResult if the request is rejected or an error is encountered, otherwise a QueryConfigurationActivationsResult containing a list of ConfigurationActivation records and a `nextPageToken` for retrieving subsequent pages.  An empty result set is returned as a QueryConfigurationActivationsResult with an empty list, not an ExceptionalResult.

----

**deleteConfigurationActivation()** deletes an activation record by `clientActivationId` or composite key (`configurationName` + `startTime`).  The response payload is an ExceptionalResult if rejected or an error is encountered, otherwise a DeleteConfigurationActivationResult confirming the `clientActivationId` of the deleted record.

----

**getActiveConfigurations()** returns all ConfigurationActivation records in effect at the specified timestamp.  The `timestamp` field is required; a zero-value timestamp is rejected with an ExceptionalResult.  An empty result (no active configurations at the specified time) is returned as a GetActiveConfigurationsResult with an empty list, not an ExceptionalResult.

</td>
</tr>
</table>

### Configuration Activation Placeholder Methods

Two additional Configuration Activation methods are defined in the proto but not yet implemented.  Calling either method returns an error response.  They are defined now to reserve their names and establish the standard CRUD pattern for metadata APIs in this service.

<table>
<tr>
<td><pre>
rpc patchConfigurationActivation(PatchConfigurationActivationRequest) returns (PatchConfigurationActivationResponse);
rpc bulkSaveConfigurationActivation(BulkSaveConfigurationActivationRequest) returns (BulkSaveConfigurationActivationResponse);
</pre></td>
</tr>
<tr>
<td>defined in: annotation.proto</td>
</tr>
<tr>
<td>

**patchConfigurationActivation()** will provide partial-update semantics, allowing individual fields (e.g., `endTime`) to be updated without replacing the entire record.  Field mask design is deferred to the release that implements this method.

**bulkSaveConfigurationActivation()** will accept a list of SaveConfigurationActivationRequest messages and apply the same full-replace upsert semantics as saveConfigurationActivation() to each record in a single request.  Intended for bulk loading of activation records from operational calendars.

</td>
</tr>
</table>


## Sample Status API

The Sample Status API, part of the Annotation Service, provides methods for assigning status codes to individual PV samples at specific timestamps.  It supports data cleaning, quality assessment, and MLOps workflows — for example, an ML model labeling samples as anomalous, a rule engine flagging out-of-range values, or an operator marking a handful of suspect points.  It is also the designated replacement for the deprecated DataValue ValueStatus mechanism: acquisition-time alarm/status information (e.g., EPICS alarm severity and status) is captured as sample statuses rather than embedded per-sample metadata, and can be assigned or updated post-ingestion.

Statuses are interpreted within a **domain** — a named contract defining the semantics of the int32 status codes (e.g., `data_quality`, `ml_anomaly`).  Following the EnumColumn precedent, the (domain, code) mapping is a contract between status producers and consumers, and is not validated or interpreted by the MLDP.  A **layer** names the producer stream assigning the statuses (e.g., `ml_model_v1`, `rule_engine`, `operator_override`), allowing multiple independent interpretations of the same samples within the same domain.  The identity key of an individual sample status is (pvName, timestamp, domain, layer).  An optional free-form `source` field carries descriptive provenance; it applies to a whole save request and is recorded at storage-bucket granularity (last writer only), not per individual status.

Sparse labeling is fully supported: a save need only supply the timestamps of the samples being labeled, and the absence of a status for a sample means "no assertion" — there is no implicit default status.  Statuses are matched to data samples by exact (pvName, timestamp) equality at nanosecond precision, so producers should label using timestamps obtained from data query results (or exact SamplingClock arithmetic).

Sample statuses can be used to filter time-series query results via the QuerySpec `sampleStatusSelector` field; see [PV Data Query V2 Methods](#pv-data-query-v2-methods).  For worked examples, see the [Sample Status cookbook](doc/cookbook/sample-status.md).

### Sample Status Save Methods
<table>
<tr>
<td><pre>
rpc saveSampleStatuses(SaveSampleStatusesRequest) returns (SaveSampleStatusesResponse);
</pre></td>
</tr>
<tr>
<td>defined in: annotation.proto</td>
</tr>
<tr>
<td>

The saveSampleStatuses() method performs a batch upsert of sample statuses.  Upsert semantics are per individual sample status, keyed by (pvName, timestamp, domain, layer): an entry replaces any existing status with the same key **in full** — statusCode, confidence, and reasons alike, so callers must supply the complete desired state for each status (re-saving with an empty confidence or reasons list clears any previously stored values) — and creates a new status otherwise.  Statuses at other timestamps are unaffected — to cleanly re-label a time range (e.g., after re-running an ML model whose output timestamps changed), first call deleteSampleStatuses() for the range, then save.  Frames are processed in request order; if the same identity key appears in more than one frame, the later frame wins and `savedCount` counts each write.

----

A SaveSampleStatusesRequest contains a list of SampleStatusFrame messages plus optional request-wide `source` (free-form provenance describing the producer) and `modifiedBy` (actor / user / service identity), recorded at storage-bucket granularity (last writer only; per-sample audit history is not maintained).  Batch frames from a single producer per request: mixing producers in one request records the same `source`/`modifiedBy` for all of them, misattributing provenance.  Each frame carries a required `domain` and `layer`, a DataTimestamps time axis (a SamplingClock for dense labeling of a regularly-sampled range, or an explicit TimestampList for sparse labeling), and one SampleStatusColumn per PV.  Each column carries the PV name, one int32 status code per timestamp, and optional `confidence` (float) and `reasons` (string) parallel arrays, each of which must be empty or contain exactly one entry per timestamp.

Validation rules applied by the service: the request must contain at least one frame; each frame requires domain, layer, dataTimestamps, and at least one status column; a PV may appear in at most one column per frame; per-column array lengths must match the timestamp count; dataTimestamps must specify at least one timestamp (a SamplingClock requires periodNanos > 0 and count >= 1; a TimestampList must be non-empty with strictly increasing timestamps); batch size limits may be enforced by server configuration, and oversized requests are rejected.  The request is validated and rejected as a whole (no partial save on rejection).  The service does not validate that status timestamps correspond to archived data samples — alignment of statuses with samples is a producer contract.

----

The response payload is an ExceptionalResult if the request is rejected or an error is encountered (a mid-write error may leave some frames persisted), otherwise a SaveSampleStatusesResult containing `savedCount`, the total number of individual sample statuses upserted across all frames and columns.

</td>
</tr>
</table>

### Sample Status Query Methods
<table>
<tr>
<td><pre>
rpc querySampleStatuses(QuerySampleStatusesRequest) returns (QuerySampleStatusesResponse);
rpc querySampleStatusesStream(QuerySampleStatusesRequest) returns (stream QuerySampleStatusesResponse);
</pre></td>
</tr>
<tr>
<td>defined in: annotation.proto</td>
</tr>
<tr>
<td>

**querySampleStatuses()** queries sample statuses over a time range, optionally filtered by PV name, domain, and layer, returning one page of SampleStatusBucket objects.

A QuerySampleStatusesRequest contains a required TimeRange, optional `pvNames`, `domains`, and `layers` filters, and pagination parameters (`limit`, `pageToken`).  The filter fields are combined with logical AND; multiple values within a single field are combined with logical OR (exact match); an empty list matches all values.  An empty `pvNames` list matches all PVs with statuses in the range — the way to enumerate which PVs a (domain, layer) has labeled, e.g. before retiring the layer.

Bucket selection follows the TimeRange overlap test, and boundary buckets are returned whole (not trimmed) — matching queryBuckets() — so a returned bucket may contain individual statuses outside [beginTime, endTime).

The response payload is an ExceptionalResult if the request is rejected or an error is encountered, otherwise a QuerySampleStatusesResult containing a list of SampleStatusBucket objects and a `nextPageToken` for retrieving subsequent pages.  Buckets are ordered by (pvName, domain, layer, bucket start time), and every bucket is complete — paging boundaries always fall between buckets.  Each bucket carries its domain and layer, a DataTimestamps time axis, a SampleStatusColumn (PV name, status codes, and optional confidence/reasons), and last-writer provenance (`source`, `modifiedBy`, and server-set `updatedTime`).  An empty result set is returned as a QuerySampleStatusesResult with an empty list, not an ExceptionalResult.

----

**querySampleStatusesStream()** executes the same request as a server stream, following the queryBucketsStream() paging model: `limit` controls the chunk size of each streamed response; streaming is fire-and-consume — the server streams to completion and does not emit continuation tokens (`nextPageToken` is empty on every streamed message); `pageToken` must be empty (a non-empty token is rejected with an ExceptionalResult).  Use unary querySampleStatuses() when resumable paging is required.

</td>
</tr>
</table>

### Sample Status Delete Methods
<table>
<tr>
<td><pre>
rpc deleteSampleStatuses(DeleteSampleStatusesRequest) returns (DeleteSampleStatusesResponse);
</pre></td>
</tr>
<tr>
<td>defined in: annotation.proto</td>
</tr>
<tr>
<td>

The deleteSampleStatuses() method deletes sample statuses within the half-open time range [beginTime, endTime), for a single required (domain, layer).  `pvNames` restricts the delete to the listed PVs; an empty `pvNames` list is a deliberate wildcard deleting the (domain, layer)'s statuses for all PVs in the range.  It is intended for cleanly re-labeling a time range (delete, then save) and for retiring an obsolete producer's statuses.

Unlike query — which returns boundary buckets whole — deletion is exact at the sample axis: only statuses whose timestamps fall within the range are removed, and the server splits or rewrites boundary storage buckets as needed.

----

A DeleteSampleStatusesRequest contains a required `timeRange`, `domain`, and `layer`, plus an optional `pvNames` list (empty = all PVs).  Requiring the time range and a single (domain, layer) scopes every delete; to retire an entire layer, use a wide time range and an empty `pvNames` list (querySampleStatuses() with empty `pvNames` enumerates what a layer has labeled, if you want to inspect before deleting).

----

The response payload is an ExceptionalResult if the request is rejected or an error is encountered, otherwise a DeleteSampleStatusesResult containing `deletedCount`, the total number of individual sample statuses deleted.  A delete matching no statuses is a successful result with `deletedCount` = 0, not an ExceptionalResult.

</td>
</tr>
</table>

### Sample Status Placeholder Methods

Two sample status domain registry methods are defined in the proto but not yet implemented.  Calling either method returns an error response.  They are defined now to reserve their names and establish the standard CRUD pattern for metadata APIs in this service.

<table>
<tr>
<td><pre>
rpc saveSampleStatusDomain(SaveSampleStatusDomainRequest) returns (SaveSampleStatusDomainResponse);
rpc querySampleStatusDomains(QuerySampleStatusDomainsRequest) returns (QuerySampleStatusDomainsResponse);
</pre></td>
</tr>
<tr>
<td>defined in: annotation.proto</td>
</tr>
<tr>
<td>

**saveSampleStatusDomain()** will create or replace a sample status domain registry record, documenting the status code mappings (code → label / description) for a domain so that consumers can interpret status codes without out-of-band knowledge.  The registry record shape is deferred to the release that implements this method.

**querySampleStatusDomains()** will query sample status domain registry records.  Search criteria and pagination fields are deferred to the release that implements this method.

</td>
</tr>
</table>


## Data Set API

When designing the Data Platform's Annotation Service, we found we needed a mechanism for specifying a collection of data in the archive as the subject of an annotation.  We decided to add the notion of a Data Set consisting of a list of Data Blocks, where each Data Block specifies a list of PV names and a time range.

See the [Data sets, annotations, and export cookbook](doc/cookbook/datasets-and-annotations.md) for the end-to-end workflow.

If you think of the entire data archive as a giant spreadsheet, with a column for each PV name and a row for each measurement timestamp, a Data block specifies some region within that spreadsheet, and a Data Set contains a collection of those regions.  This is illustrated in the figure below.

![dataset figure](./doc/images/dataset-datablock.png)

The file ___annotation.proto___ defines the messages DataSet and DataBlock for use as the data model for creating annotations, where a DataSet includes a list of DataBlock messages, and each DataBlock includes begin and end Timestamp messages (described above), and a list of PV names.

The API includes methods for saving, querying, retrieving, deleting, and exporting Data Sets.  Each is described in more detail below.

### Data Set Save Methods
<table>
<tr>
<td><pre>
rpc saveDataSet(SaveDataSetRequest) returns (SaveDataSetResponse);
</pre></td>
</tr>
<tr>
<td>defined in: annotation.proto</td>
</tr>
<tr>
<td>

saveDataSet() is a unary single request/response method for creating or replacing a Data Set.  It accepts a SaveDataSetRequest message and returns a SaveDataSetResponse.

----

A SaveDataSetRequest lists the client-settable Data Set fields directly rather than embedding a DataSet message: id, name, ownerId, description, dataBlocks, tags, attributes, and modifiedBy.  Each DataBlock message specifies a list of PVs and a range of time to identify a region of interest in the archive.

If the optional id field is empty a new Data Set is created and the service generates its id; if id is supplied, the corresponding existing Data Set is replaced.

**Full replace on update.**  All fields are replaced with the request contents.  Fields omitted from the request are not preserved, so callers must supply the complete desired state on every save.  patchDataSet() will provide partial-update semantics in a future release.

The audit timestamps createdTime and updatedTime are server-set and are not accepted as input; they are returned in getDataSet() and queryDataSets() responses only.

----

A SaveDataSetResponse message contains one of two payloads, an ExceptionalResult message if a rejection or error was encountered, or a SaveDataSetResult.

A SaveDataSetResult message contains the unique identifier of the new or updated dataset.

</td>
</tr>
</table>

### Data Set Query Methods
<table>
<tr>
<td><pre>
rpc queryDataSets(QueryDataSetsRequest) returns (QueryDataSetsResponse);
</pre></td>
</tr>
<tr>
<td>defined in: annotation.proto</td>
</tr>
<tr>
<td>

The "queryDataSets()" method is a unary single request/response method that searches for datasets in the archive that match the search criteria specified for the query.  It accepts a QueryDataSetsRequest message and returns a QueryDataSetsResponse message.

----

A QueryDataSetsRequest contains a list of QueryDataSetsCriterion entries and optional pagination parameters (limit, pageToken).  Multiple criteria are combined with logical AND; values within a single criterion are combined with logical OR.  Criterion types include:

- **IdCriterion** — match by Data Set id.  This is the batch-retrieval path for the dataSetIds returned by queryAnnotations(): gather the ids across the returned annotations and fetch all the referenced Data Sets in one call, rather than issuing a getDataSet() per id.
- **OwnerCriterion** — match by owner id.
- **NameCriterion** — match by name using exact, prefix, and/or contains sub-lists (all ORed together).
- **TextCriterion** — full-text search over the record's indexed text fields, which are name and description.  This is a collection-level text index search, not a per-field match; use NameCriterion when a match must be restricted to the name.
- **PvNameCriterion** — match Data Sets having a Data Block that names any of the specified PVs.
- **TagsCriterion** — match records that have any of the specified tags.
- **AttributesCriterion** — match by attribute key and optional value(s); an empty values list matches any record that has the key regardless of value (key-only / existence search).

An empty criteria list matches all Data Sets.

**Pagination.**  limit is the maximum number of records in a page; an unset or zero limit means a server-configured default page size, not an unbounded result.  Clients must follow nextPageToken to retrieve all matching records.  pageToken is an opaque continuation token from a previous response; a malformed token is rejected with an ExceptionalResult.

**Ordering.**  Results are ordered by id ascending.  The id is unique, which makes paging stable, and is approximately insertion order.

----

The queryDataSets() method returns a QueryDataSetsResponse message with the query results.  The payload is an ExceptionalResult if the request is rejected or an error is encountered, otherwise a DataSetsResult containing a list of DataSet messages and a nextPageToken for retrieving subsequent pages.  An empty nextPageToken indicates the last page.  An empty result set is returned as a DataSetsResult with an empty list, not an ExceptionalResult.

A DataSet message includes the following properties for the dataset: unique id, name, owner id, description, the list of DataBlock messages comprising the dataset, tags, attributes, the server-set createdTime and updatedTime, and modifiedBy.

</td>
</tr>
</table>

### Data Set Get Methods
<table>
<tr>
<td><pre>
rpc getDataSet(GetDataSetRequest) returns (GetDataSetResponse);
</pre></td>
</tr>
<tr>
<td>defined in: annotation.proto</td>
</tr>
<tr>
<td>

The getDataSet() method retrieves a single Data Set by id.  This is the content-retrieval path for the dataSetIds returned by queryAnnotations(), which carry ids only and not embedded Data Set content.

To retrieve many Data Sets at once, prefer queryDataSets() with an IdCriterion listing the ids — that is a single round trip, whereas a getDataSet() per id is not.

----

A GetDataSetRequest contains dataSetId, the id of the Data Set to retrieve.

----

The response payload is an ExceptionalResult if the request is rejected, an error is encountered, or no Data Set exists with the specified id, otherwise a GetDataSetResult containing the matching DataSet record.

</td>
</tr>
</table>

### Data Set Delete Methods
<table>
<tr>
<td><pre>
rpc deleteDataSet(DeleteDataSetRequest) returns (DeleteDataSetResponse);
</pre></td>
</tr>
<tr>
<td>defined in: annotation.proto</td>
</tr>
<tr>
<td>

The deleteDataSet() method deletes the Data Set with the specified id.

**Referential integrity.**  The request is rejected while any Annotation references the Data Set in its dataSetIds — a containment-strength association.  Delete or update those annotations first; use queryAnnotations() with a DataSetsCriterion to find them.

----

A DeleteDataSetRequest contains dataSetId, the id of the Data Set to delete.

----

The response payload is an ExceptionalResult if the request is rejected (including rejection for referencing Annotations), an error is encountered, or no Data Set exists with the specified id, otherwise a DeleteDataSetResult containing the id of the deleted record.

</td>
</tr>
</table>

### Data Set Placeholder Methods

One additional Data Set method is defined in the proto but not yet implemented.  Calling it returns an error response.  It is defined now to reserve its name and establish the standard CRUD pattern for metadata APIs in this service.

<table>
<tr>
<td><pre>
rpc patchDataSet(PatchDataSetRequest) returns (PatchDataSetResponse);
</pre></td>
</tr>
<tr>
<td>defined in: annotation.proto</td>
</tr>
<tr>
<td>

**patchDataSet()** will provide partial-update semantics, allowing individual fields (name, description, dataBlocks, tags, attributes, modifiedBy) to be updated without replacing the entire record.  Field mask design is deferred to the release that implements this method.

There is deliberately no bulkSaveDataSet() method.  Unlike PV metadata and configuration activations, Data Sets are not bulk-imported from external systems, so the bulk-write half of the CRUD pattern is omitted rather than stubbed.

</td>
</tr>
</table>

### Data Export Methods
<table>
<tr>
<td><pre>
rpc exportData(ExportDataRequest) returns (ExportDataResponse);
</pre></td>
</tr>
<tr>
<td>defined in: annotation.proto</td>
</tr>
<tr>
<td>

The method exportData() exports data for DataSets and Calculations to common file formats.  It is a unary single request / response method that accepts an ExportDataRequest message and returns an ExportDataResponse message.

----

Parameters to the exportData() method are contained in an ExportDataRequest message that specifies the data to export and the desired output file format.  There are three ways to specify data, and they may be combined in a single request:

- **dataSetId** — the id of a saved DataSet.
- **dataBlocks** — an inline, ad-hoc list of DataBlock messages, each a time range plus a list of PV names.  This uses the same building block a DataSet contains and is treated by the service as a transient dataset.  It is the path for a one-off export that does not warrant saving a DataSet; use dataSetId when the selection is worth keeping and re-using.
- **calculationsSpec** — a CalculationsSpec identifying a Calculations object by calculationsId, with an optional column filter.

Each is optional individually, but at least one must be supplied; a request specifying none is rejected.  The outputFormat enum is required.

----

The Annotation Service handling for the exportData() API method supports exporting datasets (saved or ad-hoc), Calculations, or any combination, to tabular (CSV, XLSX) and bucketed (HDF5) export output file formats.  A filtering mechanism is provided for selecting Calculations columns to include in the export using the columns specified in the CalculationsSpec message's optional "dataFrameColumns" map.

**Output format restriction.**  The tabular formats (CSV, XLSX) can only represent scalar columns.  A dataset or Calculations object containing array, image, or struct columns can be exported to HDF5, but a request to export it as CSV or XLSX is rejected.

----

For tabular export output file formats, when the export request includes only dataset content (a saved DataSet or inline dataBlocks), the output file contains data for each data block, with a column for each PV over the data block's time range. When the export includes only a Calculations object, the  output file includes data for the filtered columns from the Calculations.  When both dataset content and a Calculations object are included in the export request, the output file will contain first the columns for the dataset, followed by the filtered Calculations columns.  Only Calculations values that fall within the time range of the dataset are included.

----

The bucketed export output file format (HDF5) uses the following directory (HDF5 group) structure for navigating the data within the file:

* _dataset_ - Facilitates navigation by the DataSet object's data blocks.  Index paths to a data block follow the pattern "/dataset/datablocks/dataBlockIndex/", where the directory (group) for a data block includes fields for its list of PVs, begin timestamp, and end timestamp.
* _pvs_ - Facilitates navigation by PV name and bucket timestamp.  Paths to bucket data follow the pattern "/pvs/pvName/times/bucketFirstTimestampSeconds/bucketFirstTimestampNanos/".  The directory (group) for a data bucket includes fields for first and last timestamp, sample count, sampling period, a byte array representation of the serialized protobuf DataColumn object containing the bucket's data vector, a byte array representation of the serialized protobuf DataTimestamps object for the bucket, tags, attributes, event metadata, and provider.
* _times_ - Facilitates navigation by timestamp and PV.  Paths to bucket data follow the pattern "/times/bucketFirstTimestampSeconds/bucketFirstTimestampNanos/pvs/pvName/".  Fields for each data bucket are listed above for navigation by PV.
* _calculations_ - Facilitates navigation by the Calculations object's frames and columns. Index paths follow the pattern "/calculations/calculationId/frames/frameIndex/columns/columnIndex/".

----

The exportData() method returns an ExportDataResponse, whose payload includes either an ExceptionalResult indicating a problem in handling the export request, or an ExportDataResult for a successful request.

ExportDataResult includes fields specifying the full path for the export output file and (optionally if configured) the URL for accessing the file via a web server.

</td>
</tr>
</table>

## Annotation API

An Annotation allows clients to annotate the data archive with notes and descriptive information, data and experiment associations, and post-acquisition Calculations.

See the [Data sets, annotations, and export cookbook](doc/cookbook/datasets-and-annotations.md) for worked examples of annotating datasets, publishing Calculations, and exporting.

Some of the concepts helpful in understanding the Annotation API are discussed below, followed by details for the Data Platform APIs for creating and querying Annotations.

#### annotations

An Annotation includes required fields for owner id, a list of unique ids for the associated Data Sets, and a brief name.  It includes the following optional fields:

- annotationIds: list of unique ids for associated annotations
- description: free-form descriptive text
- tags: list of tags / keywords for cataloging the annotation
- attributes: list of key / value attribute pairs for cataloging the annotation
- calculations: used to attach user-defined calculations (more details below)
- modifiedBy: identity of the actor performing the most recent save

The service additionally sets and returns the audit timestamps createdTime and updatedTime, which are not accepted as input.

The read and write shapes differ in how calculations are carried.  SaveAnnotationRequest accepts the calculations content shown above.  The Annotation message returned by queries additionally carries calculationsId, the id of the saved Calculations object, empty if the Annotation has none; its calculations field is populated by getAnnotation() only, and is left empty by queryAnnotations().  A non-empty calculationsId with an empty calculations field therefore means the content was simply not fetched by that method, not that there is none.

The primary key is an opaque server-generated id.  Annotation names are not unique, so unlike the natural-key metadata APIs in this service, the id is the only way to address a specific record in getAnnotation(), deleteAnnotation(), and the annotationIds of other Annotations.

**References, not embedded content.**  An Annotation carries dataSetIds and calculationsId — ids, not content.  Retrieve Data Set content with getDataSet(), or in bulk with a single queryDataSets() call using an IdCriterion listing the ids gathered across a page of annotations.  Retrieve Calculations content with getCalculations(), or inline from getAnnotation().

#### data provenance tracking

The lists of associated DataSet ids and Annotation ids are an initial attempt to meet the requirement for tracking data provenance.  To add Calculations that are derived from (or related to) regular PV time-series data in the archive, the following steps are taken:

- Create a DataSet that contains one or more Data Blocks that reference the PVs and time range(s) from the archive used in the calculation.
- Create an Annotation containing the unique id of that DataSet in the list of dataSetIds, and includes the desired Calculations.

To add Calculations that are derived from other user-defined Calculations (that are part of another Annotation like the one created above), the following step is taken:

- Create an Annotation containing the unique id of the Annotation that contains the original Calculations in the list of associated annotationIds, and includes the new Calculations derived from the original.

Both of the above record provenance at the document level: they say which archived data and which other annotations a body of work drew on.  Individual calculation columns can additionally carry provenance at the column level, in the ColumnProvenance message of their ColumnMetadata.  Its "derivedFrom" list names the specific source PVs or Calculations columns a column was computed from, and optionally the source time interval consumed.  See [column metadata and provenance](#column-metadata-and-provenance) for the full description.

Links recorded in annotationIds and in derivedFrom are soft associations: they are not validated, and deleting a referenced record leaves them dangling.  A link that resolves to nothing means the referenced record was deleted, and readers must tolerate it.  Links from an Annotation to a Data Set are stronger — deleteDataSet() is rejected while any Annotation references the Data Set.

#### calculations

The Calculations object defines the data structure used for representing user-defined Calculations attached to an Annotation.

To the extent possible, it parallels the data structures used in the ingestion of regular time-series data in order that user-defined Calculations can be treated in a similar fashion for the purposes of querying and exporting data that includes both PV data and user-defined Calculations.

The Calculations object carries a server-generated id and calculationDataFrames, a list of CalculationsDataFrames (note the singular "calculation" in the field name).  Each CalculationsDataFrame includes a name and a DataFrame — the same message used as the unit of ingestion, carrying the timestamps for the frame plus lists of typed data columns.  Calculation output therefore has access to the same scalar, array, image, struct, and serialized column types as ingested data, and to per-column ColumnMetadata, which is where column-level provenance is recorded.

It might be helpful to use the analogy of an Excel workbook.  The Calculations object is the workbook, and each CalculationsDataFrame is a worksheet in that workbook that contains a column of timestamps and columns of calculated data with a value for each timestamp.

Frame names must be distinct within a Calculations object: frame names address frames in the CalculationsSpec dataFrameColumns map and in provenance links, so duplicates would be unaddressable and are rejected.

**Sparsity.**  A calculation whose values occur at a different or sparser cadence than its siblings gets its own frame with its own time axis, rather than a dense column padded with missing values.  Data frames are cheap, and every column is dense on its own frame's axis.  The legacy DataColumn type remains reachable through the frame's DataFrame as an escape hatch for heterogeneously typed columns or columns with genuinely missing values; prefer the typed columns otherwise.

**Lifecycle and addressing.**  Calculations are owned by their Annotation: they are created and replaced through saveAnnotation(), and are deleted when the Annotation is deleted.  They are nonetheless stored separately and carry their own id, which makes them separately retrievable with getCalculations().  That calculationsId is the single addressing key for Calculations across the API — getCalculations(), CalculationsSpec for export, and ColumnProvenance links all take it.  It is returned by saveAnnotation() and is present on every Annotation returned by a query or get.

### Annotation Save Methods
<table>
<tr>
<td><pre>
rpc saveAnnotation(SaveAnnotationRequest) returns (SaveAnnotationResponse);
</pre></td>
</tr>
<tr>
<td>defined in: annotation.proto</td>
</tr>
<tr>
<td>

The method saveAnnotation() creates or replaces an Annotation for the specified list of associated dataset(s).  It accepts a SaveAnnotationRequest message and returns a SaveAnnotationResponse message.

This is also the write path for Calculations — there is no saveCalculations() method.

----

A SaveAnnotationRequest includes fields for the required and optional Annotation fields described above.  If the optional id field is empty a new Annotation is created and the service generates its id; if id is supplied, the corresponding existing Annotation is replaced.

**Full replace on update.**  All fields are replaced with the request contents.  Fields omitted from the request are not preserved, so callers must supply the complete desired state on every save.  This includes calculations: an update that omits calculations clears the Annotation's existing calculations, which is the most costly instance of the general rule.  Read the current state with getAnnotation() and resend it if you are updating other fields.  patchAnnotation() will provide partial-update semantics in a future release.

The id field of a supplied Calculations object is ignored on save; the service assigns the id.  The audit timestamps createdTime and updatedTime are likewise server-set and are not accepted as input.

----

A SaveAnnotationResponse message includes one of two payloads, either an ExceptionalResult if an error is encountered, or a SaveAnnotationResult if the operation is successful.

A SaveAnnotationResult message contains the unique identifier of the new or updated annotation, and — when the request carried calculations — the calculationsId of the saved Calculations object.  The latter is returned here so that the addressing key used by getCalculations(), CalculationsSpec, and ColumnProvenance links is available without a further round trip.

</td>
</tr>
</table>

### Annotation Query Methods
<table>
<tr>
<td><pre>
rpc queryAnnotations(QueryAnnotationsRequest) returns (QueryAnnotationsResponse);
</pre></td>
</tr>
<tr>
<td>defined in: annotation.proto</td>
</tr>
<tr>
<td>

The queryAnnotations() method is a unary single request/response method that searches for Annotations in the archive that match the search criteria specified for the query.  It accepts a QueryAnnotationsRequest message and returns a QueryAnnotationsResponse message.

----

A QueryAnnotationsRequest contains a list of QueryAnnotationsCriterion entries and optional pagination parameters (limit, pageToken).  Multiple criteria are combined with logical AND; values within a single criterion are combined with logical OR.  Criterion types include:

- **IdCriterion** — match by Annotation id.
- **OwnerCriterion** — match by owner id.
- **DataSetsCriterion** — match Annotations referencing any of the specified Data Set ids.  This is also how to find the Annotations that block a deleteDataSet().
- **AnnotationsCriterion** — match Annotations referencing any of the specified Annotation ids.
- **NameCriterion** — match by name using exact, prefix, and/or contains sub-lists (all ORed together).
- **TextCriterion** — full-text search over the record's indexed text fields, which are name and description.  This is a collection-level text index search, not a per-field match; use NameCriterion when a match must be restricted to the name.
- **TagsCriterion** — match records that have any of the specified tags.
- **AttributesCriterion** — match by attribute key and optional value(s); an empty values list matches any record that has the key regardless of value (key-only / existence search).

An empty criteria list matches all Annotations.

**Pagination.**  limit is the maximum number of records in a page; an unset or zero limit means a server-configured default page size, not an unbounded result.  Clients must follow nextPageToken to retrieve all matching records.  pageToken is an opaque continuation token from a previous response; a malformed token is rejected with an ExceptionalResult.

**Ordering.**  Results are ordered by id ascending.  The id is unique, which makes paging stable, and is approximately insertion order.

----

The queryAnnotations() method returns a QueryAnnotationsResponse message with the query results.  The payload is an ExceptionalResult if the request is rejected or an error is encountered, otherwise an AnnotationsResult containing a list of Annotation messages and a nextPageToken for retrieving subsequent pages.  An empty nextPageToken indicates the last page.  An empty result set is returned as an AnnotationsResult with an empty list, not an ExceptionalResult.

Returned Annotations carry references, not embedded content: dataSetIds and calculationsId are populated, and the calculations field is empty.  Fetch the referenced Data Sets in a single queryDataSets() call using an IdCriterion listing the ids gathered across the page, and Calculations content with getCalculations() or getAnnotation().

Because calculationsId is always populated when calculations exist, it doubles as the presence indicator: an empty calculationsId means the Annotation has no calculations, and a non-empty one paired with an empty calculations field means the content was simply not fetched by this method.

</td>
</tr>
</table>

### Annotation Get Methods
<table>
<tr>
<td><pre>
rpc getAnnotation(GetAnnotationRequest) returns (GetAnnotationResponse);
</pre></td>
</tr>
<tr>
<td>defined in: annotation.proto</td>
</tr>
<tr>
<td>

The getAnnotation() method retrieves a single Annotation by id, with its Calculations content populated inline as a one-hop convenience for the common "open this annotation" case.  This is the only method that returns Calculations content within an Annotation; queryAnnotations() returns calculationsId only.

Associated Data Sets are returned as ids, not content; use getDataSet() or queryDataSets() with an IdCriterion to retrieve them.

----

A GetAnnotationRequest contains annotationId, the id of the Annotation to retrieve.

----

The response payload is an ExceptionalResult if the request is rejected, an error is encountered, or no Annotation exists with the specified id, otherwise a GetAnnotationResult containing the matching Annotation record.

</td>
</tr>
</table>

### Annotation Delete Methods
<table>
<tr>
<td><pre>
rpc deleteAnnotation(DeleteAnnotationRequest) returns (DeleteAnnotationResponse);
</pre></td>
</tr>
<tr>
<td>defined in: annotation.proto</td>
</tr>
<tr>
<td>

The deleteAnnotation() method deletes the Annotation with the specified id.  The Annotation's Calculations, if any, are deleted with it — their lifecycle belongs to the owning Annotation.

**Referential integrity.**  Unlike deleteDataSet(), this delete is not blocked by incoming references.  Other Annotations listing this annotation's id in annotationIds, and ColumnProvenance derivedFrom links naming its calculations, are soft associations and are permitted to dangle.  A soft link that resolves to nothing means the referenced record was deleted, and readers must tolerate it.

----

A DeleteAnnotationRequest contains annotationId, the id of the Annotation to delete.

----

The response payload is an ExceptionalResult if the request is rejected, an error is encountered, or no Annotation exists with the specified id, otherwise a DeleteAnnotationResult containing the id of the deleted record.

</td>
</tr>
</table>

### Annotation Placeholder Methods

One additional Annotation method is defined in the proto but not yet implemented.  Calling it returns an error response.  It is defined now to reserve its name and establish the standard CRUD pattern for metadata APIs in this service.

<table>
<tr>
<td><pre>
rpc patchAnnotation(PatchAnnotationRequest) returns (PatchAnnotationResponse);
</pre></td>
</tr>
<tr>
<td>defined in: annotation.proto</td>
</tr>
<tr>
<td>

**patchAnnotation()** will provide partial-update semantics, allowing individual fields (dataSetIds, name, annotationIds, description, tags, attributes, calculations, modifiedBy) to be updated without replacing the entire record.  Field mask design is deferred to the release that implements this method.

As with Data Sets, there is deliberately no bulkSaveAnnotation() method: Annotations are not bulk-imported from external systems, so the bulk-write half of the CRUD pattern is omitted rather than stubbed.

</td>
</tr>
</table>

### Calculations Get Methods
<table>
<tr>
<td><pre>
rpc getCalculations(GetCalculationsRequest) returns (GetCalculationsResponse);
</pre></td>
</tr>
<tr>
<td>defined in: annotation.proto</td>
</tr>
<tr>
<td>

The getCalculations() method retrieves a single Calculations object by id, without loading the owning Annotation's descriptive payload.  This is the click-through path: list annotations, pick one, then fetch exactly its calculations using the calculationsId the listing returned.

Obtain a calculationsId from SaveAnnotationResult, from the calculationsId field of an Annotation returned by a query or get, or from a ColumnProvenance CalculationsColumn provenance link.

----

A GetCalculationsRequest contains calculationsId, the id of the Calculations object to retrieve.

----

The response payload is an ExceptionalResult if the request is rejected, an error is encountered, or no Calculations object exists with the specified id, otherwise a GetCalculationsResult containing the matching Calculations record.

----

Calculations have no save, delete, or query method of their own, and the asymmetry is deliberate.  They are written and replaced through saveAnnotation(), their lifecycle belongs to the owning Annotation (deleteAnnotation() removes them), and discovery goes through queryAnnotations().  Only retrieval needs a standalone path, because a client that already holds a calculationsId should not have to fetch an annotation to use it.

</td>
</tr>
</table>



---
## Data Platform API Conventions

### ordering of elements

Within the Data Platform service proto files, elements are listed in the following order:

1. service method definitions
2. definition of request and response messages
3. supporting data structures used in the request and response messages

### packaging of parameters for a method into a single "request" message

For all Data Platform service methods, parameters are bundled into a single "request" message data type, instead of listing multiple parameters to the method.

### naming of request and response messages

The service-specific proto files each begin with a "service" definition block that defines the method interface for that service, including parameters and return types.  Where possible, the data types for the request and response use message names based on the corresponding method name.

A simple example is the Ingestion Service method registerProvider(). The method request parameters are bundled in a message data structure called RegisterProviderRequest. The method returns the response message type RegisterProviderResponse.  So the method definition looks like this:

```
rpc registerProvider (RegisterProviderRequest) returns (RegisterProviderResponse);
```

A more complex example is the Ingestion Service RPC methods ingestDataBidiStream() (bidirectional streaming data ingestion API), ingestDataStream() (client-side streaming data ingestion API), and ingestData() (unary data ingestion API). We want the methods to use the same request and response data types, so we use the common message types IngestDataRequest and IngestDataResponse. This pattern is also used for time-series data queries defined in ___query.proto___.  The method definitions look like this:

```
rpc ingestData (IngestDataRequest) returns (IngestDataResponse);
rpc ingestDataStream (stream IngestDataRequest) returns (IngestDataStreamResponse);
rpc ingestDataBidiStream (stream IngestDataRequest) returns (stream IngestDataResponse);
```

### nesting of messages

Where possible, nesting is used to enclose simpler messages within the more complex messages that use them.  In cases where we want to share messages between multiple request or response messages, the definition of those messages appears after the request and response messages in the proto file.  Messages whose scope is limited to a particular service are defined in the proto file for that service.  Messages whose scope is broader than a single service are defined in common.proto.

### determining successful method execution

A common pattern is used across all Data Platform service method responses to assist in determining whether an operation succeeded or failed.  All response messages use the gRPC "oneof" mechanism so that the message payload is either an ExceptionalResult message indicating that the operation failed, or a method-specific message containing the result of a successful operation.

The ExceptionalResult message is defined in "common.proto" with an enum indicating the status of the operation and a descriptive message.  The enum indicates operations that were rejected, encountered an error in processing, failed to return data, resources that were unavailable when requested, etc.

Here is an example of the use of this pattern in the "QueryDataResponse" message used to send the result of time-series data queries:

```
message QueryDataResponse {

  oneof result {
    ExceptionalResult exceptionalResult = 10;
    QueryData queryData = 11;
  }

  message QueryData {

    repeated DataBucket dataBuckets = 1;

    message DataBucket {
      // DataBucket field definitions...
    }
  }
}
```

### empty query results

Another common pattern across Data Platform API query methods is in reporting empty query results.  When a query matches no data, the list of results in the query response message is empty.  For example, when a time-series data query method returns no data, the QueryDataResponse message (show above) contains an empty dataBuckets list.


---
## Example Java gRPC API Code

For task-oriented examples spanning multiple API calls, see the [API Cookbook](doc/cookbook/README.md).  The example below shows the mechanics of a single call.

Here is a simple example of calling the registerProvider() API from Java, after running protoc to build Java stubs.

First the code to build a RegisterProviderRequest object from a "params" object containing the parameters for the request:

```
    public static RegisterProviderRequest buildRegisterProviderRequest(RegisterProviderRequestParams params) {

        RegisterProviderRequest.Builder builder = RegisterProviderRequest.newBuilder();

        if (params.name != null) {
            builder.setProviderName(params.name);
        }

        if (params.description != null) {
            builder.setDescription(params.description);
        }

        if (params.tags != null) {
            builder.addAllTags(params.tags);
        }

        if (params.attributes != null) {
            builder.addAllAttributes(AttributesUtility.attributeListFromMap(params.attributes));
        }

        return builder.build();
    }
```

And the code to invoke the API using the request object:

```
    protected static RegisterProviderResponse sendRegsiterProvider(
            RegisterProviderRequest request
    ) {
        final DpIngestionServiceGrpc.DpIngestionServiceStub asyncStub =
                DpIngestionServiceGrpc.newStub(ingestionChannel);

        final RegisterProviderUtility.RegisterProviderResponseObserver responseObserver =
                new RegisterProviderUtility.RegisterProviderResponseObserver();

        asyncStub.registerProvider(request, responseObserver);

        responseObserver.await();

        if (responseObserver.isError()) {
            fail("responseObserver error: " + responseObserver.getErrorMessage());
        }

        return responseObserver.getResponseList().get(0);
    }
```



