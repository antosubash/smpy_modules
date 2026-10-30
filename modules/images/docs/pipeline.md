# Processing pipeline

Everything derived from an image is a **step run**: one row per
`(image, step)` in `images_step_run`, with a status, an attempt count, an error
code, the step's version and a JSON `output`. A step is a registered class; no
step needs a table of its own, so a plugin's step needs no migration. The
original is never written: only `StepContext.write_display`, under a valid
lease, produces a display copy.

## Steps

| Step | Extra | Queue | Does |
| --- | --- | --- | --- |
| `exif` | core | `images` | Camera make and model, orientation, capture time (only when it has a time zone and none is set) and GPS location. A location never overrides a manual or imported one (`manual` > `import` > `exif`); an exact (0, 0) fix means no location. Reads HEIC through `pillow-heif` |
| `renditions` | core | `images` | One JPEG (quality 85, never enlarged) per `thumbnail_sizes` entry, cut from the display copy, all sizes or none. Runs again after a step publishes a new display copy |
| `quality` | `quality` | `images_heavy` | Resolution, Laplacian blur and exposure of the **original**. Params: `min_width` 640, `min_height` 480, `blur_threshold` 100, `dark_threshold` 0.05, `bright_threshold` 0.95. Informational: a failing photo is still a completed run |
| `anonymize` | `anonymize` | `images_gpu` | Blurs faces and number plates into a display copy; reads the original every time. Params: `faces` and `plates` (both on), `padding` 0.15, `min_confidence` 0.5. Output lists the regions (editors only) and counts. Nothing found completes with no display copy |
| `classify` | `ai` | `images_heavy` | Labels from a vision model, below |
| `prompt:<id>` | `ai` | `images_heavy` | One image-scope prompt, below |

A plugin step uses the id form `<plugin>.<name>`; the ids above, and every
`prompt:` id, are reserved ([writing-a-plugin.md](writing-a-plugin.md)).

## A collection's configuration

`pipeline_config` is `{"steps": {id: {"enabled": bool, ...params}}}`: a step
runs unless `enabled` is `false`, and the rest of its object is its params,
validated by the step's `params_schema()`. A new collection enables `exif` and
`renditions`. `PUT /api/images/collections/{id}/pipeline` (owner or
`images.manage`) validates strictly and refuses invalid params, a bad shape, more
than one enabled display mutator, a dependency that is off or unregistered, a
cycle, and a display mutator enabled beside an uninstalled step (422
`invalid_pipeline_config`). **A save stores the configuration only**; the console
then offers a restart. An id with no installed implementation is kept, as
`not_installed`, so removing a plugin never rewrites a collection.

Order comes from `requires`. Besides what a step declares, `renditions` and
every step with `sends_display_out` (`classify`, `prompt:*`, a plugin's that
opts in) are ordered after the enabled display mutator, because thumbnails are
cut from the display copy and those steps send it out of the system.

## Status rules

- `completed` and an ordinary `skipped` (the step's own "does not apply") are
  final for that `step_version`. Automatic dispatch never re-runs them.
- A `failed` step does not block independent steps. Its dependants settle as
  `skipped` with `dependency_failed`, a **blocked** skip that satisfies nothing
  downstream and is reset by a retry together with the failure.
- Bumping a step's `version` makes completed runs **stale**: they stay shown and
  are re-run by the stale restart or `force`.
- A dependency the collection does not enable settles the dependant as
  `dependency_unavailable`.

`POST /api/images/collections/{id}/pipeline/restart` (owner or `images.manage`)
takes `scope`: `failed` (retry), `stale` or `all` (force). It is a durable record
(`images_pipeline_restart`) walked in keyset chunks of 1 000, so a lost message
or a dead worker is finished by `images.reconcile`.
`POST /api/images/images/{id}/reprocess` re-runs one image for anyone who may
edit; its `force` option needs the owner or `images.manage`.

## Leases, delivery and recovery

A worker claims a step run with a **lease token** (`step_lease_seconds`, default
30 minutes), and every write it makes (the result, the display copy, the stored
bytes) is fenced by that token, so a slow worker whose lease was reclaimed cannot
overwrite a newer result or publish a display copy. A step calls
`await ctx.progress(pct)` to renew the lease and tell the task sweep it is alive.

Delivery is at-most-once (`enqueue_after_commit`), so `images.reconcile` runs
every 5 minutes, and once when a worker comes up, and re-dispatches per tenant:
step runs that are `pending` or have an expired lease and are older than 5
minutes, pending import items, import jobs and regroup jobs whose heartbeat is
stale, and requested group prompt runs. [worker.md](worker.md) has the recovery
times this implies. `images.janitor` runs daily and purges what is past
`janitor_grace_days`: trashed images and collections with their objects,
abandoned uploads, staged import sources, unreferenced objects recorded as
write-ahead intents, and settled storage-billing ops.

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
because eager mode is for tests and dev hosts only. In broker mode a step that hangs is killed only if you set Celery time limits
(`task_soft_time_limit`, `task_time_limit`; see [worker.md](worker.md)); an
abandoned run's lease expires and is reclaimed by `images.reconcile`.

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

### Known limits of AI steps

- A worker that dies after claiming a run (`ai_started_at`) and before the
  provider answers is charged again when the run is re-dispatched under a new
  lease: at most one extra charge per lease.
- A provider error is not refunded; the request was already charged.
- `classify` does not keep its previous labels when a later run fails (a prompt
  result does: a failed run keeps the previous output).

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

## Reviewing results

Prompt results (image and group scope) can be checked by a person. The queue is
`GET /api/images/collections/{id}/review?status=&prompt=&limit=&after=`
(`status` is `unreviewed` by default, or `accepted`, `corrected`, `rejected`,
`all`), and the console shows it at `/admin/images/{id}/review`. Reviewing is an
`edit` on the collection; a viewer is refused.

`POST /api/images/prompt-results/{id}/review` takes `{action, data, version}`:

- `accept` makes the model output the reviewed value.
- `correct` replaces it with `data`, validated against the prompt's
  `output_schema` (422 `invalid_review_data`); a free-text prompt is corrected
  with `{"text": "..."}`. The console generates the form from the schema.
- `reject` keeps no reviewed value.

`version` is the row's `version` as the reviewer saw it. A re-run (or another
reviewer) that changed the output, its prompt revision or its review meanwhile
makes the call a **409 `review_stale`**, and the client reloads. A result whose
prompt was edited since is flagged `stale` in the queue.

