import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from sm_analytics.core.runtime import Runtime
from sm_analytics.core.settings import AnalyticsSettings
from sm_analytics.models import AnalyticsEvent, AnalyticsProperty, AnalyticsSession
from sqlalchemy import func, select


async def test_operator_cleanup_uses_stored_retention_and_closes_engine(factory, monkeypatch):
    root = Path(__file__).resolve().parents[4]
    monkeypatch.syspath_prepend(str(root / "scripts"))
    spec = importlib.util.spec_from_file_location(
        "cleanup_analytics", root / "scripts/cleanup_analytics.py"
    )
    command = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(command)
    now = datetime.now(UTC)
    async with factory() as db:
        db.add(AnalyticsProperty(id="p", tenant_id="a", name="Site"))
        await db.flush()
        db.add(
            AnalyticsSession(
                id="s",
                property_id="p",
                tenant_id="a",
                visitor="v",
                started_at=now - timedelta(days=3),
                last_seen=now - timedelta(days=3),
            )
        )
        await db.flush()
        db.add(
            AnalyticsEvent(
                tenant_id="a",
                property_id="p",
                session_id="s",
                visitor="v",
                event_id="expired",
                kind="pageview",
                path="/",
                created_at=now - timedelta(days=3),
            )
        )
        await db.commit()
    state = Runtime(AnalyticsSettings())
    disposed = []

    async def dispose():
        disposed.append(True)

    class Overrides:
        async def get_overrides(self, package):
            assert package == "sm_analytics"
            return {"retention_days": ("2", "int")}

    app = SimpleNamespace(
        state=SimpleNamespace(
            sm_analytics=state,
            sm=SimpleNamespace(
                db=SimpleNamespace(session_factory=factory, engine=SimpleNamespace(dispose=dispose))
            ),
        )
    )
    monkeypatch.setattr(command, "headless_settings", lambda: None)
    monkeypatch.setattr(command, "create_app", lambda _: app)
    monkeypatch.setattr(command, "SettingsStore", lambda _: Overrides())
    assert await command.run() == 0
    async with factory() as db:
        assert await db.scalar(select(func.count()).select_from(AnalyticsEvent)) == 0
    assert disposed == [True]
