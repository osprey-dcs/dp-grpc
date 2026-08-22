# Subscriptions Cookbook

Worked examples for the two live-data subscription methods: `DpIngestionService.subscribeData()`,
which tails new data for a list of PVs, and `DpIngestionStreamService.subscribeDataEvent()`, which
fires when a PV condition is met and can capture a window of data around the trigger.

Reference documentation: [PV Data Subscription Methods](../../README.md#pv-data-subscription-methods)
and [PV Data Event Subscription Methods](../../README.md#pv-data-event-subscription-methods).
Shared response-checking rules are in [conventions.md](conventions.md).

> The Query API V2 method referenced in passing (`queryBuckets`) was added in 1.15.0 and is
> not available in earlier releases.

## Contents

- [Model](#model) — the handshake shape both methods share
- [Tailing a set of PVs](#tailing-a-set-of-pvs) — the common case: live values for a known PV list
- [Triggering on a PV condition](#triggering-on-a-pv-condition) — threshold alarms, notification only
- [Capturing a data window around a trigger](#capturing-a-data-window-around-a-trigger) — transient
  and post-mortem capture
- [Cancelling and reconnecting](#cancelling-and-reconnecting)
- [Also worth knowing](#also-worth-knowing)

## Model

Both methods are **bidirectional streaming**.  That has one immediate practical consequence: you
must use the **async stub**.  `DpIngestionServiceGrpc.newStub(channel)` and
`DpIngestionStreamServiceGrpc.newStub(channel)` expose these methods; the blocking and future
stubs do not.

Both follow the same four-phase shape:

1. **Register.**  The client sends a request carrying a `NewSubscription` payload.  For
   `subscribeData` this must be exactly one — see below.
2. **Acknowledge.**  The service replies with a *single* response carrying either an
   `ExceptionalResult` (rejected) or an `AckResult` (registered).
3. **Stream.**  The service sends payload messages — `SubscribeDataResult` for `subscribeData`,
   `Event` and optionally `EventData` for `subscribeDataEvent` — until the subscription ends.
4. **Cancel.**  The client sends a `CancelSubscription` payload, closes the request stream, or
   both.

Two properties of this shape are easy to get wrong and worth stating up front.

**Exactly one `NewSubscription` — documented for `subscribeData` only.**  The `subscribeData`
proto is explicit: if the client sends a second `NewSubscription` on an already-registered stream,
the service rejects it and closes the response stream.  To change the PV set, cancel and open a
new stream.

`ingestion_stream.proto` states no equivalent rule for `subscribeDataEvent`, so its behavior on a
second `NewSubscription` is unspecified.  Treat the one-subscription-per-stream discipline as the
safe default for both, but do not rely on `subscribeDataEvent` rejecting a second registration.

**Subscriptions are forward-looking only.**  `subscribeData` delivers data received by the
Ingestion Service *after* the subscription is created.  There is no replay and no backfill; data
that arrived before the ack, or during a reconnect gap, must be fetched from `DpQueryService`.

Subscribing is read-only and does **not** require `registerProvider()` — provider registration
exists only for ingestion.

### The ack field is named differently in each service

This is the single most common mistake:

| Method | Ack field | Accessor |
|---|---|---|
| `subscribeData` | `ackResult = 11` | `hasAckResult()` / `getAckResult()` |
| `subscribeDataEvent` | `ack = 11` | `hasAck()` / `getAck()` |

Both `AckResult` messages are **empty** — their presence is the entire signal.  Prefer the
`hasXxx()` accessors over switching on the generated `ResultCase` enum; they are less sensitive
to the naming asymmetry.

### `ExceptionalResult` is terminal

In both services, an `ExceptionalResult` — whether it arrives at registration or mid-stream —
is followed by the service closing the response stream.  Treat it as end-of-subscription, not as
a recoverable per-message error.

## Tailing a set of PVs

The workflow for a strip chart, dashboard, or alarm sidecar that wants new values for a known
list of PVs without polling the query API.

### 1. Build the response observer

`onNext` runs on a gRPC network thread.  Do the minimum there and hand work off.

```java
CountDownLatch ackLatch  = new CountDownLatch(1);
CountDownLatch doneLatch = new CountDownLatch(1);

StreamObserver<SubscribeDataResponse> responseObserver = new StreamObserver<>() {
    @Override public void onNext(SubscribeDataResponse response) {
        if (response.hasExceptionalResult()) {
            // terminal: the service closes the response stream after this
            log(response.getExceptionalResult().getExceptionalResultStatus(),
                response.getExceptionalResult().getMessage());
            return;
        }
        if (response.hasAckResult()) {          // NOTE: ackResult, not ack
            ackLatch.countDown();
            return;
        }
        if (response.hasSubscribeDataResult()) {
            for (DataBucket bucket : response.getSubscribeDataResult().getDataBucketsList()) {
                queue.offer(bucket);           // hand off; do not decode on this thread
            }
        }
    }
    @Override public void onError(Throwable t)   { doneLatch.countDown(); }
    @Override public void onCompleted()          { doneLatch.countDown(); }
};
```

### 2. Open the stream and register

```java
DpIngestionServiceGrpc.DpIngestionServiceStub asyncStub =
        DpIngestionServiceGrpc.newStub(channel);

StreamObserver<SubscribeDataRequest> requestObserver =
        asyncStub.subscribeData(responseObserver);

requestObserver.onNext(SubscribeDataRequest.newBuilder()
    .setNewSubscription(SubscribeDataRequest.NewSubscription.newBuilder()
        .addAllPvNames(List.of("S01-BPM01:X", "S01-BPM01:Y", "S01-BCM:CURRENT")))
    .build());

ackLatch.await(10, TimeUnit.SECONDS);   // wait for registration before counting data
```

`NewSubscription.pvNames` is the *only* field in the message.  There is **no** regex, no
attribute or metadata selector, and no time range.  Query V2's `PvSelector` is not usable here —
subscriptions take exact PV names only.  If you need pattern matching, resolve the names first
with `queryPvMetadata()` and pass the resulting list.

### 3. Decode buckets

A subscription delivers `dp.service.common.DataBucket`, the same message the query API returns.
The column type mirrors whatever the provider used at ingestion time, so a subscriber to a
heterogeneous PV set **cannot assume `DoubleColumn`** — switch on the case:

```java
DataValues values = bucket.getDataValues();
switch (values.getValuesCase()) {
    case DOUBLECOLUMN -> handle(bucket.getPvName(), values.getDoubleColumn());
    case INT64COLUMN  -> handle(bucket.getPvName(), values.getInt64Column());
    case DATACOLUMN   -> handle(bucket.getPvName(), values.getDataColumn());
    // ... 16 cases total, including SERIALIZEDDATACOLUMN and the five *ARRAYCOLUMN variants
    default -> unexpected(values.getValuesCase());
}
```

Timestamps come from `bucket.getDataTimestamps()`, whose `oneof value` is either a
`samplingClock` (`startTime` + `periodNanos` + `count`, expand it yourself) or an explicit
`timestampList`.

## Triggering on a PV condition

Use `subscribeDataEvent()` when you care about a *threshold crossing* rather than every sample —
a beam-current drop, a temperature excursion.  Omitting the optional `DataEventOperation` gives
you notifications only, with no bulk data attached.

### 1. Build the triggers

```java
PvConditionTrigger trigger = PvConditionTrigger.newBuilder()
    .setPvName("S01-BCM:CURRENT")
    .setCondition(PvConditionTrigger.PvCondition.PV_CONDITION_LESS)
    .setValue(DataValue.newBuilder().setDoubleValue(5.0))
    .build();
```

Only six conditions exist: `PV_CONDITION_UNSPECIFIED`, `_EQUAL_TO`, `_GREATER`, `_GREATER_EQ`,
`_LESS`, `_LESS_EQ`.  There is no not-equal, no range or band, no rate-of-change, and no
hysteresis or debounce.  A noisy PV sitting near the threshold will fire repeatedly; debouncing
is the client's job.

**Always set the condition explicitly.**  An unset `condition` defaults to
`PV_CONDITION_UNSPECIFIED` (0), and the proto does not document what the service does with it.

The threshold is a `dp.service.common.DataValue` — a oneof of scalar and complex types.  Set the
member matching the PV's ingested type (`setDoubleValue` for a PV ingested as `DoubleColumn`).
The proto does not document cross-type coercion, so **do not rely on it**; if you set
`setIntValue` against a double-typed PV, the behavior is unspecified.

`DataValue` is marked deprecated *for ingestion* in `common.proto` because of its per-sample
allocation cost.  That warning does not apply here — `DataValue` is the correct and required
type for `PvConditionTrigger.value` and `Event.dataValue`.

### 2. Register and handle events

```java
DpIngestionStreamServiceGrpc.DpIngestionStreamServiceStub asyncStub =
        DpIngestionStreamServiceGrpc.newStub(channel);

StreamObserver<SubscribeDataEventRequest> requestObserver =
        asyncStub.subscribeDataEvent(responseObserver);

requestObserver.onNext(SubscribeDataEventRequest.newBuilder()
    .setNewSubscription(SubscribeDataEventRequest.NewSubscription.newBuilder()
        .addTriggers(trigger))          // no setOperation() -> notifications only
    .build());
```

In `onNext`, the payloads to check are `hasExceptionalResult()`, `hasAck()` (**not**
`hasAckResult()`), and `hasEvent()`:

```java
if (response.hasEvent()) {
    SubscribeDataEventResponse.Event event = response.getEvent();
    Timestamp when   = event.getEventTime();               // when the condition was met
    String    pvName = event.getTrigger().getPvName();     // which trigger fired
    DataValue value  = event.getDataValue();               // the value that satisfied it
}
```

`Event.trigger` echoes back the whole `PvConditionTrigger`, which is what lets you distinguish
firings when you registered several triggers on one stream.

Do not confuse `response.getResponseTime()` with `event.getEventTime()`.  `responseTime` sits
*outside* the oneof and is populated on every message including acks and errors; it is the
service's message-generation time, not a data timestamp.

## Capturing a data window around a trigger

For transient or post-mortem capture: when PV X crosses a limit, grab a second of data for a
whole group of related PVs, spanning before and after the event.  This is `subscribeDataEvent()`
*with* a `DataEventOperation`.

### 1. Define the window

`TimeInterval.offset` is a **signed** `int64` in nanoseconds relative to the trigger time;
negative means *before*.  `duration` is unsigned nanoseconds measured from
`triggerTime + offset`.

```java
// 1 second of data centered on the trigger: 500 ms before through 500 ms after
DataEventOperation.DataEventWindow.TimeInterval interval =
    DataEventOperation.DataEventWindow.TimeInterval.newBuilder()
        .setOffset(-500_000_000L)     // start 500 ms before the trigger
        .setDuration(1_000_000_000L)  // capture 1 s from that start point
        .build();
```

For a purely pre-trigger window, use a negative offset with `duration <= |offset|`.

`DataEventWindow`'s oneof is named `type` and has exactly **one** usable member, `timeInterval`.
A `SampleCount` variant is commented out in the proto and is not available; the proto comment
explains it is unresolved for multiple PVs on different timescales.

### 2. Attach the target PVs

```java
DataEventOperation operation = DataEventOperation.newBuilder()
    .setWindow(DataEventOperation.DataEventWindow.newBuilder()
        .setTimeInterval(interval))
    .addAllTargetPvs(List.of(
        "S01-BCM:CURRENT",       // include the trigger PV explicitly if you want its data
        "S01-BPM01:X", "S01-BPM01:Y", "S01-RF:PHASE"))
    .build();

requestObserver.onNext(SubscribeDataEventRequest.newBuilder()
    .setNewSubscription(SubscribeDataEventRequest.NewSubscription.newBuilder()
        .addTriggers(trigger)
        .setOperation(operation))
    .build());
```

`targetPvs` (note the spelling — lowercase `v`, `s`; the prose proto comment writes "targetPVs"
but the field does not) is **independent of the trigger PVs**.  That independence is the point:
trigger on one PV, capture many.  But it also means the triggering PV's own data is *not*
included unless you list it.

### 3. Handle `Event` and `EventData` as separate messages

They are distinct members of the same oneof and arrive as separate stream messages:

```java
if (response.hasEvent()) {
    // notification: arrives first, promptly
    beginCapture(response.getEvent());
} else if (response.hasEventData()) {
    SubscribeDataEventResponse.EventData eventData = response.getEventData();
    // correlate back to the notification
    Timestamp eventTime = eventData.getEvent().getEventTime();
    for (DataBucket bucket : eventData.getDataBucketsList()) {
        accumulate(eventTime, bucket.getPvName(), bucket);
    }
}
```

**`EventData` necessarily lags.**  The service cannot emit the window until the window's end time
has passed in the ingestion stream, so with the example above expect at least ~500 ms of delay
after the notification, plus pipeline latency.  Do not wait synchronously for `EventData` inside
your `Event` handler.

The proto does not specify how many `EventData` messages are sent per event, nor whether all
target PVs arrive in one message.  Write the accumulator to tolerate several messages per event,
keyed on the correlating `Event`, and decide completeness on your own timer rather than on a
message count.

## Cancelling and reconnecting

### Cancelling

Two mechanisms are documented, and both are valid:

```java
// preferred: explicit cancel, then close the request stream
requestObserver.onNext(SubscribeDataRequest.newBuilder()
    .setCancelSubscription(SubscribeDataRequest.CancelSubscription.newBuilder().build())
    .build());
requestObserver.onCompleted();

doneLatch.await(10, TimeUnit.SECONDS);   // wait for the response stream to terminate
```

Simply calling `onCompleted()` without the explicit cancel also ends the subscription — closing
the request stream is an implicit cancel.  Sending `CancelSubscription` first is cleaner because
it states the intent to the service before the transport closes.

`CancelSubscription` is an **empty** message, but it must still be explicitly set on the oneof.
An unset oneof carries neither payload and is not a cancel.  The identical pattern applies to
`SubscribeDataEventRequest.CancelSubscription`.

### Reconnecting

A `StreamObserver` is single-use.  Once `onError` or `onCompleted` has fired on the response
observer, the call is dead — you cannot reuse either observer.  Reconnect by creating a fresh
pair from a new stub call:

1. Keep the PV name list (or trigger list) in a field *outside* the stream, so re-subscribing is
   idempotent from the client's point of view.
2. Structure setup as a method that returns once the response observer terminates, latching on
   `doneLatch`.
3. On `onError`, back off, then call that method again to build a new observer pair and re-send
   `NewSubscription`.
4. **Backfill the gap if completeness matters.**  Nothing is buffered for you across the
   reconnect.  Record the last timestamp you saw before the failure and fetch
   `[lastSeen, resubscribedAt)` from `DpQueryService` — `queryData()` in 1.14, or `queryBuckets()`
   in 1.15 and later.

## Also worth knowing

- **Verifying the pipeline end to end.**  Open the subscription and wait for the ack *before* the
  producer starts ingesting; the subscriber sees only data received after registration.  Ingestion
  publishes to subscribers while also persisting to the archive, so delivery on the subscription
  is not by itself proof of persistence — check that separately with
  `DpIngestionService.queryRequestStatus()`, which is async and independent.
- **Do slow work off the callback thread.**  gRPC invokes `onNext` on a network thread; decoding,
  plotting, or writing to disk there blocks the stream and can cause flow-control backpressure or
  deadlock.  Enqueue and let an executor drain.
- **Package trap.**  `ingestion_stream.proto` declares proto package `dp.service.ingestionstream`
  and Java package `com.ospreydcs.dp.grpc.v1.ingestionstream` — no underscore, despite the file
  name.  (Its header comment also mistakenly reads "ingestion.proto"; that is cosmetic.)
- **Spelling traps.**  `pvNames`, `pvName`, `targetPvs`, `dataBuckets`, `subscribeDataResult`.
- The proto documents no limit on the number of PVs in a `NewSubscription`, no server-side
  rate limiting, and no delivery-ordering guarantee across PVs.  These are **unspecified** at the
  API level — consult your deployment rather than assuming.
