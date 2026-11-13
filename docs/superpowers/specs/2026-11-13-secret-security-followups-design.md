# Secret security follow-ups: billing writes and signed-link rotation

Date: 2026-11-13. Status: approved by the user on 2026-11-13.

## Open-issue grouping and order

Live issues and comments were read on 2026-11-13. The four open PRs are
dependency updates; none implements the issue work below.

| Group | Issues | Treatment |
| --- | --- | --- |
| Secret handling and key rotation | [#365](https://github.com/antosubash/smpy_modules/issues/365), [#366](https://github.com/antosubash/smpy_modules/issues/366) | First implementation batch, this design and one PR. Both follow #351 and use the existing crypto/settings patterns. |
| Article URL validation | [#364](https://github.com/antosubash/smpy_modules/issues/364) | Next independent batch: validation on article save/restore and safe rendering. |
| Module boundaries and framework extraction | [#376](https://github.com/antosubash/smpy_modules/issues/376), [#374](https://github.com/antosubash/smpy_modules/issues/374) | Related architecture work, separate PRs: records DTO moves can be local; tenancy extraction needs an upstream framework release first. |
| Migration distribution | [#334](https://github.com/antosubash/smpy_modules/issues/334) | Remains parked as its latest comment requests; branch migration versus public data-step helpers needs a separate design choice. |
| External adoption and future billing | [#86](https://github.com/antosubash/smpy_modules/issues/86), [#87](https://github.com/antosubash/smpy_modules/issues/87) | #86 belongs in iiasa_lib_rag; #87 explicitly waits for a consumer requirement. Neither belongs in this batch. |
| Review tracker | [#361](https://github.com/antosubash/smpy_modules/issues/361) | Tracking umbrella; latest comment says its original findings are resolved except #334. No duplicate implementation. |

This grouping is local. Issue labels, comments, status, repository settings,
and existing worktrees are not changed.

## Goal and scope

Close #365 and #366 in one reviewable PR. Seal billing's Stripe secrets on
supported settings writes and preserve newsletter/records signed links across
an operator's key rotation. Reuse the existing module-local crypto copies;
add no dependency, schema migration, route, screen, or background job.

Sessions, images upload tickets, keyed IP/analytics hashes, upstream crypto
extraction, and other issue groups are outside this batch.

## Approach and alternatives

Use records' established sealed-field pattern for billing and each module's
existing `crypto.previous_secrets()` for verification fallback. Changing
billing's `manage_url` would hide other settings without giving them a home.
A new token format or key-id registry would add deployment and compatibility
work without being needed to verify existing links.

## Billing design (#365)

- Give `stripe_secret_key` and `stripe_webhook_secret` a billing-local
  `SealedSecret` annotation: nullable string, empty normalized to `""`, and a
  serializer that encrypts nonempty plaintext as `enc:v2:`. Held values remain
  strings and serialization does not mutate them.
- Generic Settings writes and `scripts/set_setting.py` then use the
  framework's existing JSON-field validated-dump path. Existing `string` rows
  still hydrate; new writes use `json` rows. The rotation script already
  handles both encodings.
- Install the live provider during `register_settings`, including headless
  app construction. Reuse records' absent/dead-app versus live-empty-key
  distinction: a live app without a key must refuse a plaintext write.
  Provider lifecycle changes must preserve the crypto parity checks.
- Preserve encrypted strings without wrapping them again. Preserve Connection
  screen behavior: blank keeps the existing secret; explicit clear removes
  it. Generic Settings keeps its existing empty-value clearing behavior.
- Keep legacy plaintext reads compatible. Existing plaintext rows are cleaned
  with the existing `reencrypt_secrets.py`, rather than adding startup database
  writes. The raw framework `smpy settings import-from-env` bypasses serializers
  and still requires that cleanup; document this boundary explicitly.
- Document the headless CLI's changed input encoding: these fields now require
  a JSON string argument, e.g. `'"sk_test_example"'`. Preserve response masking,
  permissions, and provider reload behavior.

## Signed-link design (#366)

- Always mint tokens with the current host key, with unchanged formats and
  claims. On verification, try the current key first; consult the existing
  previous-key parser only after the current MAC fails, in configured order.
  Preserve key bytes, including whitespace, as the crypto parser does.
- Cover newsletter unsubscribe/open/click, records form tokens, and records
  confirmation/unsubscribe links. Put fallback in their shared verification
  code so API and page routes behave consistently.
- Records' gate MAC must verify before any database query. Its later state
  MAC must still validate the current subscriber nonce. Both MACs must match
  the same candidate key; carry only non-secret verification metadata between
  the checks. Never attach a signing key to a returned claims object.
- Preserve token size/ASCII validation, purpose and tenant binding, form
  minimum-fill and maximum-age limits, confirmation expiry, nonce revocation,
  host-derived tenant restrictions, and indistinguishable public refusals.
- Bad previous-key configuration must not break a current-key token or expose
  keys. If fallback is needed, reject the token through the existing public
  refusal and log only a safe configuration diagnostic. Missing current keys
  continue to fail closed.
- Update the rotation guide: retaining an old key keeps its issued links valid;
  removing it revokes them. Re-encryption alone is insufficient grounds to
  remove a key because newsletter and records unsubscribe links do not expire.
  A compromised retired key must be removed even if old links then stop working.

## Change surface

- Billing: `core/settings.py` and a small local sealed-field helper if needed,
  provider installation in `module.py`, and `core/crypto.py` lifecycle support.
- Newsletter: `core/tokens.py` and existing public token consumers if required.
- Records: `public_submissions/tokens.py`, `links.py`, and their bind/opt-in
  consumers where verification context must be carried across both checks.
- Regression tests in each module's mirrored test area; crypto parity metadata
  in `scripts/tests/parity_crypto.py` if lifecycle helpers change.
- Billing operations docs, affected token docstrings, and
  `docs/secret-key-rotation.md`. No sibling-internal imports or version bump.

## Decisions made

Start with #365/#366 because they share the existing key infrastructure and
have bounded acceptance criteria. Use one branch/PR for this group. Leave
the raw framework importer and existing plaintext cleanup behavior explicit,
without expanding into a framework patch or a new automatic data migration.
Keep existing settings UI, permissions, token wire formats, and signing APIs.
The implementation may choose the smallest private representation of the
verified gate needed to enforce the same-key check without retaining a secret.

## Verification

Write failing regressions before changing behavior:

1. Both billing secrets saved through generic Settings have encrypted stored
   bytes, stay masked, and decrypt correctly. Cover headless serialization,
   old/new row encodings, missing-key refusal, repeated dumps/reloads,
   ciphertext pass-through, and Connection blank/clear behavior.
2. All three newsletter purposes and all records token kinds survive one and
   multiple rotations while old keys are configured; new tokens use only the
   current key, and removing an old key rejects its tokens.
3. Tampered/cross-purpose/cross-tenant/expired tokens, rotated subscriber nonces,
   and mixed-key gate/state combinations remain rejected. Exercise public
   routes as well as pure token helpers; forged gates do not reach the DB.
4. Invalid previous-key configuration leaves current-key tokens usable and
   refuses fallback without secret disclosure. Pin verbatim old-key bytes.

Then run repository lint/type checks and Python/frontend suites, serialized
with `PYTEST_WORKERS=8`; run affected route integration and browser smoke checks
for generic Settings, Connection, and public forms/links. Use the existing
running-the-stack skill and owned throwaway data. Run `/ship` after checks and
review converge, opening a PR that closes #365 and #366 without merging it.

## Risks

The settings field changes persistence encoding and headless CLI quoting;
legacy hydration, masking, and reload tests must pin compatibility. Module
crypto providers are process-global, so liveness and test-app cleanup must be
preserved. Accepting previous keys deliberately extends their verification
lifetime; operators need the updated retention/revocation guidance. No live
Stripe calls or production data are needed for this batch's verification.
