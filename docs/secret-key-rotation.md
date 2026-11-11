# Rotating `SM_SECRET_KEY`

`SM_SECRET_KEY` (the host's `secret_key`) does two jobs. It signs things — the
session cookie and a handful of links and tokens — and four modules encrypt the
credentials they store with a key derived from it:

| Module | Settings encrypted at rest |
|---|---|
| ai | `chat_api_key`, `embedding_api_key` |
| billing | `stripe_secret_key`, `stripe_webhook_secret` |
| newsletter | `smtp_password` |
| records | `public_submissions_captcha_secret` |

They are stored `enc:v2:<Fernet token>`, each module under its own key (HKDF-SHA256
of the secret, with the module's package as the info string). Since 0.0.16 every
module also decrypts with the keys in **`SM_SECRET_KEY_PREVIOUS`**, which is what
makes a rotation possible without re-entering every credential (#351).

## What a rotation does not cover

Only the stored credentials above survive a rotation. Everything **signed** with
the secret is checked against the current key alone, so after the switch:

- **every session is signed out** (the session cookie);
- **newsletter links already sent stop working**: unsubscribe, open-tracking and
  click links (`/newsletter/u/`, `/o/`, `/c/`) answer the same page but do
  nothing — mail already in inboxes cannot be fixed;
- **records' links and tokens**: double-opt-in confirmation links already sent,
  and forms loaded before the switch (the signed form token; visitors reload and
  send again);
- **images' direct-upload tickets** in flight;
- the **keyed hashes** derived from the secret (records' `sm_ip_hash`, analytics'
  visitor hashes) change, so new rows do not match old ones.

Plan the rotation for a quiet period, and say so before you start if
newsletters went out recently.

## `SM_SECRET_KEY_PREVIOUS`

One retired key, or a JSON list of them (newest first):

```
SM_SECRET_KEY_PREVIOUS=old-key
SM_SECRET_KEY_PREVIOUS=["old-key", "older-key"]
```

It is read from the process environment, else from the project `.env` (the one
the framework's `BootstrapSettings` locates). A value starting with `[` that is
not a JSON list of strings stops every encrypt and decrypt with an error naming
the variable, never its value. Unlike `SM_SECRET_KEY` there is no database
fallback: previous keys exist only where you put them, and a host that injects
`secret_key` in code still gives previous keys through this variable.

## Procedure

1. **Generate a new key.**

   ```bash
   python -c "import secrets; print(secrets.token_urlsafe(32))"
   ```

2. **Set both variables everywhere the app runs**: the web process, every Celery
   worker and beat, and the shell you run the script from:

   ```
   SM_SECRET_KEY=<new>
   SM_SECRET_KEY_PREVIOUS=<old>
   ```

   If the old key was never in the environment — the host generated it and
   stored it as the `host.secret_key` settings row — copy that row's value as the
   previous key. Then either keep `SM_SECRET_KEY` set from now on (the
   environment wins over the row), or overwrite the row with the new key.

3. **Restart** the web process, workers and beat. Everyone is signed out (see
   above). Stored credentials keep working: they open with the previous key.

4. **Re-encrypt** the stored credentials under the new key, from the repo root:

   ```bash
   uv run python scripts/reencrypt_secrets.py --dry-run
   uv run python scripts/reencrypt_secrets.py
   ```

   The dry run lists every row and what it needs (`rotate`, `upgrade` for a
   0.0.15 `enc:v1:` value, `seal` for one stored in the clear, `current`,
   `empty`) without writing. The real run is all or nothing: if any row cannot be
   decrypted with the keys given, or belongs to a module that is not installed,
   it lists them and writes nothing. It never prints a value, and running it
   again is a no-op. `--no-seal-plaintext` leaves values stored in the clear as
   they are.

   A host built from the published modules, without this repo's `scripts/`,
   re-enters each credential instead: the AI page, billing's connection screen,
   newsletter's SMTP password, and records' CAPTCHA secret on the Settings
   screen. A save always writes the current format under the current key.

5. **Restart** again, so no process holds a value it decrypted before step 4.

6. **Remove `SM_SECRET_KEY_PREVIOUS`** everywhere, and **restart** once more.
   Anything the script did not re-encrypt is now unreadable: the modules say so
   (ai's `AiKeyUnreadableError`, billing's `BillingKeyUnreadableError`,
   newsletter's `smtp_password_unreadable`, records' `503 captcha_unavailable`),
   naming the field, never the value.

## Formats

| Stored value | Read as |
|---|---|
| `enc:v2:…` | written since 0.0.16; opened with `SM_SECRET_KEY`, then each previous key |
| `enc:v1:…` | written by 0.0.15 and earlier (SHA-256 of the secret); still read, with one warning per field, **until 0.1.0** — re-encrypt or re-save it before then |
| another `enc:` prefix | refused as unreadable, never used as plaintext |
| no prefix | plaintext, with one warning per field (records encrypts its row at startup) |

Downgrading to 0.0.15 after anything wrote `enc:v2:` leaves those values
unreadable to 0.0.15; re-enter them after the downgrade.
