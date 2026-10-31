# Display worker

Pipelines enqueue messages in Redis. The display worker processes them in FIFO
order through `DisplayManager`, which sets the transition, sends the content,
and records the new display state after a successful API response.

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

Redis holds the shared cooldown and a renewable lease. The lease covers dequeue,
transition changes, retries, and recording the result. A second worker waits
without consuming messages while another worker owns the lease. The existing key
namespace supports one board per Redis database.

The cooldown survives worker restarts. Before a content request, the worker
reserves a cooldown lasting through the lease plus the minimum interval. On
completion (including a timeout), it resets that cooldown to the minimum interval.
An abrupt process exit during a request can therefore cause a longer pause before
the next send.

SIGTERM and SIGINT finish the current message, including any retry waits, then
stop before taking another message. Exhausted HTTP retries are logged with the
message ID, and processing continues. Redis coordination failures stop the worker
because it cannot safely send without ownership and shared timing.

Stage 1 uses destructive dequeue. A process crash or final send failure can lose
the current message. In-flight recovery, acknowledgment, priority, expiration,
and replacement policies belong to later stages.

Run the tests with `python -m unittest discover -s tests -q`. Worker tests use
controlled time and simulated Redis/HTTP responses; they do not send to a board.
