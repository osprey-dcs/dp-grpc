# Machine Configuration Cookbook

Worked examples for the Machine Configuration and Configuration Activation APIs, part of the
Annotation Service.

Reference documentation: [Machine Configuration API](../../README.md#machine-configuration-api)
and [Configuration Activation API](../../README.md#configuration-activation-api).

### Imports used by the examples

Snippets name generated classes without qualification, for readability.  The activation query
criterion types nest two levels inside the request:

```java
import com.ospreydcs.dp.grpc.v1.annotation.SaveConfigurationRequest;
import com.ospreydcs.dp.grpc.v1.annotation.SaveConfigurationActivationRequest;
import com.ospreydcs.dp.grpc.v1.annotation.QueryConfigurationActivationsRequest;
import com.ospreydcs.dp.grpc.v1.annotation.GetConfigurationActivationRequest;
import com.ospreydcs.dp.grpc.v1.annotation.GetActiveConfigurationsRequest;
import com.ospreydcs.dp.grpc.v1.common.ConfigurationActivation;
import com.ospreydcs.dp.grpc.v1.common.Timestamp;

// nested inside the request message
import com.ospreydcs.dp.grpc.v1.annotation.QueryConfigurationActivationsRequest.QueryConfigurationActivationsCriterion;
import com.ospreydcs.dp.grpc.v1.annotation.QueryConfigurationActivationsRequest.QueryConfigurationActivationsCriterion.ConfigurationNameCriterion;
import com.ospreydcs.dp.grpc.v1.annotation.QueryConfigurationActivationsRequest.QueryConfigurationActivationsCriterion.TimestampCriterion;
import com.ospreydcs.dp.grpc.v1.annotation.QueryConfigurationActivationsRequest.QueryConfigurationActivationsCriterion.TimeRangeCriterion;
```

## Contents

- [Recording a configuration change in real time](#recording-a-configuration-change-in-real-time)
  — the common case: a PV reports a change and you must close the current activation and open a
  new one
- [Listing activations for a configuration](#listing-activations-for-a-configuration)
- [Finding the current or latest activation](#finding-the-current-or-latest-activation)

## Model

A **`Configuration`** is a reusable, named machine configuration definition — it has no time
component.  `configurationName` is its primary key.

A **`ConfigurationActivation`** records a time interval during which a Configuration was active:
a `configurationName`, a required `startTime`, and an optional `endTime`.  An absent `endTime`
means the interval is open-ended — the configuration is still in effect.

Intervals are half-open.  Setting one activation's `endTime` equal to the next activation's
`startTime` yields continuous coverage with no gap and no overlap.  The server rejects
overlapping activations for the same `configurationName`, and for different configurations
within the same `category`.

## Recording a configuration change in real time

This is the workflow for a live bridge: a PV reports that the machine changed configuration,
possibly reporting it late, and you need the activation history to reflect the change without a
gap.

### 1. Create the configuration

A Configuration must exist before any activation can reference it.  This is typically done once,
at setup, not per change.

```java
SaveConfigurationRequest.newBuilder()
    .setConfigurationName("linac-rf-config-A")   // required; canonical primary key
    .setCategory("rf")                           // required
    .setDescription("Linac RF configuration variant A")
    .setModifiedBy("rf-ioc-bridge")
    .build();
```

`SaveConfigurationResult.configurationName` echoes the name back.

`saveConfiguration()` is a **full-replace upsert**.  On update you must supply the complete
desired state — omitted fields are cleared, not preserved.

### 2. Open the first activation

Leave `endTime` unset to mean "still in effect":

```java
SaveConfigurationActivationRequest.newBuilder()
    .setClientActivationId("act-0001")     // optional; server generates one if absent
    .setConfigurationName("linac-rf-config-A")
    .setStartTime(ts(t0))                  // required
    // no endTime -> open-ended
    .setModifiedBy("rf-ioc-bridge")
    .build();
```

When driving this from a live stream rather than loading from a calendar, **supply your own
`clientActivationId`**.  It lets you address the record later via `getConfigurationActivation()`
without a lookup.  If you omit it, retain the server-generated ID returned in
`SaveConfigurationActivationResult.clientActivationId`.

### 3. Close the old activation and open the new one

When the PV reports a change at time `t1`:

```java
// a) find the activation currently in effect (see "Finding the current or latest activation")
ConfigurationActivation current = latestActivationFor("linac-rf-config-A");

// b) close it: re-save the SAME clientActivationId with endTime set.
//    Full-replace semantics -- resend every field you want to keep.
SaveConfigurationActivationRequest.newBuilder()
    .setClientActivationId(current.getClientActivationId())  // same ID = update in place
    .setConfigurationName(current.getConfigurationName())
    .setStartTime(current.getStartTime())
    .setEndTime(ts(t1))                                      // <-- close it
    .setDescription(current.getDescription())
    .addAllTags(current.getTagsList())
    .addAllAttributes(current.getAttributesList())
    .setModifiedBy("rf-ioc-bridge")
    .build();

// c) open the new activation starting exactly where the previous one ended
SaveConfigurationActivationRequest.newBuilder()
    .setClientActivationId("act-0002")
    .setConfigurationName("linac-rf-config-B")
    .setStartTime(ts(t1))          // == previous endTime: continuous, no gap
    .setModifiedBy("rf-ioc-bridge")
    .build();
```

Two things to get right:

- **Reuse the same `clientActivationId` in step (b).**  That is what makes the call an update
  rather than the creation of a second activation record.
- **Copy fields forward.**  Because `save*` is full-replace, omitting `description`, `tags`, or
  `attributes` erases them.  Read the current record first and carry its values across.

`patchConfigurationActivation()` will eventually allow setting `endTime` alone without the
copy-forward step, but it is a reserved placeholder as of 1.14 and returns a "not implemented"
error.

### A note on late reports

If the PV reports the change well after it happened, use the *actual* change time as `t1`, not
the time the report arrived.  Because step (b) sets an explicit `endTime` and step (c) uses that
same value as `startTime`, backdating is simply a matter of choosing `t1` — no special handling
is required.  The server's overlap validation applies to the resulting intervals, so a `t1`
earlier than the current activation's `startTime` will be rejected.

## Listing activations for a configuration

Use `queryConfigurationActivations()` with a `ConfigurationNameCriterion`:

```java
QueryConfigurationActivationsRequest.newBuilder()
    .addCriteria(QueryConfigurationActivationsCriterion.newBuilder()
        .setConfigurationNameCriterion(
            ConfigurationNameCriterion.newBuilder()
                .addValues("linac-rf-config-A")))   // repeated -> OR across names
    .setLimit(100)
    .setPageToken(pageToken)                        // "" for the first page
    .build();
```

Read `QueryConfigurationActivationsResult.configurationActivations`, then loop while
`nextPageToken` is non-empty, passing it as `pageToken` on the next request.

Criteria in the outer `criteria` list are **ANDed**; multiple values within a single criterion
are **ORed**.  An empty result is returned as an empty list, not an `ExceptionalResult`.

## Finding the current or latest activation

The API does not sort results or expose a "latest" flag, so there are three approaches depending
on what you actually need.

### The configuration currently in effect

`getActiveConfigurations()` returns every activation in effect at a point in time — that is,
`startTime <= t AND (endTime absent OR endTime > t)`:

```java
GetActiveConfigurationsRequest.newBuilder()
    .setTimestamp(ts(now))
    .build();
```

Filter the returned list to your `configurationName`.  This is the cheapest and most direct
answer to "what is active right now", and it is the right call for the real-time workflow above:
the record you need to close is by definition the open-ended one.

### The same, scoped to one configuration in a single call

`TimestampCriterion` applies the same point-in-time predicate, and can be ANDed with a
configuration name so the server does the filtering:

```java
QueryConfigurationActivationsRequest.newBuilder()
    .addCriteria(criterion().setConfigurationNameCriterion(names("linac-rf-config-A")))
    .addCriteria(criterion().setTimestampCriterion(at(now)))   // separate criteria are ANDed
    .setLimit(10)
    .build();
```

### The most recent activation, including closed ones

If the latest activation has already been closed — its `endTime` is in the past — neither
approach above will match it, since neither is in effect at `now`.  In that case query and take
the maximum `startTime` client-side.

There is no sort order and no `totalCount` field, so this means paging through the matching set.
If the configuration has a long history, bound the query with a `TimeRangeCriterion` rather than
scanning everything:

```java
QueryConfigurationActivationsRequest.newBuilder()
    .addCriteria(criterion().setConfigurationNameCriterion(names("linac-rf-config-A")))
    .addCriteria(criterion().setTimeRangeCriterion(range(ts(oneDayAgo), ts(now))))
    .setLimit(100)
    .build();
```

`TimeRangeCriterion` matches activations that *overlap* the window:
`activation.startTime < endTime AND (activation.endTime absent OR activation.endTime > startTime)`.

## Also worth knowing

- Deleting a `Configuration` is rejected while `ConfigurationActivation` records still reference
  it.
- `getConfigurationActivation()` accepts either `clientActivationId` **or** the composite key
  `configurationName` + `startTime` — useful if you did not retain a server-generated ID.
- `createdTime` and `updatedTime` are server-set audit fields.  They are returned in query and
  get responses but are not accepted as input on save.
- All responses use the standard `oneof result` of `ExceptionalResult` or the method-specific
  success payload; check which is set before reading.
