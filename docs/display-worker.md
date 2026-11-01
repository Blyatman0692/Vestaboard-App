# Display worker

Pipelines enqueue messages in Redis. The display worker processes them in FIFO
order through `DisplayManager`, which sets the transition and sends the content.
After API success, the worker atomically records display state and acknowledges
the message in Redis.

Run the worker alongside the web process and existing pipeline jobs:

```sh
python -m vestaboard.run_display_worker
```

The `Procfile` declares this as the `display` process. Enable that process when
deploying; starting only the web process will not consume queued messages.

The worker uses the existing `REDIS_URL` and `VB_RW_API_KEY` settings.
`DISPLAY_MIN_INTERVAL_S` defaults to `16` and must be a finite number of at least
`15`. It applies to every content-send attempt, including retries, and is measured
from completion of the previous attempt. Transition updates do not consume a
content slot, but are protected by the same worker lease.

Redis holds the shared cooldown and a renewable lease. The lease covers claiming
work, transition changes, retries, and acknowledgment. A second worker waits
without consuming messages while another worker owns the lease. The existing key
namespace supports one board per Redis database.

The cooldown survives worker restarts. Before a content request, the worker
reserves a cooldown lasting through the lease plus the minimum interval. On
completion (including a timeout), it resets that cooldown to the minimum interval.
An abrupt process exit during a request can therefore cause a longer pause before
the next send.

SIGTERM and SIGINT finish the current message, including any retry waits, then
stop before taking another message. Redis coordination failures stop the worker;
unfinished work remains available to the next worker.

## Delivery recovery

The worker atomically claims the oldest pending payload into a single in-flight
record. If a worker exits before acknowledgment, the next lease owner recovers
that record before newer messages. Claim, attempt, acknowledgment, and failure
operations verify ownership inside Redis, so an expired worker cannot change a
successor's delivery state.

The existing five-attempt HTTP budget applies separately to transition and content
requests. Counts are reserved before each request and survive worker restarts.
There are no additional queue-level retries after that budget is exhausted.
Permanent errors and malformed payloads are also retained as failures so they
cannot block the queue. A crash between reserving an attempt and sending can spend
an attempt without issuing the request.

Redis keys:

| Key | Contents |
| --- | --- |
| `vestaboard:queue:pending` | FIFO list of serialized message envelopes |
| `vestaboard:queue:inflight` | Claimed payload and persisted HTTP attempt counters |
| `vestaboard:queue:failed` | Retained payload, error, timestamp, message ID, source, and attempt counts |
| `vestaboard:display:current` | Last acknowledged display state, including message ID |

A successful acknowledgment updates display state and removes the in-flight
record atomically. Failures are appended to the failed list before the in-flight
record is removed; processing then continues. Failed records are retained for
inspection and are not automatically replayed. Logs identify claims, recoveries,
HTTP attempts, queue delay, successes, and failures.

If the board accepts a request but the response or acknowledgment is lost, recovery
can resend the same content. Exactly-once physical display is not guaranteed.
Recovery also depends on Redis retaining its data; configure Redis persistence
for the durability required by the deployment.

## Flight deduplication

New flight envelopes carry an optional `flight_id`. Enqueue atomically checks for
a pending or successfully sent flight and registers the pending message ID.
Pending markers have no timeout, so a long backlog or worker crash does not allow
duplicate flights to accumulate.

Acknowledgment clears the pending marker and marks the flight as successfully
sent for one hour. Final failure clears the pending marker without marking it
sent, allowing the next flight poll to queue it again.

## Deployment and tests

Stop all stage 1 display workers before starting the updated worker: the old
consumer destructively pops from the same pending list and cannot provide recovery.
Restart producers on the updated code to enable flight delivery tracking. Existing
version 1 payloads remain readable; older flight messages without `flight_id`
retain their previous deduplication behavior until the existing seen marker expires.

Install test dependencies with `python -m pip install -r requirements-dev.txt`,
then run `python -m unittest discover -s tests -q`. Worker tests use controlled
time, fakeredis with Lua support, and simulated HTTP responses. They execute the
queue scripts and redis-py lease operations without connecting to a board or
production Redis. Priority, expiration, and replacement policies remain later work.
