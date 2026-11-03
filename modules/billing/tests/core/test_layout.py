"""Consumer discovery remains stable while Billing follows the module layout."""

import importlib
import importlib.metadata
from pathlib import Path

from sm_billing import contracts
from sm_billing.cli import app
from sm_billing.module import BillingModule


def test_package_root_contains_only_discovery_paths():
    root = Path(contracts.__file__).parents[1]
    assert {p.name for p in root.glob("*.py")} == {"__init__.py", "module.py", "cli.py"}
    assert {p.name for p in root.iterdir() if p.is_dir() and p.name != "__pycache__"} == {
        "contracts", "core", "locales", "metering", "models", "pages", "plans",
        "providers", "subscriptions", "ui", "web",
    }


def test_consumers_discover_module_cli_models_and_locales():
    module = next(ep for ep in importlib.metadata.entry_points(group="simple_module")
                  if ep.name == "billing")
    cli = next(ep for ep in importlib.metadata.entry_points(group="simple_module_cli.cli_plugins")
               if ep.name == "billing")
    assert module.load() is BillingModule
    assert cli.load() is app
    assert importlib.import_module("sm_billing.models").Plan.__tablename__ == "billing_plan"
    locales = BillingModule().locale_dirs()["billing"]
    assert (locales / "en.json").is_file()
    assert (locales / "de.json").is_file()
    assert (locales.parent / "pages" / "Billing.tsx").is_file()
