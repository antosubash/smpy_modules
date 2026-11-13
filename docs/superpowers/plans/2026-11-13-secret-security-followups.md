# Secret Security Follow-ups Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Close #365/#366 by sealing billing settings writes and verifying newsletter/records tokens across host-key rotation.

**Architecture:** Reuse the existing sealed JSON field pattern and module-local previous-key parsers. Signing formats and callers remain compatible. Records verifies its gate before DB access and binds its state MAC to the same candidate key.

**Tech Stack:** Python 3.12, FastAPI, Pydantic serializers, SQLModel, existing cryptography/HMAC helpers, pytest, existing browser tooling.

**Spec:** `docs/superpowers/specs/2026-11-13-secret-security-followups-design.md` (approved).

## Global Constraints

- No new dependency, schema migration, route, screen, background job, or version bump.
- No sibling-internal imports; module-local copies preserve the existing parity checks.
- Always sign with the current host key; token formats, permissions, tenancy, expiry, nonce revocation, and public refusal behavior remain intact.
- Never read credential files or `.env` files. Use only synthetic secrets and isolated test databases.
- Before heavy work run `~/.codex/bin/wait-for-headroom`; at most two heavy jobs total, one full suite at a time, `PYTEST_WORKERS=8`.
- Work only in `/home/anto/.codex/worktrees/secret-security-followups/smpy_modules`, branch `feat/secret-security-followups`.
- Do not edit Claude configuration or existing skills. Preserve every other worktree.

## Review Focus

- Settings serialization must refuse a live app's missing key without breaking no-app hydration/dumps (Task 1).
- Existing string rows, newly JSON-encoded rows, and ciphertext passed through Connection must all hydrate without double encryption (Task 1).
- Bad previous-key configuration cannot break valid current-key tokens or expose values through anonymous errors (Tasks 2/3).
- Retired key bytes must be used verbatim, and removing the key must revoke its tokens (Tasks 2/3).
- Records' two MACs must verify under one key, and a valid old signature must not bypass nonce revocation or expiry (Task 3).

### Task 1: Seal billing settings on write

**Files:** Modify `modules/billing/sm_billing/core/settings.py`, `core/crypto.py`, `module.py`; create `core/sealed_secret.py` if needed for a focused serializer; add `modules/billing/tests/core/test_sealed_secrets.py` and focused HTTP settings regression tests under `tests/web/`; update `scripts/tests/parity_crypto.py`, billing `docs/operations.md`, affected settings docstrings and headless-write tests under `scripts/tests/` only as needed.

**Interfaces:** Consume `crypto.encrypt_value(str) -> str`, `is_encrypted(str) -> bool`, the existing records sealed-field/liveness pattern, and framework JSON field persistence. Produce billing-local `SealedSecret` and the same string-valued `BillingSettings` attributes; Connection and provider readers need no new interface.

Independent of Tasks 2/3; execute sequentially to avoid shared-index or test contention.

- [ ] Add failing tests: generic Settings writes for both fields persist JSON ciphertext and remain masked; headless field serialization seals; nullable/empty clears, ciphertext pass-through and legacy `string` rows work. Live app with no key refuses storage; no-app/dead-app dump remains safe for hydration; repeated dumps/reloads don't mutate held values.
- [ ] Run new tests before production edits and save the expected RED evidence. Run focused baseline as needed from `modules/billing` with `uv run pytest -q <test paths>`.
- [ ] Implement the local sealed annotation and provider liveness setup using records' pattern. Preserve Connection blank/explicit-clear semantics and encrypted-prefix pass-through. Update parity metadata without weakening shared crypto guarantees.
- [ ] Document JSON string quoting for `scripts/set_setting.py`, existing plaintext cleanup with `reencrypt_secrets.py`, and the raw framework import bypass. Do not add startup database writes.
- [ ] Run billing's suite (`PYTEST_WORKERS=8 uv run pytest -n 8` from `modules/billing`), affected script/parity tests, and focused ruff. Save GREEN output and self-review the diff.
- [ ] Commit task files as `fix(billing): seal Stripe secrets on settings writes` and write the task report.

### Task 2: Preserve newsletter links through key rotation