A review, and a re-run, move the previous reviewed value into `history`, newest
first, **keeping the last 5**; a re-run also resets the review to `unreviewed`.
`PromptResultReviewed` is published after commit.

Keyboard path in the queue: `j` next, `k` previous, `a` accept, `r` reject, `e`
correct, `Escape` leaves the correction form. Keys are ignored while typing and
with Ctrl, Alt or Meta held.

## Storage metering

With `billing` installed, an image's stored bytes count against the
`images.storage_bytes` gauge (unit bytes; a plan's limit is the most an
organisation may store). Without it nothing is limited, and
`images_image.storage_bytes` (original + display copy + renditions) is kept
all the same.

- **One committed hold per image**, sized to `storage_bytes` and named by
  `storage_hold_id`. Every hold comes from billing's atomic `swap`: the new
  hold is committed and the image's old hold released in one billing
  transaction, and the quota is checked on the net delta (new less old). No
  images hold is ever `held`, so none can lapse; replacing an image's hold
  never counts it twice or by nothing. The janitor's purge releases the hold
  once the image is gone.
- **Ingest** swaps from no hold (a plain reserve and commit) under a key of
  its attempt (`images:{image}:storage:0-{nonce}`), before the insert: two
  concurrent completes of one upload never share a hold. The insert marks the
  `ingest` op done with the row; a duplicate or a failed insert hands the op
  to the settler, which releases the hold.
- **A publication that grows the image** swaps before it publishes: a `swap`
  op is written under the image's lock (only when no other swap of the image
  is pending; one is settled first, else the step runs again later), then
  billing swaps. Refused: the old hold still counts, the step fails
  `quota_exceeded`, its objects are deleted and the previous display copy is
  kept. Granted: the fenced completion writes the new hold onto the image and
  finishes the op in one transaction. A completion that keeps nothing hands
  the op to the settler, which installs the swapped hold and queues a swap
  back down to what the image stores - a shrink, which billing never
  refuses.
- **A publication that shrinks the image** (or keeps its size) asks nothing
  of billing first: the completion queues the swap with its writes, and it
  runs after the commit.
- **Refusals.** Upload, base64 upload, direct-upload complete and import start
  check the gauge first and answer 402 `quota_exceeded`. The check is
  advisory: a batch checks the sum of its files, duplicates included, so it
  can refuse a batch whose new images would have fit; the swap is the
  enforcement, atomic in billing. A replayed complete of a finished upload
  answers its image before any check, and a complete whose hold is refused
  keeps the assembled upload, so it can be retried once there is room. An
  import item that does not fit fails `quota_exceeded`.
- **Durable settlement.** Every billing call is driven by a row in
  `images_billing_op` (`ingest`, `swap` or `release`), written before the
  call or in the transaction of the change it settles, and attempted right
  after; what fails stays pending with a backoff, and `images.reconcile`
  retries each tenant's due ops. Every op is claimed before it runs (a token
  with an expiry), and only its claimant may finish it, so an executor that
  stalls past its claim cannot also install what a settler installed. An
  image's swaps run one at a time, oldest first. Each op has one key and one
  old hold, fixed before billing first hears of it, and every retry repeats
  both. Billing commits exactly one outcome per key - the hold, a refusal,
  an expiry or a closure - in the transaction that claimed the key, so a
  retry, or a call delayed past its claim, gets the same answer and never
  changes anything twice.
