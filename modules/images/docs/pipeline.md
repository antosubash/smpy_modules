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

## Group prompts

A group-scope prompt runs once per group (`POST /api/images/prompts/{id}/run`
with `group_ids`, or the whole collection). Its `inputs` say what it
summarises: the members' display copies (`images`), each member's result of
the image prompt named by `member_prompt_id` (`results`), or `both`. That
image prompt cannot be deleted while a group prompt reads it
(`prompt_in_use`).

- **The run.** The group's `images_prompt_result` row is the run record: a
  request marks it `pending` for one lease period (a lost message blocks
  nothing longer), a worker claims it with a lease token, and the store is
  fenced by that token, as for image steps.
- **Members.** A stored result is reused when it is completed, has content
  and was made under the member prompt's current revision. Each other member
  runs through the executor, at most 4 at a time, with exactly an image
  prompt run's claim, metering (`images:prompt`) and retry rules.
- **Privacy.** Every picture this run would send must be a display copy
  serving would trust: all members' with `images`/`both`, otherwise those of
  the members that need a call. If one is not, the whole run fails
  `display_not_ready` before anything is sent or charged. A member whose
  stored result is reused sends nothing and needs no safe copy. Originals
  are never sent. Whether a member needs a call is decided again under its
  image lock, so two group prompts over one image prompt call it once.
- **Recovery.** `images.reconcile` dispatches again a group run requested (by
  `requested_at`, which only entering `pending` sets - never `updated_at`)
  more than 5 minutes ago and never claimed, or claimed under an expired
  lease; the claim is fenced, so a duplicate is harmless.
- **The consolidation** is one provider request at temperature 0, claimed
  once per lease and metered once (`images:group_prompt`, key
  `images:{tenant}:group:{group}:prompt:{prompt}:{revision}:{lease token}`).
  Its output is validated against the prompt's schema. When some members
  have no usable result the summary is stored anyway, but the run is `failed`
  with `member_results_missing` naming them, so it is never mistaken for a
  complete verdict. Nothing usable at all fails `no_usable_inputs`, uncharged.
- **The cross-check.** A prompt applied from a preset carries its
  `preset_id`; that preset's `cross_check(group, results)` is called after
  the consolidation, with no session open. `group` is a `GroupRead` (members
  in role order); `results` are the usable member results in role order and
  then the group's own summary (`group_id` set). Its return value is stored
  in `cross_check` (the hook gets deep copies, so it cannot alter the stored
  summary); an exception, a non-dict, non-JSON or a value over
  `step_output_max_bytes` is stored as `{"error": "..."}` instead.

## Presets

`GET /api/images/presets` lists what installed plugins registered.
`POST /api/images/collections/{id}/apply-preset {"preset_id"}` (owner or
`images.manage`: it can switch `auto_run` on) seeds the collection and is
idempotent: each `PromptSpec` becomes one prompt, recognised by its spec id
(`Prompt.preset_prompt_id`, unique per collection), and a spec applied before
is left as edited. Pipeline steps the collection does not configure are
added; group roles are set only while the collection has none. A spec's name
already used by another prompt refuses the whole application with 409
`prompt_name_taken`. Prompt names are unique per collection in the database
too (`uq_images_prompt_name`). A `PromptSpec` of a group prompt over
`results` names its image spec in `member`, which may be left out when the
preset has exactly one image spec. `register_preset` runs every spec's schema
through `schema_safety` and refuses an unsafe one at boot.

## Storage metering

With `billing` installed, an image's stored bytes count against the
`images.storage_bytes` gauge (unit bytes; a plan's limit is the most an
organisation may store). Without it nothing is limited, and
`images_image.storage_bytes` (original + display copy + renditions) is kept
all the same.

- **One committed hold per image**, sized to `storage_bytes` and named by
  `storage_hold_id`. Ingest holds the original; a published display copy or
  rendition set takes a hold for the new total and then releases the old one;
  the janitor's purge releases it once the image is gone. Every hold is keyed
  by the attempt that took it (`images:{image}:storage:{nonce}`), so two
  concurrent completes of one upload never share a hold, and the loser
  releases only its own.
- **Refusals.** Upload, base64 upload, direct-upload complete and import start
  check the gauge first and answer 402 `quota_exceeded`. The check is
  advisory: a batch checks the sum of its files, duplicates included, so it
  can refuse a batch whose new images would have fit. A replayed complete of
  a finished upload answers its image before any check, and a complete whose
  hold is refused keeps the assembled upload, so it can be retried once
  there is room. An import item that
  does not fit fails `quota_exceeded`; a step whose new objects do not fit
  fails `quota_exceeded`, its objects deleted and the previous display copy
  kept.
