# Processing pipeline

This page is a stub. The full pipeline guide (steps, presets, leases,
reconcile, extensions) arrives with the module's documentation pass.

## Eager mode

With `task_always_eager` on (tests, a dev host without a broker), nothing goes
through Celery. `submit` runs the pipeline on the calling event loop, then
waits for the durable deliveries the work published, so `ImageProcessed`
subscribers have finished before the caller returns.

That wait is **bounded** by `sm_images.pipeline.orchestrate.EAGER_DRAIN_TIMEOUT`
(5 s). The bound exists for one case the module cannot detect: a durable
handler that spawns a task (`asyncio.create_task`) which submits images work
and is then awaited by the handler. The new task does not carry the handler's
call stack, so its submit waits on the transport's deliveries, including the
parent delivery that is waiting on it. When the bound expires, images logs an
`images.pipeline.eager_drain_timeout` warning and returns. The deliveries are
not cancelled and finish on their own. A deadlock becomes a delay of at most
5 s.

Two cases need no bound and return at once:

- submits made directly from a durable handler, which images detects from the
  call path;
- submits from tasks spawned while images code runs inside a delivery, which
  inherit a context variable.

Broker mode (a real Celery worker) never waits on the transport, and the bound
does not apply there.
