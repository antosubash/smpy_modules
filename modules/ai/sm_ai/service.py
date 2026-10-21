"""AI settings service — reads current settings and applies admin changes.

No AI table: values live in the shared settings store. Writes go through
``settings.reload.apply_changes_and_reload`` which validates against
``AiSettings``, persists (SYSTEM scope), hot-swaps ``app.state.sm_ai`` (the
same instance the module-global holder references) and publishes
``SettingsReloaded``. Key material is encrypted before it ever reaches the
store — see ``build_changes``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sm_ai import constants, crypto, services
from sm_ai.contracts.schemas import AiSettingsOut, AiSettingsUpdate

if TYPE_CHECKING:
    from fastapi import FastAPI
    from sqlalchemy.ext.asyncio import AsyncSession

_CLEAR_FLAGS = {
    "clear_chat_api_key": "chat_api_key",
    "clear_embedding_api_key": "embedding_api_key",
}


class AiService:
    """Read/update the host's AI connection settings."""

    def __init__(self, app: FastAPI, db: AsyncSession) -> None:
        self.app = app
        self.db = db

    @staticmethod
    def current() -> AiSettingsOut:
        # Static: reads only the module-global holder, so callers that never
        # write (GET /settings) can use it without resolving app/db deps.
        s = services.current_settings()
        return AiSettingsOut(
            **s.model_dump(exclude=set(constants.SECRET_FIELDS)),
            has_chat_api_key=bool(s.chat_api_key),
            has_embedding_api_key=bool(s.embedding_api_key),
        )

    @staticmethod
    def build_changes(data: AiSettingsUpdate) -> dict[str, Any]:
        """Translate an update payload into settings-store changes.

        Secret fields: omitted or blank = keep the stored key; a value is
        stripped (keys pasted from clipboards grow trailing newlines that
        would round-trip into provider 401s) and encrypted; ``clear_*`` wins
        and empties the field.
        """
        payload = data.model_dump(exclude_unset=True)
        changes: dict[str, Any] = {}
        for field, value in payload.items():
            if field in _CLEAR_FLAGS:
                continue  # handled below
            if value is None:
                continue
            if field in constants.SECRET_FIELDS:
                value = value.strip()
                if value == "":
                    continue
                changes[field] = crypto.encrypt_value(value)
            elif isinstance(value, str):
                changes[field] = value.strip()
            else:
                changes[field] = value
        for flag, target in _CLEAR_FLAGS.items():
            if payload.get(flag):
                changes[target] = ""
        return changes

    @staticmethod
    def slot_errors(changes: dict[str, Any]) -> list[dict[str, Any]]:
        """Request-validation errors for the slots as they would be after ``changes``.

        Judged on the merged result, not the payload: a partial update that
        sets only the provider, or only blanks the URL, must not leave an
        ``openai_compatible`` slot with no endpoint — it has no default one,
        so the slot would fail every call until someone noticed (#164).
        Shaped like FastAPI's own 422 items so the page renders them alike.
        """
        merged = {**services.current_settings().model_dump(), **changes}
        errors: list[dict[str, Any]] = []
        for slot in constants.TEST_SLOTS:
            provider = str(merged[f"{slot}_provider"]).strip().lower()
            url_field = f"{slot}_base_url"
            if provider in constants.PROVIDERS_NEEDING_BASE_URL and not merged[url_field].strip():
                errors.append(
                    {
                        "type": "value_error",
                        "loc": ["body", url_field],
                        "msg": f"a base URL is required for the {provider} provider",
                        "input": merged[url_field],
                    }
                )
        return errors

    async def apply(self, changes: dict[str, Any]) -> AiSettingsOut:
        """Persist and hot-swap the given field changes, then return current."""
        # Plugin→plugin imports (settings is a declared dependency); kept local
        # so import order during discovery stays tolerant.
        from settings.reload import apply_changes_and_reload
        from settings.service import SettingService
        from settings.store import SettingsStore

        store = SettingsStore(SettingService(self.db))
        bus = self.app.state.sm.event_bus
        await apply_changes_and_reload(
            self.app, bus, store, package=constants.PACKAGE, changes=changes
        )
        return self.current()
