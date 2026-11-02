# Per-user metering for images' background work (#284)

Follow-up to #274 (PR #282). In `subject_mode = user`, web requests bill the
signed-in user, but images' work (storage holds, pipeline growth, AI steps)
still meters `default`, and boot warns about it
(`sm_billing/subject_boot.py`, `billing.subject_mode.tenant_billed_callers`).

## Goal and scope

In: every place images meters billing uses one **image subject**, in both
the web process and the Celery workers:
- the storage hold taken at upload or import;
- pipeline growth (`storage_hold.reserve`/`record`/`abandon`);
- settle, repair and release of those holds;
- the AI steps' `ai.requests` (`pipeline/ai/runner.py`, `group_run.py`);
- the web advisory checks (`billing.check`/`headroom` on upload).

Out:
- ai's own request-time quota is unchanged (`RequiresAiRequest` already bills
  the user).
- Moving old rows. The "rows do not move" rule from #274 stays.
- `tenant` mode, where nothing changes: the subject is the tenant, as today.

## Who pays: the collection's owner

In user mode an image's work bills **`user:<collection.owner_id>`**. This
needs a decision (question 1).

- **Why the owner.** `Collection.owner_id` exists for every image and every
  job, including code-started ones. One image always has one payer, so its
  storage hold can be swapped, grown and released under the same subject for
  its whole life. Sharing a collection does not move the bill: the owner pays
  for what others upload into it, as with a shared drive.
- **Rejected: whoever acted pays** (the uploader, or the `run_as` of an
  import, restart, regroup or prompt run). This is fairer for shared
  collections, but one image's hold would change hands between upload and
  later growth. A `swap` across subjects is refused by billing (`HoldNotFound`).
  Pipeline steps, group prompts and code-started jobs have no actor at all.
- **Rejected: carry the subject on every task payload.** Every enqueue site
  would change, and retries and reconcile re-dispatch would have to carry it
  too. Deriving it from the collection, plus recording it on the hold, needs
  neither.

## Design

1. **`sm_images.core.billing.subject`**: `image_subject(tenant, owner_id, mode) -> str`.
   - Tenant mode returns the tenant.
   - User mode returns `subject_for_user(owner_id)`, read through
     `sm_billing.contracts`, which is optional as today: no billing installed
     means no metering.
   - The mode comes from `subject_mode` on `app.state` in the web process and
     from `worker_subject_mode()` in workers. The latter is DB-backed and
     cached for about 30 s, so a worker follows a mode switch within about
     30 s of the restart.
   - **A malformed or missing owner** (an owner deleted while the collection
     stays): the image falls back to the tenant subject, `default`, and logs
     `images.billing.owner_unbillable` once per collection. This needs a
     decision (question 3).
2. **The subject is recorded on the hold, not re-derived.** New nullable
   `subject` column (max 64) on `images_billing_op` and on `images_image`
   (`storage_subject`):
   - Every op is written with the subject it bills.
   - Settle, repair, reconcile and the janitor replay each op with its
     recorded subject, never a fresh derivation.
   - An image's growth swaps under `Image.storage_subject`, the subject its
     current hold was taken under. A mode switch or an ownership change
     therefore never sends a swap to a subject that doesn't hold it.
   - `NULL`, for rows written before this change, means the row's
     `tenant_id`, which is what those holds were taken under. Existing holds
     keep settling and releasing exactly as before.
   - One host migration adds both columns (`host/migrations/versions/`,
     SQLite and Postgres, `alembic check`).
3. **Call sites** pass the subject instead of the tenant:
   - `slots.hold_slot` and `IngestService.reserve` derive it once from the
     collection when the hold is taken.
   - `storage_hold.reserve` uses `Image.storage_subject`, or the derived
     subject for a first hold.
   - `core/billing/settle.py`, `repair.py`, `install.py` and `ops.py` use
     `BillingOp.subject or tenant_id`.
   - The two `consume_requests` callers pass the image's subject. Metering
     keys keep their current form, which is already unique per image, step
     and attempt.
4. **Web advisory checks** (`api/images.py`, `api/uploads.py`,
   `ingest/admission.py`) check the collection owner's headroom, the same
   subject the hold will use. The uploader's own counter is irrelevant
   because they are not the one billed.
5. **Jobs with no originating user.**
   - `reconcile`, `janitor` and the purge only settle, repair, release or
     expire existing ops. They take no new quota, and they use each op's
     recorded subject.
   - `release` takes no subject at all.
   - Nothing new is billed to `default` in user mode, apart from the
     unbillable-owner fallback.
6. **Boot warning and docs.**
   - images and ai are removed from `_TENANT_BILLED`. images was the only
     worker caller of `consume_requests`, so the warning goes away entirely.
   - `subjects.md` replaces "Worker metering stays on the tenant" with
     "Images bills the collection's owner".
   - Update the #274 design's Decisions item 3 and the CLAUDE.md billing
     paragraph.

## Decisions made (override any at approval)

- The owner's subject is decided when the hold is taken and kept for that
  hold's life. A later ownership change affects only new holds.
- AI step charges follow the same payer as storage, so the AI cost of a
  shared collection lands on its owner.
- A pre-check against the owner's quota fails the upload with the existing
  `quota_exceeded` error. The message names the collection's storage, not the
  uploader's plan.
- No backfill of `subject` on existing rows: `NULL` already means "the
  tenant", which is correct for them.

## Testing

- **Unit:**
  - `image_subject` in both modes, including a malformed or missing owner.
  - The ingest hold, pipeline growth, settle, repair and AI step bill
    `user:<owner>` in user mode and the tenant in tenant mode. This needs a
    subject-aware `FakeGauge` in `images/tests/support/billing.py`.
- **Continuity:**
  - A hold taken in tenant mode, with a `NULL` subject, still grows, settles
    and is released after the switch to user mode, under `default`.
  - A user-mode hold stays under its user after an ownership change.
- **Worker path:**
  - A `run_step` under `worker_subject_mode() == "user"` meters the owner.
  - Reconcile and janitor replay with the recorded subject.
- **Boot:** `test_subject_mode_boot.py` no longer expects the warning.
- **Migration:** upgrade and downgrade on SQLite and Postgres;
  `check_migration_heads`.
- **e2e:** `billing-user` gains a case where a user uploads an image and sees
  storage usage on their own Billing page, not on `default`.

## Risks

- **Size.** Every billing call path in images changes. The change is
  mechanical but wide (about 15 files), so it is split into tasks per layer:
  subject helper and columns; ingest; pipeline and settle; AI; web checks;
  docs.
- **The 30 s worker lag** after a mode switch. Recording the subject on the
  hold makes the lag harmless to continuity. Only which payer a brand-new
  hold gets can lag.
- **The owner's quota blocks other uploaders** to a shared collection. This
  follows from question 1.
