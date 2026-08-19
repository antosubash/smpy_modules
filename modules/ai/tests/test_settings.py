"""Settings defaults, env seeding, and the module-global services holder."""

from __future__ import annotations

import pytest
from sm_ai import services
from sm_ai.contracts.errors import AiNotConfiguredError
from sm_ai.settings import AiSettings


@pytest.fixture(autouse=True)
def _reset_holder():
    yield
    services.reset()


class TestDefaults:
    def test_chat_defaults(self):
        s = AiSettings()
        assert s.chat_provider == "anthropic"
        assert s.chat_model == "claude-opus-5"
        assert s.chat_base_url == ""
        assert s.chat_api_key == ""

    def test_embeddings_unconfigured_by_default(self):
        s = AiSettings()
        assert s.embedding_provider == ""
        assert s.embedding_model == ""
        assert s.embedding_dim == 0


class TestEnvSeeding:
    def test_env_vars_fill_unset_fields(self, monkeypatch):
        # hydrate_settings constructs AiSettings(**db_overrides); BaseSettings
        # then reads SM_AI_* env for anything the DB didn't override. This is
        # how dev/CI configure with zero DB rows.
        monkeypatch.setenv("SM_AI_CHAT_MODEL", "claude-sonnet-5")
        monkeypatch.setenv("SM_AI_EMBEDDING_DIM", "4096")
        s = AiSettings()
        assert s.chat_model == "claude-sonnet-5"
        assert s.embedding_dim == 4096

    def test_explicit_kwargs_beat_env(self, monkeypatch):
        monkeypatch.setenv("SM_AI_CHAT_MODEL", "from-env")
        assert AiSettings(chat_model="from-db").chat_model == "from-db"


class TestHolder:
    def test_current_settings_before_install_raises(self):
        with pytest.raises(AiNotConfiguredError) as exc:
            services.current_settings()
        assert exc.value.field == "module"

    def test_install_then_read(self):
        installed = services.install(services.AiServices(settings=AiSettings()))
        assert services.current_settings() is installed.settings

    def test_hot_swap_visible_through_holder(self):
        # apply_changes_and_reload assigns services.settings = validated on the
        # same AiServices instance app.state holds — the holder must see it.
        installed = services.install(services.AiServices(settings=AiSettings()))
        installed.settings = AiSettings(chat_model="swapped")
        assert services.current_settings().chat_model == "swapped"
class TestReadDto:
    def test_out_normalizes_env_seeded_provider_case(self):
        # SM_AI_CHAT_PROVIDER=Anthropic works at runtime (resolve.py lowers
        # it); the read DTO must serve the lowercase id or the settings
        # dropdown renders no selection.
        from sm_ai.contracts.schemas import AiSettingsOut

        out = AiSettingsOut(
            chat_provider=" Anthropic ",
            chat_model="claude-opus-5",
            chat_base_url="",
            has_chat_api_key=False,
            embedding_provider="",
            embedding_model="",
            embedding_base_url="",
            has_embedding_api_key=False,
            embedding_dim=0,
        )
        assert out.chat_provider == "anthropic"
        assert out.embedding_provider == ""
