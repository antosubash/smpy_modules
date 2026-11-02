# Worker Billing Subject (#284) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** In billing `subject_mode = user`, every images meter call (storage holds, pipeline growth, settle/repair, AI steps, web pre-checks) bills `user:<collection.owner_id>` instead of `default`, in the web process and in Celery workers, without disturbing holds taken before the switch.

**Architecture:** One helper module, `sm_images.core.billing.subject`, turns `(tenant, collection owner, mode)` into a billing subject. The mode comes from a new `Runtime.subject_mode` callable: `app.state` in the web process, `worker_subject_mode()` in a worker. Every op row and every image records the subject its hold was taken under (`images_billing_op.subject`, `images_image.storage_subject`, nullable, where `NULL` means the row's `tenant_id`). Settle, repair, install and growth replay that recorded subject and never derive it again. Only a brand-new hold or an AI charge derives one.

**Tech Stack:** Python 3.14, SQLModel/SQLAlchemy async, Alembic (host), pytest + pytest-asyncio, Playwright (e2e).

**Spec:** `docs/superpowers/specs/2026-11-02-worker-billing-subject-design.md` (approved). Answers given at approval: (1) the collection owner pays; (2) old holds stay on `default`, and the subject is recorded per hold in new nullable columns where `NULL` means the row's `tenant_id`; (3) an unbillable owner (missing, deleted or not a UUID) falls back to the tenant subject with a one-time `images.billing.owner_unbillable` log per collection.

Paths below are relative to the worktree root
`/home/anto/Repos/smpy_modules/.claude/worktrees/issue-284-worker-subject` (WORKTREE).
`IMG` = `modules/images/sm_images`, `IMGT` = `modules/images/tests`, `BIL` = `modules/billing/sm_billing`, `BILT` = `modules/billing/tests`.

## Global Constraints

- Migrations go only in `host/migrations/versions/`, and the history must still end in exactly one head (`python scripts/check_migration_heads.py`). The current head is `a7c2e4d81b35`.
- Files have a hard cap of 300 lines, and 280 or more triggers a warning (`scripts/check_file_size.py`). When a touched file reaches 280, split it by responsibility. Trimming comments to fit does not count. Watch `IMG/ingest/service.py` (276 lines now), `IMG/core/billing/ops.py` (267) and `IMG/ingest/imports/settle.py` (279, which this plan does not touch).
- Images reads no environment variables. Workers read settings through `background_tasks.settings_for`, and the billing mode through `sm_billing.contracts.worker_subject_mode()`.
- Billing stays optional for images. When `billing_installed()` is false, the mode is `"tenant"`, nothing meters, and `sm_billing` is never imported. Every `sm_billing` import inside images is lazy, behind that check.
- Published modules use range pins only. The images `billing` extra floor stays `>=0.0.14`; only its `# floor:` comment changes (Task 1).
- Subject strings are at most 64 characters (`user:<uuid>` is 41). Build user subjects only with `subject_for_user`, never by hand.
- Billing semantics this plan relies on:
  - `UsageMeter.swap` raises `HoldNotFound` when the old hold belongs to another subject.
  - `get_hold(subject, id)` returns `None` for another subject's hold.
  - `close_key(subject, meter, key)` is scoped to its subject.

  So every call on an existing key or hold must name the subject the hold or key was created under.
- In tenant mode, behaviour is byte-for-byte unchanged: the subject equals the tenant, and no extra queries run.
- Shell rules for every executor: one plain command per Bash call, literal absolute paths, `git -C WORKTREE`, no `$(…)`, no `cd X && git`. Use `/usr/bin/ps`. Run targeted test files only, never a full suite, and start no servers (the e2e in Task 10 is the exception and follows the headroom rule there).

## Review Focus

1. **A queued swap that settles after the image's hold changed subject.** A shrink is queued under subject S, and before it runs, an earlier op installs a hold under S′. Expected: the swap names the hold the image names now, under that hold's subject. It must not raise `HoldNotFound` forever and back off. Pinned by `test_queued_swap_fixes_subject_with_old_hold` (Task 4).
2. **`close_key` and `get_hold` under the wrong subject.** If the repair or the expiry asks under `tenant` for a key or hold made under `user:X`, billing answers `Closed` or `None`, while the real swap may still write or the image looks uncounted, and the repair would queue a second hold. Expected: both ask under the op's subject for its key and hold, and under the image's `storage_subject` for the hold the image names. Pinned by `test_repair_reads_holds_under_their_subjects` and `test_expired_user_op_closes_key_under_its_subject` (Task 4).
3. **A collection owned by a user who was deleted (hard-deleted `users_user` row), or whose `owner_id` is not a UUID.** Expected: the tenant subject, one `images.billing.owner_unbillable` warning per collection per process, and the upload still works. Pinned in Task 2 (`test_owner_subject_*`) and in Task 5 (`test_upload_to_unbillable_owner_bills_tenant`).
4. **A shared collection: a non-owner uploads while the owner's quota is full.** Expected: a 402 `quota_exceeded`, because the pre-check reads the owner's headroom and not the uploader's. Pinned by `test_shared_uploader_is_checked_against_owner_quota` (Task 8).
5. **A worker with billing installed but its settings read failing**, for example while the database is down. Expected: the step fails and is retried. It must not fall back to `default`. `worker_mode()` propagates the error, pinned by `test_worker_mode_propagates_settings_errors` (Task 2).

---

## File map

| File | Change | Responsibility |
|---|---|---|
| `BIL/contracts/__init__.py` | modify | export `subject_exists(db, subject)` (lazy) |
| `IMG/core/billing/subject.py` | **create** | mode lookup and subject derivation, plus the unbillable fallback and its log |
| `IMG/pipeline/runtime.py` | modify | `Runtime.subject_mode` + `billing_mode()` |
| `IMG/module.py`, `IMG/pipeline/worker_runtime.py` | modify | wire `subject_mode` in web and worker |
| `IMG/models/billing_op.py`, `IMG/models/image.py` | modify | `BillingOp.subject`, `Image.storage_subject` |
| `host/migrations/versions/c4e9b2a7d613_images_billing_subject.py` | **create** | add both columns |
| `IMG/core/billing/__init__.py` | modify | rename the `tenant` param to `subject` in `check`/`headroom`/`swap`/`close_key` (docs and names only) |
| `IMG/core/billing/ops.py`, `settle.py`, `install.py`, `repair.py` | modify | write and replay the recorded subject |
| `IMG/ingest/slots.py`, `IMG/ingest/service.py` | modify | the ingest hold bills the owner |
| `IMG/pipeline/load.py`, `storage_hold.py`, `executor.py` | modify | growth bills the image's recorded subject, or the owner's for a first hold |
| `IMG/pipeline/ai/runner.py`, `group_load.py`, `group_run.py` | modify | `consume_requests` bills the owner |
| `IMG/web/endpoints/api/images.py`, `uploads.py`, `imports.py`, `IMG/ingest/admission.py` | modify | pre-checks read the owner's headroom |
| `BIL/subject_boot.py`, `BILT/test_subject_mode_boot.py` | modify | drop the tenant-billed warning |
| `modules/billing/docs/subjects.md`, `modules/images/docs/pipeline.md`, `docs/superpowers/specs/2026-11-01-billing-subject-design.md`, `CLAUDE.md`, `modules/images/pyproject.toml` | modify | docs and the floor comment |
| `IMGT/support/billing.py` | modify | `FakeGauge` levels per subject; `user_mode` fixture |
| `tests/e2e/billing-user.spec.ts` | modify | an upload shows on the user's own Billing page |

## Task order, kind and overlap

| # | Task | Kind | Depends on | Files disjoint from |
|---|---|---|---|---|
| 1 | billing `subject_exists` contract + floor comment | routine | — | everything in images; can run in parallel with 3 and 9 |
| 2 | images subject helper + Runtime wiring | routine | 1 | 3 |
| 3 | columns + host migration | routine | — | 1, 2, 9 |
| 4 | op layer: ops/settle/install/repair replay the subject | **hard** (cross-cutting) | 2, 3 | 7, 8, 9 |
| 5 | ingest hold bills the owner | routine | 4 | 6, 7, 8, 9 |
| 6 | pipeline growth bills the recorded subject | **hard** | 4 | 5, 8, 9 |
| 7 | AI steps bill the owner | routine | 6 (`Loaded.subject`, `Staging.subject`) | 5, 8, 9 |
| 8 | web advisory checks read the owner's headroom | routine | 2 | 5, 6, 7, 9 |
| 9 | boot warning + docs + CLAUDE.md | routine | — (docs text assumes the design) | all images code |
| 10 | e2e `billing-user` upload case | routine | 1–8 | — |

Tasks run sequentially in this order. 1, 3 and 9 touch disjoint files, as do 7 and 8, if a reviewer gate allows overlap.

---

### Task 1: billing contract `subject_exists`

**Files:**
- Modify: `BIL/contracts/__init__.py` (add the function and its `__all__` entry)
- Modify: `modules/images/pyproject.toml` (the `# floor: 0.0.14` comment above `billing = [...]`)
- Test: `BILT/test_contracts_worker.py`

**Interfaces:**
- Produces: `async def subject_exists(db: Any, subject: str) -> bool`. It delegates lazily to `sm_billing.subjects.exists`, for the same reason `subject_for_request` imports lazily. It returns `True` for `"default"`, `True` for an existing user's `user:<uuid>`, and `False` for an unknown user or a non-canonical spelling.

- [ ] **Step 1: Write the failing tests** in `BILT/test_contracts_worker.py`, using the existing `user_mode_app`/`app` fixtures from `BILT/conftest.py`:

```python
async def test_subject_exists_knows_users_and_default(user_mode_app):
    async with user_mode_app.state.sm.db.session_factory() as db:
        user = User(id=uuid.uuid4(), email="owner@x.io", hashed_password="x")  # as tests/helpers.py
        db.add(user)
        await db.flush()
        assert await contracts.subject_exists(db, contracts.subject_for_user(user.id)) is True
        assert await contracts.subject_exists(db, contracts.subject_for_user(uuid.uuid4())) is False
        assert await contracts.subject_exists(db, "default") is True
        assert "subject_exists" in contracts.__all__
```

- [ ] **Step 2:** Run `uv run --directory /home/anto/Repos/smpy_modules/.claude/worktrees/issue-284-worker-subject/modules/billing pytest -q tests/test_contracts_worker.py`. Expected: FAIL (`AttributeError: subject_exists`).
- [ ] **Step 3:** Implement it. Then, in `modules/images/pyproject.toml`, extend the billing floor comment so it also names `sm_billing.contracts.subject_for_user`, `worker_subject_mode`, `current_subject_mode` and `subject_exists` (#274/#284), which also first ship in 0.0.14. The specifier stays `>=0.0.14,<0.1`.
- [ ] **Step 4:** Re-run the Step 2 command (PASS), then run `uv run --directory WORKTREE python scripts/check_rules.py` (PASS).
- [ ] **Step 5:** Commit with `git -C WORKTREE commit -m "billing: subject_exists contract (#284)"`.

### Task 2: images subject helper and runtime mode

**Files:**
- Create: `IMG/core/billing/subject.py`
- Modify: `IMG/pipeline/runtime.py` (`Runtime`), `IMG/module.py` (`_use_runtime`), `IMG/pipeline/worker_runtime.py` (`worker_runtime`)
- Modify: `IMGT/support/billing.py` (add a `user_mode` fixture and a subject-aware `FakeGauge`)
- Test: `IMGT/core/billing/test_billing_subject.py` (new)

**Interfaces:**
- Consumes: `sm_billing.contracts.{subject_for_user, current_subject_mode, worker_subject_mode, subject_exists}` (Task 1).
- Produces, in `sm_images.core.billing.subject`:
  - `TENANT: Final = "tenant"`, `USER: Final = "user"`
  - `def app_mode(app: Any) -> str`: `TENANT` without billing, else `current_subject_mode(app)`.
  - `def worker_mode() -> str`: `TENANT` without billing, else `worker_subject_mode()`. Errors propagate, so a failed read never bills `default`.
  - `def runtime_mode() -> str`: `current_runtime().billing_mode()`, or `TENANT` when no runtime is bound. The import from `sm_images.pipeline.runtime` is lazy.
  - `def held_under(tenant: str, recorded: str | None) -> str`: `recorded or tenant`. This is the one place that spells out "NULL means the row's tenant".
  - `def image_subject(tenant: str, owner_id: str | None, mode: str, *, collection_id: uuid.UUID | None = None) -> str`. It is pure and sync. Tenant mode returns `tenant`. User mode returns `subject_for_user(owner_id)`; on a `None`/empty/non-UUID owner (`ValueError`, `TypeError`) it returns `tenant` after `_unbillable(collection_id)`.
  - `async def owner_subject(db: Any, tenant: str, collection: Any, mode: str) -> str`. It calls `image_subject(tenant, collection.owner_id, mode, collection_id=collection.id)`. When that gives a user subject, it falls back to `tenant` (with `_unbillable`) if `await user_exists(db, s)` is false. Tenant mode runs no query.
  - `async def owner_subject_in(factory: Any, tenant: str, collection: Any, mode: str) -> str`. This is `owner_subject` in a short read session of its own (`finalize_session`). Callers whose own session may hold the SQLite writer lock, or soon will, use it. Tenant mode opens no session.
  - `async def for_app(app: Any, factory: Any, tenant: str, collection: Any) -> str`, which is `owner_subject_in(factory, tenant, collection, app_mode(app))`.
  - `async def user_exists(db: Any, subject: str) -> bool`: the seam over `sm_billing.contracts.subject_exists`, which tests monkeypatch.
  - `_unbillable(collection_id)` logs `logger.warning("images.billing.owner_unbillable collection=%s", collection_id)` at most once per collection id per process, using a module-level `set`. `reset_unbillable_log()` exists for tests.
- Produces on `Runtime`: the field `subject_mode: Callable[[], str] | None = None`, and `def billing_mode(self) -> str` that returns `subject_mode()` or `"tenant"` when the field is `None`. The web wires `subject_mode=lambda: app_mode(app)` and the worker wires `subject_mode=worker_mode`.
- Produces in `IMGT/support/billing.py`:
  - `FakeGauge.level_of(subject) -> int` (the live holds whose `tenant_id == subject`).
  - `check` and the swap's limit test use `level_of(tenant_id)`. `limit` applies per subject, and `limits: dict[str, int]` overrides it per subject.
  - `check` records `("check", tenant_id, meter, str(qty))`. Update the 7 existing `gauge.calls` asserts if any of them match `"check"` (grep shows none match today).
  - The fixture `user_mode(monkeypatch)` patches `subject.user_exists` to return `True`, and returns a helper that sets the mode on a given `Runtime` (`dataclasses.replace(rt, subject_mode=lambda: "user")`) or on an app (`app.state.billing_subject_mode = "user"`).

- [ ] **Step 1: Write the failing tests** in `IMGT/core/billing/test_billing_subject.py`:

```python
OWNER = str(uuid.uuid4())

def test_tenant_mode_is_the_tenant():
    assert subject.image_subject("default", OWNER, "tenant") == "default"

def test_user_mode_is_the_owner():
    assert subject.image_subject("default", OWNER, "user") == f"user:{OWNER}"
    assert subject.image_subject("default", OWNER.upper(), "user") == f"user:{OWNER}"

@pytest.mark.parametrize("owner", [None, "", "olga"])
def test_malformed_owner_falls_back_once(owner, caplog):
    subject.reset_unbillable_log()
    cid = uuid.uuid4()
    with caplog.at_level("WARNING"):
        assert subject.image_subject("default", owner, "user", collection_id=cid) == "default"
        assert subject.image_subject("default", owner, "user", collection_id=cid) == "default"
    assert len([r for r in caplog.records if "images.billing.owner_unbillable" in r.message]) == 1

async def test_owner_subject_deleted_owner_falls_back(monkeypatch, caplog): ...
    # patch subject.user_exists -> False; owner_subject(None, "default", coll, "user") == "default"; one log
async def test_owner_subject_existing_owner(monkeypatch): ...  # user_exists -> True: "user:<owner>"
async def test_owner_subject_tenant_mode_runs_no_query(): ...  # db=None, a factory that raises if called
def test_held_under():
    assert subject.held_under("default", None) == "default"
    assert subject.held_under("default", "user:x") == "user:x"
def test_no_billing_is_tenant(): ...  # _billing_off autouse: app_mode(app) == worker_mode() == "tenant"
def test_worker_mode_reads_billing(monkeypatch): ...  # billing on, patch sm_billing.contracts.worker_subject_mode -> "user"
def test_worker_mode_propagates_settings_errors(monkeypatch): ...  # it raises RuntimeError: pytest.raises
def test_app_mode_reads_app_state(monkeypatch): ...  # billing on, app.state.billing_subject_mode = "user" -> "user"
def test_runtime_billing_mode_defaults_to_tenant(pipe): assert pipe.runtime.billing_mode() == "tenant"
def test_worker_runtime_wires_worker_mode(monkeypatch): ...  # worker_runtime().subject_mode is subject.worker_mode (patch out the engine/store builders as test_pipeline_worker.py does)
```

- [ ] **Step 2:** Run `uv run --directory WORKTREE/modules/images pytest -q tests/core/billing/test_billing_subject.py`. Expected: FAIL (`ModuleNotFoundError: sm_images.core.billing.subject`).
- [ ] **Step 3:** Implement `subject.py`, the `Runtime` field and method, the two wirings and the `FakeGauge`/fixture changes. Add `"subject"` nowhere in `core/billing/__init__.__all__`: callers import the submodule.
- [ ] **Step 4:** Run the Step 2 command, then `uv run --directory WORKTREE/modules/images pytest -q tests/core/billing/test_storage_metering.py tests/pipeline/test_pipeline_worker.py`. Expected: PASS, because tenant mode is unchanged.
- [ ] **Step 5:** Commit with `git -C WORKTREE commit -m "images: billing subject helper and runtime mode (#284)"`.

### Task 3: subject columns and host migration

**Files:**
- Modify: `IMG/models/billing_op.py` (`BillingOp.subject`), `IMG/models/image.py` (`Image.storage_subject`, after `storage_hold_id`)
- Create: `host/migrations/versions/c4e9b2a7d613_images_billing_subject.py`
- Test: `IMGT/core/billing/test_billing_subject_columns.py` (new)

**Interfaces:**
- Produces:
  - `BillingOp.subject: str | None = Field(default=None, max_length=64)`. Docstring: the subject the op bills (its key and its hold live there); `NULL` = the row's `tenant_id` (rows before #284).
  - `Image.storage_subject: str | None = Field(default=None, max_length=64)`. Docstring: the subject `storage_hold_id` was taken under; `NULL` = `tenant_id`.
  - Migration `revision = "c4e9b2a7d613"`, `down_revision = "a7c2e4d81b35"`, no branch label. `upgrade` adds `sa.Column("subject", sa.String(64), nullable=True)` to `images_billing_op` and `sa.Column("storage_subject", sa.String(64), nullable=True)` to `images_image`, through `op.batch_alter_table`. `downgrade` drops both. The docstring says that no backfill happens and why (`NULL` already means the tenant).

- [ ] **Step 1: Write the failing test:**

```python
async def test_rows_default_to_null_subject(pipe):
    coll = await pipe.collection({})
    img = await pipe.image(coll)
    assert (await pipe.row(img)).storage_subject is None
    async with pipe.db_state.session_factory() as s:
        s.add(BillingOp(op="release", image_id=img, hold_id="h", subject="user:x"))
        await s.commit()
        assert (await s.execute(select(BillingOp.subject))).scalar_one() == "user:x"
```

- [ ] **Step 2:** Run `uv run --directory WORKTREE/modules/images pytest -q tests/core/billing/test_billing_subject_columns.py`. Expected: FAIL (an unknown attribute or column).
- [ ] **Step 3:** Add the fields and write the migration by hand. Do not autogenerate it: autogenerate could pick up unrelated drift.
- [ ] **Step 4: Verify.** Each line below is a separate Bash call:
  - `uv run --directory WORKTREE/modules/images pytest -q tests/core/billing/test_billing_subject_columns.py` → PASS
  - `SM_DATABASE_URL=sqlite+aiosqlite:////tmp/issue284-migrate.db uv run --directory WORKTREE --project host alembic -c host/alembic.ini upgrade heads` → ends at `c4e9b2a7d613`
  - The same `SM_DATABASE_URL`: `... alembic -c host/alembic.ini check` → `No new upgrade operations detected.`
  - The same: `... alembic -c host/alembic.ini downgrade a7c2e4d81b35`, then `upgrade heads` again → both succeed
  - `uv run --directory WORKTREE python scripts/check_migration_heads.py` → `One migration head: c4e9b2a7d613`
  - Postgres, if the dev-services stack is up on 5432: the same four alembic commands with `SM_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/smpy_modules`. If the stack is not up, say so in the task report. CI's Postgres job is the backstop.
  - Delete `/tmp/issue284-migrate.db`.
- [ ] **Step 5:** Commit with `git -C WORKTREE commit -m "images: record the billing subject per hold (#284)"`.

### Task 4: the op layer replays the recorded subject (hard)

**Files:**
- Modify: `IMG/core/billing/__init__.py`. Rename the `tenant` param to `subject` in `check`, `headroom`, `swap` and `close_key`, and update the docstrings. The behaviour does not change.
- Modify: `IMG/core/billing/ops.py`. `open_op(..., subject: str)` and `add_swap(db, image_id, qty, *, subject: str, factory=None)` write `BillingOp.subject`. `add_release` and `release_storage` take no subject, because billing's `release` takes only the hold id.
- Modify: `IMG/core/billing/settle.py`. `Op` gains `subject: str | None`, `_COLUMNS` adds `BillingOp.subject`, and `_attempt` passes `held_under(tenant, op.subject)` to `run.expire` and `run.swap`.
- Modify: `IMG/core/billing/install.py`, as listed under Interfaces.
- Modify: `IMG/core/billing/repair.py`, as listed under Interfaces.
- Test: `IMGT/core/billing/test_storage_metering_subject.py` (new). Keep it under 280 lines; split into `..._subject_repair.py` if needed.

**Interfaces:**
- Consumes: `subject.held_under`, and the Task 3 columns.
- Produces:
  - `billing_ops.open_op(db, op, image_id, qty, key, *, claim, old, subject: str) -> Claimed`
  - `billing_ops.add_swap(db, image_id, qty, *, subject: str, factory=None) -> BillingOp`
  - `install.swap(factory, tenant, op, mine, meter)`. It still takes the tenant (the image row lookup and lock are tenant rows) and bills `held_under(tenant, op.subject)`.
  - `install.expire(factory, subject: str, mine, meter)`. `close_key` runs under `subject`.
  - `install._names(...) -> tuple[bool, str | None, str | None]`, which is `(present, named hold, its storage_subject)`.
  - `install._fix_old(factory, mine, old: str, subject: str | None)`. When a queued op's old hold is fixed, the op's `subject` is fixed with it in the same conditional `UPDATE`. If the image names a hold, the subject becomes `held_under(tenant, image.storage_subject)`. If the image names none, the op's recorded subject is kept. Billing has not seen the key yet, so moving its subject is safe.
  - `install._install`. It writes `storage_subject=<op's billed subject>` with `storage_hold_id`. Its correcting `add_swap` passes `subject=` that same subject.
  - `repair`. `_COLUMNS` adds `BillingOp.subject` and `Image.storage_subject`.
    - `close_key` and the orphan `get_hold` use the op's subject (`held_under(tenant, op.subject)`).
    - The image's named-hold `get_hold` uses `held_under(tenant, image.storage_subject)`.
    - When `_decide` installs an orphan, it writes `storage_subject = op subject`.
    - Its `add_swap` uses the subject of the hold the image names after that decision: the op subject when it just installed the orphan, otherwise the image's subject.
    - The lock re-read (`lock()`) also returns `storage_subject`, so that a subject change counts as "moved" (`now_seen != seen`).

- [ ] **Step 1: Write the failing tests** with `pipe`, `gauge` and `held_image`. Add `held_image(pipe, gauge, coll, subject="default")`, which seeds the hold under `subject` and writes `storage_subject` when the subject is not `"default"`.
  - `test_legacy_null_subject_op_settles_under_tenant`: an `add_swap` row inserted with `subject=None` for a hold seeded under `"default"`. After `settle`, the new hold has `tenant_id == "default"`, and `assert_counted_once`.
  - `test_user_subject_swap_settles_under_user`: an image seeded under `"user:<u>"` with `storage_subject` set, and `add_swap(subject="user:<u>")`. After `settle`, the new hold has `tenant_id == "user:<u>"`, the image's `storage_subject == "user:<u>"`, and `gauge.level_of("default") == 0`.
  - `test_queued_swap_fixes_subject_with_old_hold`: the image names a `"user:<u>"` hold, but a queued op was written with `subject="default"`. After `settle`, the op row has `subject == "user:<u>"` and `old_hold_id` equal to the named hold, and no `HoldNotFound` was logged (`last_error is None`).
  - `test_expired_user_op_closes_key_under_its_subject`: an op with `subject="user:<u>"` is past its deadline. `settle(now=...)` records `("close_key", key)`, and a spy on `FakeGauge.close_key` sees `tenant_id == "user:<u>"`.
  - `test_repair_reads_holds_under_their_subjects`: a done user-subject op whose hold the image names, at the right size. `repair` queues nothing (`ops()` gains no row), and every `get_hold` spy call names `"user:<u>"`.
  - `test_repair_installs_orphan_with_its_subject`: a lost swap under `"user:<u>"` (an op `hold_id` that the image does not name; the image names nothing that still counts). After `repair` + `settle`, the image names the orphan, `storage_subject == "user:<u>"`, and `assert_counted_once`.
  - `test_user_hold_survives_owner_change`: seed under `"user:<a>"`, change `Collection.owner_id` to `<b>`, then `add_swap(subject="user:<a>")` and `settle`. The new hold is under `"user:<a>"`.

  To make `FakeGauge.close_key`/`get_hold` subject-aware: record `("close_key", tenant_id, key)` and `("get_hold", tenant_id, hold_id)`. Then grep `IMGT` for `"close_key"`/`"get_hold"` call asserts and update them.
- [ ] **Step 2:** Run `uv run --directory WORKTREE/modules/images pytest -q tests/core/billing/test_storage_metering_subject.py`. Expected: FAIL.
- [ ] **Step 3:** Implement. Every existing caller of `open_op`/`add_swap` must now pass `subject=`. Until Tasks 5 and 6 land, `slots.hold_slot` and `storage_hold` pass `subject=tenant` explicitly, so the tree stays green.
- [ ] **Step 4:** Run `uv run --directory WORKTREE/modules/images pytest -q tests/core/billing/`, then `uv run --directory WORKTREE/modules/images pytest -q tests/ingest/test_ingest_hold_outcome.py tests/ingest/test_ingest_hold_rollback.py tests/jobs`. If `tests/jobs` does not exist, run the reconcile and janitor test files instead (`grep -rl "reconcile\|janitor" tests`). Expected: PASS. Then run `uv run --directory WORKTREE python scripts/check_file_size.py`. It must show no ERROR, and no new WARNING for `ops.py`/`settle.py`/`install.py`/`repair.py`.
- [ ] **Step 5:** Commit with `git -C WORKTREE commit -m "images: settle, repair and install replay the recorded billing subject (#284)"`.

### Task 5: the ingest hold bills the collection owner

**Files:**
- Modify: `IMG/ingest/slots.py`. `Slot` gains `subject: str | None = None`. `hold_slot(factory, tenant, slot, size, collection)` derives `who = await subject.owner_subject_in(factory, tenant, collection, subject.runtime_mode())` only after its `meter is None or size < 1` early return, then passes `subject=who` to `open_op` and swaps under `who`. It returns `replace(slot, hold=..., op=..., subject=who)`.
- Modify: `IMG/ingest/service.py`. `_hold(self, collection, slot, size)` passes `collection` through. `reserve` calls `self._hold(collection, s, n)`, and the staged branch of `add_image` calls `self._hold(collection, Slot(new_id, key), len(data))`. The `Image(...)` row adds `storage_subject=slot.subject if slot.hold else None`. The net line change must keep `service.py` under 280. If it cannot, move `reserve`, `_hold`, `release_holds`, `finalize` and `_factory` into `IMG/ingest/service_holds.py` as a mixin, with a `Protocol` for what it reads from the host (`db`, `intent_factory`, `acquired`), following `pagebuilder/service/_host.py`.
- Test: `IMGT/ingest/test_ingest_hold_subject.py` (new)

**Interfaces:**
- Consumes: `subject.owner_subject_in`, `subject.runtime_mode` (Task 2), and `open_op(..., subject=)` (Task 4).
- Produces: `Slot.subject`, and `Image.storage_subject` set at insert.

- [ ] **Step 1: Write the failing tests** with the `uploads` and `gauge` fixtures, setting the web runtime's mode the way `user_mode` does. The web path reads `runtime_mode()`, which is the global runtime set in `on_startup`, so patch `subject.runtime_mode` to return `"user"`, or replace the global runtime.
  - `test_upload_in_user_mode_holds_under_owner`: one upload. Then `gauge.live()[0].tenant_id == f"user:{user_uuid('olga')}"`, the row has `storage_subject` equal to that subject, and the `ingest` op row has the same `subject`.
  - `test_upload_in_tenant_mode_unchanged`: the hold is under `"default"`, `storage_subject is None`, and the op `subject == "default"`.
  - `test_upload_to_unbillable_owner_bills_tenant`: with user mode and `user_exists` patched to return `False`, the hold is under `"default"`, the upload returns 200, and one `images.billing.owner_unbillable` record is logged.
  - `test_import_item_in_user_mode_holds_under_owner`: drive `ingest/imports/settle.settle_item`, or the nearest existing import test helper (see `IMGT/ingest/imports/test_import_tasks.py`), under a runtime with `subject_mode=lambda: "user"` bound through `bind_runtime`. The hold is under the owner.
- [ ] **Step 2:** Run `uv run --directory WORKTREE/modules/images pytest -q tests/ingest/test_ingest_hold_subject.py`. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run `uv run --directory WORKTREE/modules/images pytest -q tests/ingest/test_ingest_hold_subject.py tests/ingest/test_ingest_hold_outcome.py tests/ingest/test_ingest_hold_rollback.py tests/ingest/test_ingest_staged_size.py tests/ingest/test_direct_upload.py tests/core/billing/test_storage_metering.py tests/core/billing/test_storage_metering_direct.py`. Expected: PASS. Then run `check_file_size.py`, which must show no new warning.
- [ ] **Step 5:** Commit with `git -C WORKTREE commit -m "images: the ingest hold bills the collection owner (#284)"`.

### Task 6: pipeline growth bills the image's recorded subject (hard)

**Files:**
- Modify: `IMG/pipeline/load.py`. `Loaded` gains `subject: str | None = None`. `load_run` computes it inside its existing read session with `await subject.owner_subject(db, tenant, collection, runtime.billing_mode())`. It reads `Collection` once: reuse `_display_safe`'s select by loading the collection in `load_run` and passing it in.
- Modify: `IMG/pipeline/storage_hold.py`:
  - `parts` returns a 6-tuple ending in `Image.storage_subject`.
  - `Planned` gains `subject: str | None = None`.
  - `_open` bills `who = found.storage_subject or (tenant if found.hold else loaded.subject or tenant)`, passes `open_op(..., subject=who)`, and returns `(op, old, who)`.
  - `reserve` swaps under `who`, and returns `Planned(planned, hold.id, old, op, subject=who)`.
  - When `record` installs `planned.hold`, it writes `storage_subject=planned.subject`.
  - The queued shrink in `record` calls `add_swap(..., subject=held_under(tenant, found.storage_subject) if found.hold else (loaded.subject or tenant))`.
- Modify: `IMG/pipeline/executor.py`. `Staging` gains `subject: str | None = None`, set from `loaded.subject` next to `staging.token`.
- Test: `IMGT/core/billing/test_storage_metering_pipeline_subject.py` (new)

**Interfaces:**
- Consumes: `subject.owner_subject`, `held_under` and `Runtime.billing_mode` (Task 2), and `open_op`/`add_swap(subject=)` (Task 4).
- Produces: `Loaded.subject` and `Staging.subject`, which Task 7 reads.

- [ ] **Step 1: Write the failing tests.** Use `pipe` with `pipe.runtime = dataclasses.replace(pipe.runtime, subject_mode=lambda: "user")`, `user_exists` patched to return `True`, and a collection whose `owner_id=str(uuid4())`. Pass it through `pipe.collection(..., owner_id=...)`, after making `Pipe.collection` accept an `owner_id` override (`kw.pop("owner_id", "olga")`).
  - `test_growth_first_hold_in_user_mode_bills_owner`: an image with no hold. Run Blur + renditions. The single live hold has `tenant_id == "user:<owner>"`, `storage_subject` equals that subject, and `assert_counted_once`.
  - `test_growth_keeps_legacy_tenant_hold_after_switch`: `held_image(...)` under `"default"` with `storage_subject=None`, then user mode, then a run. The new hold is under `"default"` (continuity), and `gauge.level_of("user:<owner>") == 0`.
  - `test_growth_keeps_user_hold_after_owner_change`: a hold under `"user:<a>"`, then the owner changes to `<b>`, then a run. The new hold is under `"user:<a>"`.
  - `test_shrink_queues_swap_under_held_subject`: a re-run that shrinks the display copy (follow the shrink setup in `test_storage_metering_pipeline.py`). The queued op `subject` equals the image's `storage_subject`.
  - `test_worker_mode_user_meters_owner`: build the runtime with `subject_mode=subject.worker_mode` and monkeypatch `sm_billing.contracts.worker_subject_mode` to return `"user"`. A `pipe.run` meters the owner. This is the spec's worker-path test.
- [ ] **Step 2:** Run `uv run --directory WORKTREE/modules/images pytest -q tests/core/billing/test_storage_metering_pipeline_subject.py`. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run `uv run --directory WORKTREE/modules/images pytest -q tests/core/billing/test_storage_metering_pipeline_subject.py tests/core/billing/test_storage_metering_pipeline.py tests/core/billing/test_storage_metering_swap.py tests/pipeline/test_pipeline_executor.py`. Expected: PASS. Then run `check_file_size.py`.
- [ ] **Step 5:** Commit with `git -C WORKTREE commit -m "images: pipeline growth bills the image's recorded subject (#284)"`.

### Task 7: AI steps bill the collection owner

**Files:**
- Modify: `IMG/pipeline/ai/runner.py`. `consume_requests(staging.subject or ctx.tenant_id, ...)`.
- Modify: `IMG/pipeline/ai/group_load.py`. `GroupJob` gains `subject: str | None = None`, which `load` computes with `await subject.owner_subject(db, tenant, collection, runtime.billing_mode())` from the collection it already reads.
- Modify: `IMG/pipeline/ai/group_run.py`. `consume_requests(job.subject or job.tenant, ...)`. The metering keys (`metering_key(...)`) keep their current form.
- Test: `IMGT/pipeline/ai/test_ai_subject.py` (new)

**Interfaces:**
- Consumes: `Staging.subject` (Task 6), and `subject.owner_subject` (Task 2).

The decision this task carries out: an AI charge is a one-shot `consume` with no hold, so it bills the owner as derived *now*, not `Image.storage_subject`. This is the spec's "AI step charges follow the same payer as storage", applied to new charges.

- [ ] **Step 1: Write the failing tests** with the `ai` fixture (`IMGT/support/ai.py`), `pipe` in user mode and a UUID owner:
  - `test_prompt_step_charges_owner_in_user_mode`: `ai.charges[0]["tenant"] == f"user:{owner}"`.
  - `test_prompt_step_charges_tenant_in_tenant_mode`: `ai.charges[0]["tenant"] == "default"`.
  - `test_group_prompt_charges_owner_in_user_mode`: follow the group setup in `IMGT/pipeline/ai/test_group_prompts_store.py` or `IMGT/support/groups.py`. `ai.charges[-1]["tenant"] == f"user:{owner}"`.
  - `test_ai_charge_key_unchanged_by_mode`: the same image and step in both modes gives the same key prefix (`metering_key` unchanged).
- [ ] **Step 2:** Run `uv run --directory WORKTREE/modules/images pytest -q tests/pipeline/ai/test_ai_subject.py`. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run `uv run --directory WORKTREE/modules/images pytest -q tests/pipeline/ai/`. Expected: PASS.
- [ ] **Step 5:** Commit with `git -C WORKTREE commit -m "images: AI steps bill the collection owner (#284)"`.

### Task 8: web advisory checks read the owner's headroom

**Files:**
- Modify: `IMG/web/endpoints/api/images.py`. `upload_images` and `upload_base64` call `billing.check(request.app, await subject.for_app(request.app, billing.factory_of(ingest.db), bound_tenant(), collection), qty)`.
- Modify: `IMG/web/endpoints/api/uploads.py`. `complete_upload` does the same. `start_upload` passes `subject=` to `prepare`.
- Modify: `IMG/web/endpoints/api/imports.py`. `create_import`'s `check(..., 1)` and `create_zip_import`'s `prepare` use the owner's subject.
- Modify: `IMG/ingest/admission.py`. The new signature is `prepare(app, tenant, size, *, cap, subject: str | None = None)`. It reads `billing.headroom(app, subject or tenant, size)`. The per-tenant lock, the cap and the open-upload count stay per tenant (conservative: other users' open uploads still count against the room). Add one sentence to the module docstring saying this.
- Test: `IMGT/ingest/test_upload_subject.py` (new)

**Interfaces:**
- Consumes: `subject.for_app` (Task 2), `FakeGauge` per-subject limits, and `FakeGauge.check` recording the subject (Task 2).

- [ ] **Step 1: Write the failing tests** with `uploads` and `gauge`, `uploads.app.state.billing_usage = gauge`, `uploads.app.state.billing_subject_mode = "user"` and the `user_mode` fixture:
  - `test_precheck_reads_owner_subject`: an upload by OLGA, the owner. A `check` call names `f"user:{user_uuid('olga')}"`.
  - `test_shared_uploader_is_checked_against_owner_quota`: OLGA's collection, shared to a second stub user with edit rights (reuse the sharing helper in `IMGT/support/access.py`). Set `gauge.limits = {owner_subject: 10}`. The second user's upload gets 402 `quota_exceeded`, and their own subject has no limit.
  - `test_direct_upload_admission_reads_owner_headroom`: `start_upload` with `gauge.limits={owner: 10}` and `size=100` gets 402.
  - `test_import_precheck_reads_owner_subject`: `POST .../imports` with a full owner gauge gets 402.
  - `test_tenant_mode_precheck_unchanged`: the `check` call names `"default"`.
- [ ] **Step 2:** Run `uv run --directory WORKTREE/modules/images pytest -q tests/ingest/test_upload_subject.py`. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run `uv run --directory WORKTREE/modules/images pytest -q tests/ingest/test_upload_subject.py tests/ingest/test_upload_admission.py tests/ingest/test_upload_admission_race.py tests/core/billing/test_storage_metering.py tests/ingest/imports`. Expected: PASS.
- [ ] **Step 5:** Commit with `git -C WORKTREE commit -m "images: upload pre-checks read the collection owner's quota (#284)"`.

### Task 9: boot warning, docs and CLAUDE.md

**Files:**
- Modify: `BIL/subject_boot.py`. Delete `_TENANT_BILLED`, `installed_callers` and the `tenant_billed_callers` warning block, plus any import that only they used (`get_module_package_name`).
- Modify: `BILT/test_subject_mode_boot.py`. Delete `test_installed_images_or_ai_warn` and `test_ai_warning_says_requests_are_split`. Add `test_user_mode_logs_no_tenant_billed_warning`: with images and ai loaded (or with no monkeypatching), `apply_subject_mode` in user mode logs no record containing `"tenant_billed_callers"`. Keep the existing `CALLERS == []` assertion.
- Modify: `modules/billing/docs/subjects.md`:
  - Replace the section "Worker metering stays on the tenant" with "Images bills the collection's owner": who pays and why, the recorded subject (`NULL` = tenant, so old holds stay on `default`), the unbillable fallback and its log, the about-30 s worker lag for new holds only, and the fact that `ai.requests` is no longer split.
  - Fix the anchor link near line 27, and remove "logs two warnings" so the text says one.
- Modify: `modules/images/docs/pipeline.md`. Add a "Who is billed" bullet to the storage-billing section.
- Modify: `docs/superpowers/specs/2026-11-01-billing-subject-design.md`. Decisions item 3 now says it was superseded by #284 (owner pays), with a link to the 2026-11-02 spec.
- Modify: `CLAUDE.md`, the billing paragraph, after the `subject_mode = user` sentence. Add one or two sentences: in user mode images bills `user:<collection owner>` (#284). The subject is recorded per hold (`images_billing_op.subject`, `images_image.storage_subject`; `NULL` = the row's tenant), and settle, repair and growth replay it and never re-derive it. A new images billing call must take its subject from the op or image, or from `sm_images.core.billing.subject`.

- [ ] **Step 1:** Edit the test first. Run `uv run --directory WORKTREE/modules/billing pytest -q tests/test_subject_mode_boot.py`. Expected: FAIL, because the warning still fires when images is loaded, or the test errors on deleted symbols. Note the actual output.
- [ ] **Step 2:** Implement the code change. Re-run: PASS.
- [ ] **Step 3:** Make the docs and CLAUDE.md edits. Run `grep -rn "tenant_billed_callers\|Worker metering stays" WORKTREE/modules WORKTREE/CLAUDE.md`, which should find nothing except the superseded note in the old spec.
- [ ] **Step 4:** Commit with `git -C WORKTREE commit -m "billing: drop the tenant-billed worker warning; document owner billing (#284)"`.

### Task 10: e2e upload billed to the user

**Files:**
- Modify: `tests/e2e/billing-user.spec.ts` (add a second `test(...)`; the file stays standalone)

**Interfaces:**
- Consumes: the whole feature, on a host started with `E2E_BILLING_USER=1` (`tests/e2e/start-test-server.sh` already sets `subject_mode=user` and eager tasks).

- [ ] **Step 1: Write the test** `'images a user uploads count on their own Billing page'`:
  - The admin logs in. `createPlainUser(page, stamp)` (the `user` role), then `PUT /api/permissions/users/{id}` with `['images.view', 'images.create']` (as `images-core.spec.ts` grants).
  - The admin's page reads `[data-meter="images.storage_bytes"]` on `/billing/` and records its text, or its absence.
  - The member creates a collection through the UI, as `images-core.spec.ts` does (`images-new-collection` → Name → Create collection), and uploads `modules/images/tests/fixtures/rotated.jpg` with `images-upload-input`. They wait for one gallery tile.
  - The member goes to `/billing/`. `getByTestId('usage-card').locator('[data-meter="images.storage_bytes"]')` is visible, and does not contain `0 B` or `0 bytes` (match the `formatQuantity` output).
  - The admin reloads `/billing/`. The admin's `images.storage_bytes` row reads what it read before.
- [ ] **Step 2:** Run `~/.claude/bin/wait-for-headroom`. Then, as the only browser job running, run `E2E_BILLING_USER=1 npx --prefix WORKTREE playwright test billing-user` (or the Makefile e2e target with that env, per the `running-the-stack` skill). Expected: both tests PASS. Stop the server afterwards.
- [ ] **Step 3:** Commit with `git -C WORKTREE commit -m "e2e: images uploads bill the user in billing-user (#284)"`.

---

## Final verification (once, at /ship, not per task)

- Run `make lint` (check_rules, check_file_size, check_locales).
- Run `make test-py` with `PYTEST_WORKERS=8`, after `wait-for-headroom`.
- Run the Postgres migration round trip from Task 3 if it was skipped then.
- Run `uv run --directory WORKTREE python scripts/check_migration_heads.py`.