- **Deadlines, on the database's clock.** Every op carries `not_after`: the
  database's time when the op was written, plus 7 days
  (`BILLING_OP_MAX_AGE`). It never changes, and every billing call for the
  op passes it unchanged (billing treats another deadline as another call:
  `IdempotencyConflict`). Billing admits a call only after claiming its key,
  by its database's clock (`clock_timestamp()` on Postgres): a call admitted
  past the deadline is `Expired`, nothing written, kept under the key. So no
  code path - an executor paused for a month between its check and its
  write, a settler, the repair - can change a hold after the deadline, even
  once billing's retention has purged the key's earlier outcome (it keeps a
  settled outcome 30 days, and at least a day past its `not_after`). No
  worker's clock decides what billing admits.
- **Nothing finishes an op without billing's answer.** An op ends with the
  outcome billing gave its key: the swap's own (a hold, a refusal, an
  expiry), or - wherever images would finish it without one - `close_key`'s.
  `close_key` returns the key's outcome if it has one (waiting for a swap
  still in flight under it) and otherwise commits `Closed`, after which every
  call under the key answers `Closed` and writes nothing. The settler calls
  it before finishing an op past its deadline (`op_expired`; deciding that
  by its own clock is safe, since closing early only refuses a late call),
  and the repair calls it for an op expired with its outcome unknown. A hold
  it returns is recorded on the op before anything else; if billing cannot
  answer, the op stays unfinished and is retried. A `release` op is finished
  only once billing has answered that the hold no longer counts (released
  now, settled already, or unknown to it); it has no deadline.
- **The repair** (`images.reconcile`, after the settler) examines every done
  `swap` and `ingest` op once, whatever it ended with, and declares an image
  correct only when it names a committed hold of exactly its
  `storage_bytes` and nothing else of the op's still counts. Otherwise: an
  op's committed hold the image does not name is installed where the image's
  own no longer counts, else released; and an image counted by nothing, or
  by a hold of the wrong size (a refusal, an expired shrink that left an
  oversized hold), gets a swap to `storage_bytes` queued. If that swap is
  refused too, its op is examined on the next lap, so the image is tried
  again until it is counted right. Every such decision - the repair's, and
  a settler's "the image moved on" - is taken under the image's row lock,
  re-reading what it names and stores and its unfinished ops, and a release
  is recorded there as a `release` op. The scan walks bounded laps: a lap
  covers each tenant's done ops up to the highest op id when it began
  (`images_billing_cursor.lap_end`), 200 per tick, so it ends however fast
  new ops arrive, and the next lap revisits whatever was deferred; the cursor
  moves only by compare-and-set. The janitor deletes done ops after
  `janitor_grace_days` once the repair has examined them.
- **Recovery bound.** A healthy op settles in the settle pass after its
  commit. A crashed one is taken over once its claim expires (5 minutes for
  a publication, 30 for an ingest) and settled by the next reconcile tick
  (5 minutes). An op that cannot reach billing at all settles at its
  deadline (7 days) once `close_key` answers; the repair then reaches its
  image within one lap of the tenant's backlog (200 ops a tick). Until then
  the image is counted by its old hold, or by the new one, never by both for
  longer than that lap. While billing refuses the correcting swap (the
  tenant is full), the image is retried once a lap.
- **A lowered plan limit evicts nothing.** Stored images keep their holds; a
  swap that does not grow an image is always admitted, one that grows it is
  refused until the tenant is under the limit again.
- **Fail closed.** An installed billing that cannot meter raises: an upload
  fails, and a step fails `storage_error` without publishing.
- **Over-count after a crashed ingest.** An ingest killed after billing
  committed its hold, and before the insert marked the op done, leaves the
  tenant over-counted by that one original until the op's 30-minute ingest claim
  expires and the next reconcile tick settles it: 30 to 35 minutes (33 were
  observed in the real-worker check, see [worker.md](worker.md)). Near a plan
  limit that window can refuse an upload that would otherwise fit. The orphan
  object is reaped by the janitor after `janitor_grace_days`, and billing never
  counts it.
- **A crash at the exact step while billing is unreachable for the whole 7-day
  deadline** can leave one committed hold nobody references; an administrator
  releases it in billing.
- **If billing is uninstalled later**, done `swap` and `ingest` ops the repair
  has not yet examined are never swept (the repair only runs with billing), so
  they stay in `images_billing_op`. That is a few rows per stored image, nothing
  more; images keeps recording `storage_bytes` as before.
