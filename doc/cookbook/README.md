# MLDP API Cookbook

Task-oriented, worked examples of calling the MLDP gRPC API.

The [main README](../../README.md) is the *reference*: it describes every method, request, and
response field by field.  This cookbook is the *guide*: each recipe walks through a complete
task that spans several API calls, in the order you would actually make them.

Recipes show Java, the language whose stubs this repo builds.  The call sequences, request
shapes, and semantics are protocol-level and apply equally from any language.

Start with [API conventions](conventions.md) — response checking, pagination, query criteria,
save semantics, and time handling recur in every recipe and are documented once there.

## Recipes

Roughly in the order a new client encounters them.

| Recipe | Covers |
|---|---|
| [API conventions](conventions.md) | Patterns shared by every method: `oneof result` handling, paging, criteria AND/OR rules, full-replace `save*`, half-open time ranges |
| [Provider registration](provider-registration.md) | Registering before ingesting, re-registering on startup, finding providers, reading a provider's archive statistics |
| [Ingesting PV data](ingestion.md) | The three ingestion methods, building a `DataFrame`, choosing a column type, sampling clocks vs. timestamp lists, and checking async request status |
| [Subscriptions](subscriptions.md) | Bidirectional streaming: tailing live PVs, triggering on a PV condition, capturing a window around a trigger, clean cancellation |
| [Querying archived data](query.md) | Query API V2 — buckets vs. samples, `QuerySpec`, paging, metadata- and configuration-driven selection, and migrating a V1 client |
| [PV metadata](pv-metadata.md) | Cataloguing PVs, updating without data loss, discovery by tag/attribute/name, alias resolution, and driving queries from metadata |
| [Machine configuration](machine-configuration.md) | Creating a configuration, recording activations in real time, closing an open activation, listing activation history |
| [Sample status](sample-status.md) | Labeling samples with status codes (dense and sparse), querying statuses, re-labeling a range, filtering data queries by status |
| [Data sets, annotations, export](datasets-and-annotations.md) | Defining DataSets, annotating them, publishing Calculations, recording column-level provenance, and exporting to HDF5/CSV/XLSX |

## Calling the API from Python

Python users should start with **[dp-python-lib](https://github.com/osprey-dcs/dp-python-lib)**,
a client library that wraps this API with Python-friendly request builders and result objects.
It is the recommended way to use MLDP from Python.

Its **[cookbook](https://github.com/osprey-dcs/dp-python-lib/tree/main/doc/cookbook)** is the
Python counterpart to this one — the same tasks, documented against that library's client classes
rather than the raw protocol.  Recipes there cover client construction and configuration, PV
metadata, machine configuration, and querying time-series data into pandas / NumPy.

If you need to work with the generated protobuf stubs directly, see
[Generating and importing Python stubs](python-stubs.md) for what this repo produces and how the
stubs are laid out.

## Conventions used in recipes

- Each recipe states the release it was **verified against**.  The API is additive across
  releases, but field sets do change; check the note before assuming a recipe applies to your
  deployment.
- Code omits imports, channel setup, and error handling except where a recipe is specifically
  about those things.
- `ts(...)` in Java examples stands for whatever helper you use to build a
  `dp.service.common.Timestamp`.
