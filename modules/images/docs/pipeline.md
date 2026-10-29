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

## AI steps: `classify` and prompts

Both need the `[ai]` extra (the `ai` module and Pydantic AI). Without it,
`classify` is not registered and no prompt resolves, so their runs settle as
`not_installed` and the prompt run route answers 503 `ai_unavailable`.

- **`classify`** sends the display copy, scaled to `max_side` (default 1024)
  and re-encoded without metadata, to `sm_ai.contracts.resolve_model()`. Its
  params are `vocabulary` (empty means free labels), `instruction` (a neutral
  default) and `max_side`. The output is `{"labels": [{"label", "confidence"}],
  "model"}`.
- **`prompt:<id>`** runs one image-scope prompt on one image. These steps are
  resolved from the database on every execution; the registry never holds
  them. The step's version is the prompt's `revision`, which an edit to the
  instruction or the schema bumps, so older results become stale. The result
  goes to `images_prompt_result`. A re-run resets the review to `unreviewed`
  and keeps the last 5 reviewed values in `history`. A failed run keeps the
  previous output.
- A prompt runs on every image when the collection's config enables
  `prompt:<id>`. It runs on demand when a run is *requested*: `auto_run`
  prompts on each new image (uploads always; imports too, unless the import
  opts out with `auto_run_prompts: false`), and
  `POST /api/images/prompts/{id}/run` (`missing`, `stale` or `all`,
  optionally limited to `image_ids`). A requested run whose prompt is gone
  settles as `not_installed`.
- **Who may spend.** An edit share may run a prompt on named `image_ids`
  with `missing` or `stale`. A run over the whole collection, a run with
  `all`, and switching `auto_run` on are the owner's or `images.manage`'s.
- **Privacy.** A step that declares `sends_display_out = True` (`classify`,
  every prompt step, and any plugin step that opts in) is ordered after the
  display mutator, as renditions are. When the display copy is one serving
  would not trust, the executor fails the run `display_not_ready` without
  invoking the step at all, so it never reads those bytes.
  The original is never sent.
- **Metering.** Each call charges one `ai.requests` through
  `sm_ai.contracts.consume_requests`, keyed
  `images:{tenant}:{image}:{step}:{version}:{lease token}`. Before the call,
  the run claims `step_run.ai_started_at` once per lease, so a redelivered
  message for the same lease neither calls the provider nor pays again.
  Pydantic AI's output retries and the provider SDK's transport retries
  (`resolve_model(max_retries=0)`) are off: one charge is at most one
  provider request, and a reply that does not fit fails `invalid_output`. A refusal fails the
  step with `quota_exceeded`, and nothing retries it automatically. A stored
  prompt result (output, metadata and review history) is held to
  `step_output_max_bytes` by dropping the oldest history first; an output
  that cannot fit on its own fails `output_too_large` and keeps the previous
  result.
- **Output schemas** are user input. `schema_safety.check` caps size, depth
  (as written and through references), properties, `$ref` count and pattern
  length. It allows only local `$ref` with no sibling keywords, keeping
  `$defs` and `definitions` apart, and refuses what the model would not
  enforce (`format`, `allOf`, unknown keywords, `required` names that are
  not properties) as `unsupported_schema`. An optional property may be
  omitted but is null only where its type allows it, and unlisted properties
  are kept unless `additionalProperties` is `false`. The check runs on save
  and again before every run; it builds the pydantic model once, cached per
  prompt id and revision.