**Files:** Modify `modules/newsletter/sm_newsletter/core/tokens.py`; create `modules/newsletter/tests/core/test_token_rotation.py` and extend focused tests under `tests/web/` for unsubscribe/open/click. Update token docstrings. No root rotation-guide edit yet (Task 3 owns it).

**Interfaces:** Consume `sm_newsletter.core.crypto.previous_secrets() -> tuple[str, ...]`. Preserve `sign`, `parse`, and `verify` call signatures and `SendToken` claims. Produce current-first verification with previous keys read only on MAC failure; return existing `None` refusals on malformed fallback configuration and log only a safe diagnostic.

Independent of Task 1 and records files; execute after Task 1 review.

- [ ] Write failing pure-helper and public-route regressions proving old tokens work for purposes `u`, `o`, `c` across multiple retired keys; new tokens still use the supplied current key. Include retired-key removal, whitespace-preserving keys, malformed previous config, tampering/wrong purpose/tenant, and no DB access for a forged gate.
- [ ] Run the new tests before production edits and save expected RED evidence.
- [ ] Add the smallest current-first MAC fallback in shared verification code. Preserve missing-current-key refusal, parser bounds, canonical token checks, host-derived tenant restrictions, and indistinguishable public responses. Never sign with previous keys or attach them to claims.
- [ ] Run newsletter's suite (`PYTEST_WORKERS=8 uv run pytest -n 8` from `modules/newsletter`), focused ruff, and save GREEN evidence.
- [ ] Commit as `fix(newsletter): accept retained keys for signed links` and write the task report.

### Task 3: Preserve records forms and mailed links through rotation

**Files:** Modify `modules/records/sm_records/public_submissions/tokens.py`, `links.py`, and bind/opt-in consumers only if needed; create rotation tests under `modules/records/tests/public_submissions/` and extend route tests. Update `docs/secret-key-rotation.md`, `modules/records/docs/operations.md` and newsletter docs wherever they currently claim rotation kills these links.

**Interfaces:** Consume `sm_records.core.crypto.previous_secrets() -> tuple[str, ...]`. Preserve `sign_form`, `verify_form`, `links.sign`, `links.parse`, `links.matches` signatures; `Link` may carry private non-secret gate metadata. Never carry a raw key in claims. Existing `TokenError`/`LinkInvalid` refusal contracts remain unchanged.

Hard task: the pre-DB gate and post-DB nonce MAC must use the same candidate key. Independent source files from Tasks 1/2; execute after Task 2 review.

- [ ] Write failing tests for old form, confirm and unsubscribe tokens under one/multiple retained keys; confirm new signatures use current only and removing an old key revokes them. Pin form min-fill/max-age, digest, confirmation expiry, tenant/type/action, rotated nonce and malformed previous config behavior.
- [ ] Add a mixed-key gate/state splice rejection and public-route tests that old links complete the intended state transition while forged gates reach no DB lookup. Use real route/store outcomes rather than mock-only assertions.
- [ ] Run tests before production edits; save expected RED evidence.
- [ ] Implement current-first fallback in the shared helpers. Preserve pre-DB gate verification; carry the signed gate (or equivalent non-secret context) to require gate/state validation under one candidate key. Handle malformed config with safe existing refusals, keeping valid current-key tokens unaffected.
- [ ] Update rotation documentation: credential re-encryption cannot re-sign issued links; retain retired keys while their links must work, remove compromised keys to revoke them. Document indefinite unsubscribe links, unchanged sessions/images/hash behavior, and existing billing plaintext cleanup.
- [ ] Run records' suite (`PYTEST_WORKERS=8 uv run pytest -n 8` from `modules/records`), focused ruff and save GREEN evidence.
- [ ] Commit as `fix(records): retain signed links across key rotation` and write the task report.

## Integration and shipping

The controller reviews each task against its brief and report, then runs the complete Python/frontend/lint/build checks serially under the workstation caps. Use the existing running-the-stack skill for an owned local stack and browser smoke checks of generic Settings, Connection and public links/forms. Finish with `/ship` (optimize once, independent code review, QA, verification and one PR closing #365/#366); no base push, force push, production changes or merge.
