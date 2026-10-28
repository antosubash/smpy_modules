# Processing pipeline

This page is a stub. The full pipeline guide (steps, presets, leases,
reconcile, extensions) arrives with the module's documentation pass.

## Eager mode

With `task_always_eager` on (tests, a dev host without a broker), nothing goes
through Celery. `submit` runs the pipeline on the calling event loop, then
waits for the durable deliveries the work published, so `ImageProcessed`
subscribers have finished before the caller returns.

That wait is **bounded** by `sm_images.pipeline.eager_drain.EAGER_DRAIN_TIMEOUT`
(5 s). The bound exists for one case the module cannot detect: a durable
handler that spawns a task (`asyncio.create_task`) which submits images work
and is then awaited by the handler. The new task does not carry the handler's
call stack, so its submit waits on the transport's deliveries, including the
parent delivery that is waiting on it. When the bound expires, images logs an
`images.pipeline.eager_drain_timeout` warning and stops waiting. The
deliveries are not cancelled and finish on their own. A deadlock becomes a
delay of at most 5 s.

Only the *wait* is bounded, never the image work. Image work a handler had
already queued on the drain before the bound expired still runs before
`submit` returns; after a timeout, `submit` just does not wait again for the
deliveries that work publishes. Work a still-running delivery submits after
`submit` has returned starts a drain of its own.

Eager mode has **no overall deadline** for a step that never terminates: the
drain runs every queued item to the end on the calling loop. That is accepted,
because eager mode is for tests and dev hosts only. In broker mode each
`images.run_step` task runs under Celery's soft time limit, and an abandoned
run's lease expires and is reclaimed by `images.reconcile`.

Two cases need no bound and return at once:

- submits made directly from a durable handler, which images detects from the
  call path;
- submits from tasks spawned while images code runs inside a delivery, which
  inherit a context variable.

Broker mode (a real Celery worker) never waits on the transport, and the bound
does not apply there.
