"""The stored-secret crypto copies, and how they may differ (#127, #351, #350).

Split out of ``parity_families.py``, which appends these to ``FAMILIES``; the
rules there apply here — an allowance is a decision, and says why.

ai, billing, newsletter and records each keep a copy of one ``core/crypto.py``
(a published module must not import a sibling): the same formats (``enc:v1:``
read, ``enc:v2:`` written), the same HKDF derivation with the module's own
``info``, the same ``SM_SECRET_KEY_PREVIOUS`` parsing and the same
re-encryption. ``scripts/tests/test_secret_crypto_formats.py`` pins the bytes;
this pins that the code stays one design.
"""

from __future__ import annotations

from parity_support import Copy, Family

AI = "modules/ai/sm_ai/core/crypto.py"
BILLING = "modules/billing/sm_billing/core/crypto.py"
NEWSLETTER = "modules/newsletter/sm_newsletter/core/crypto.py"
RECORDS = "modules/records/sm_records/core/crypto.py"

_AI_MESSAGES = (
    "SM_SECRET_KEY is not set — the AI module needs it to encrypt stored provider keys.",
    "AI setting %r is stored in the v1 format; run "
    "scripts/reencrypt_secrets.py or re-save it via the AI settings page.",
    "AI setting %r is stored unencrypted; re-save it via the AI settings page to encrypt it.",
)
_NEWSLETTER_MESSAGES = (
    "SM_SECRET_KEY is not set — the newsletter module needs it to encrypt the SMTP password.",
    "Newsletter setting %r is stored in the v1 format; run "
    "scripts/reencrypt_secrets.py or re-save it through the password endpoint.",
    "Newsletter setting %r is stored unencrypted; re-save it through "
    "the password endpoint to encrypt it.",
)

CRYPTO_FAMILIES: tuple[Family, ...] = (
    Family(
        "stored-secret crypto",
        (
            Copy(AI, messages=_AI_MESSAGES),
            Copy(
                BILLING,
                own={
                    "BillingKeyUnreadableError": "AI keeps its error in sm_ai.contracts.errors "
                    "and newsletter in sm_newsletter.core.errors, where their APIs map it.",
                    "BillingKeyUnreadableError.__init__": "See BillingKeyUnreadableError.",
                },
                messages=(
                    "The app has no secret_key — the billing module needs it to encrypt "
                    "stored Stripe secrets.",
                    "Billing setting %r is stored in the v1 format; run "
                    "scripts/reencrypt_secrets.py or re-save it on /admin/billing/connection.",
                    "Billing setting %r is stored unencrypted; re-save it "
                    "on /admin/billing/connection to encrypt it.",
                ),
            ),
            Copy(NEWSLETTER, messages=_NEWSLETTER_MESSAGES),
            Copy(
                RECORDS,
                own={
                    "CaptchaSecretUnreadableError": "See billing's BillingKeyUnreadableError.",
                    "CaptchaSecretUnreadableError.__init__": "See CaptchaSecretUnreadableError.",
                    "has_secret_provider": "SealedSecret dumps unsealed in a process with no "
                    "app (newsletter's worker); only records has a sealed field.",
                },
                messages=(
                    "The app has no secret_key — the records module needs it to encrypt "
                    "the stored CAPTCHA secret.",
                    "Records setting %r is stored in the v1 format; run "
                    "scripts/reencrypt_secrets.py or re-save it on the Settings screen.",
                    "Records setting %r is stored unencrypted; re-save it "
                    "on the Settings screen to encrypt it.",
                ),
            ),
        ),
        shared=(
            "ENC_V1",
            "ENC_V2",
            "PREVIOUS_ENV",
            "_INFO",
            "_warned_plaintext",
            "_warned_v1",
            "_secret_provider",
            "set_secret_provider",
            "previous_secrets",
            "_dotenv_previous",
            "_parse_previous",
            "_v1_key",
            "_v2_key",
            "_keys",
            "is_encrypted",
            "encrypt_value",
            "_open",
            "decrypt_value",
            "reencrypt_value",
        ),
        differ={
            "_current_secret": "ai and newsletter also run in workers with no app, so they "
            "fall back to SM_SECRET_KEY from the environment and .env; billing and records "
            "take the app's secret only.",
            "_unreadable": "Each module raises its own unreadable-secret error.",
        },
    ),
    Family(
        "stored-secret crypto: worker fallback",
        (
            Copy(AI, messages=_AI_MESSAGES),
            Copy(NEWSLETTER, messages=_NEWSLETTER_MESSAGES),
        ),
        shared=("_current_secret", "_dotenv_secret", "explicit_secret"),
    ),
)