- **Order.** Billing writes in its own short transactions, so a hold is
  reserved (`held`) before the caller's transaction writes - on SQLite it
  would otherwise wait on the caller's lock. A rollback leaves a `held` hold
  to lapse at billing's TTL; capacity is never leaked. Taking the new hold
  before releasing the old one means a regenerated image briefly needs room
  for both.
- **Durable settlement.** Committing the new hold and releasing the old one
  are rows in `images_billing_op`, written in the same transaction as the
  change they settle (the ingest insert, the fenced completion, the purge).
  They are attempted right after the commit; what fails stays pending with a
  backoff, and `images.reconcile` retries each tenant's due ops until billing
  confirms. Every op is claimed before it runs (a token with an expiry), so two
  settlers never run one twice. An image's release of its old hold waits until
  the op it follows is done and billing confirms the hold the image names now
  is committed. A new hold that lapsed before its commit becomes a `rehold`:
  a replacement for the image's current total is reserved under
  `rehold-{op}-{generation}`, recorded on the op, committed, and swapped onto
  the image only while the image still names the lapsed hold; a spent
  replacement is released and the generation moves on, so no key is reused.
  The janitor deletes done ops after `janitor_grace_days`, keeping any a
  pending op still waits for. A release that has to wait is pushed back 30
  seconds without counting as a failure, and due ops are taken oldest-due
  first, so waiting releases never starve the commits behind them. A
  replacement billing no longer knows counts as released.
- **Hold ownership.** Every hold images keeps has a row in `images_hold_ref`
  (`reserved`, `installed`, `orphan`, `releasing`, `released`). Installing a
  hold on an image is a compare-and-set `reserved|orphan → installed` in the
  same transaction as the image update; releasing one first wins
  `reserved|orphan → releasing`, and only the winner calls billing. A stalled
  settler releasing a replacement and a newer settler installing it can
  therefore never both win, and a hold an image names is never released.
  A release that finds the row `released` already counts as done, so a
  settler that died after the release committed resumes. A replacement that
  was committed but lost the install (a release won it first) gets a durable
  `release` op in the same transaction that moves the rehold to its next
  generation, so it is released even if the releaser that beat it died.
- **No release waits on quota.** A hold that was never installed (a spare
  replacement, a rolled-back completion, a duplicate at ingest) is released
  with no dependency at all. An old hold waits for the image's current hold
  only while that hold is `held` (its commit needs no room); once the
  current hold lapsed and its rehold was refused for quota, the old hold is
  released, so the room it holds lets the rehold through. The image is
  under-counted meanwhile, never deadlocked.
- **Freed room goes to the rehold first.** That under-count is a window: the
  gauge counts the image by no hold from the moment its old hold is released
  until its rehold installs. If anything else took the freed room, the rehold
  would be refused for good and the tenant would store the image for free.
  So every quota pre-check (upload, batch, base64, direct-upload complete,
  import start, each ingested original and each publication's reserve)
  counts the gauge **plus** the bytes of the tenant's under-counted images.
  An image is in doubt while its current hold has a pending `commit` or
  `rehold` op, and it counts as covered only when its hold ref is `installed`
  and billing confirms the hold: a commit's hold `committed` (or `held` and
  unexpired), a rehold's recorded replacement likewise. An expired, released
  or unknown hold, or a rehold with no replacement, is under-counted. At most
  50 holds are asked about per check (the rest count as under-counted). A new
  reservation fits only if `gauge + under-counted + new ≤ limit`; otherwise
  it is refused 402 `quota_exceeded` (a step fails `quota_exceeded`). A
  publication does not count its own image, whose new hold replaces the
  lapsed one, and a rehold does not count the term at all, since it is what
  restores the count. In a worker billing has no gauge-aware check, so the
  guard reserves a short-lived probe of `new + under-counted` and releases it
  at once; a tenant with nothing under-counted pays no extra billing call.
- **One reservation per tenant at a time.** When the tenant's plan limits
  `images.storage_bytes`, the guard and the reservation after it (ingest,
  direct complete, publication, rehold, import items) run under the lease
  `images:quota:{tenant}` (the framework's leases: Redis, else `sm_lease`),
  held for those two billing calls only, never across the caller's
  transaction. Two reservations can no longer both pass the probe before
  either reserves. Without billing, or without a limit, no lease is taken.
  A request that cannot get the lease within 10 s answers 503 `quota_busy`
  (a direct upload stays open to retry); a worker raises, and the step run or
  import item is handed out again by reconcile, a rehold by its backoff.
- **The reservation's deadline.** A publication reserves for the step lease
  plus five minutes (at least billing's 15-minute default): a completion is
  accepted only within its lease, so the hold outlives any completion that can
  still succeed. It is extended when within a minute of lapsing before the
  image lock is taken, and a lapsed one is refused under the lock (rolled
  back and planned again, like a lost fence).
- **Fail closed.** An installed billing that cannot meter raises: an upload
  fails, and a step fails `storage_error` without publishing.
