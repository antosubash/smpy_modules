"""Settings defaults, no environment sources, and the module-global services holder."""

from __future__ import annotations

import pytest
from sm_ai import services
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


class TestNoEnvironment:
    """DB-backed only (#124): an ``SM_AI_*`` variable or a ``.env`` is dead."""

    def test_env_vars_are_ignored(self, monkeypatch):
        monkeypatch.setenv("SM_AI_CHAT_MODEL", "from-env")
        monkeypatch.setenv("SM_AI_EMBEDDING_DIM", "4096")
        # Unprefixed field names too — a plain BaseSettings would read these.
        monkeypatch.setenv("CHAT_API_KEY", "sk-from-bare-env")
        s = AiSettings()
        assert s.chat_model == "claude-opus-5"
        assert s.embedding_dim == 0
        assert s.chat_api_key == ""

    def test_a_dotenv_in_the_working_directory_is_ignored(self, tmp_path):
        # conftest chdir'd to tmp_path; this is the worker-from-elsewhere case.
        (tmp_path / ".env").write_text("SM_AI_CHAT_PROVIDER=openai\nchat_model=x\n")
        s = AiSettings()
        assert s.chat_provider == "anthropic"
        assert s.chat_model == "claude-opus-5"

    def test_constructor_values_are_what_hydration_passes(self):
        # hydrate_settings constructs AiSettings(**db_overrides).
        assert AiSettings(chat_model="from-db").chat_model == "from-db"


class TestStoredEmbeddingDim:
    """#164: a negative width already in the store must not fail hydration.

    The framework falls back to *all* defaults when a class will not construct,
    which would drop the chat slot and its key along with the bad width.
    """

    def test_negative_stored_dim_reads_as_unset(self, caplog):
        with caplog.at_level("WARNING", logger="sm_ai.settings"):
            s = AiSettings(embedding_dim=-5, chat_model="kept")
        assert s.embedding_dim == 0
        assert s.chat_model == "kept"
        assert "embedding_dim" in caplog.text

    def test_hydration_keeps_other_fields(self):
        from settings.hydrate import build_settings

        s = build_settings(
            AiSettings,
            {"embedding_dim": ("-5", "int"), "chat_provider": ("openai", "string")},
        )
        assert s.embedding_dim == 0
        assert s.chat_provider == "openai"

    def test_valid_dim_kept(self):
        assert AiSettings(embedding_dim=1536).embedding_dim == 1536


class TestHolder:
    def test_current_settings_without_install_hydrates_lazily(self, monkeypatch):
        # No host registered the module (a Celery worker, #100): settings come
        # from the store instead of raising — see test_worker_settings.
        monkeypatch.setattr(services.worker_settings, "load", lambda: AiSettings(chat_model="lazy"))
        assert services.current_settings().chat_model == "lazy"

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
    def test_out_normalizes_provider_case(self):
        # A row saved as "Anthropic" (set_setting.py, the generic Settings
        # screen) works at runtime (resolve.py lowers it); the read DTO must
        # serve the lowercase id or the settings dropdown renders no selection.
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
