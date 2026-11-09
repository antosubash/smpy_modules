"""Pin the News package paths its consumers discover by name."""

import importlib
import importlib.metadata
from pathlib import Path

import news
from news.module import NewsModule

# Until 0.0.17 the old directories hold nothing but moved-path stubs (#319).
_STUB = ("/** @deprecated Moved to ", "/* @deprecated Moved to ")


def _only_stubs(path: Path) -> bool:
    files = [f for f in path.rglob("*") if f.is_file() and "__pycache__" not in f.parts]
    return bool(files) and all(f.read_text(encoding="utf-8").startswith(_STUB) for f in files)


def test_package_root_contains_only_discovery_paths():
    root = Path(news.__file__).parent
    assert {p.name for p in root.glob("*.py")} == {"__init__.py", "module.py"}
    dirs = [p for p in root.iterdir() if p.is_dir() and p.name != "__pycache__"]
    assert {p.name for p in dirs if not _only_stubs(p)} == {
        "content", "contracts", "core", "integrations", "locales", "models", "pages",
        "scheduling", "ui", "web",
    }
    for area in ("content", "core", "scheduling", "ui", "web"):
        initializer = root / area / "__init__.py"
        if initializer.exists():
            import ast
            assert len(ast.parse(initializer.read_text()).body) == 1


def test_consumers_discover_module_models_pages_locales_and_blocks():
    entry = next(ep for ep in importlib.metadata.entry_points(group="simple_module")
                 if ep.name == "news")
    assert entry.load() is NewsModule
    assert importlib.import_module("news.models").NewsArticle.__tablename__ == "news_articles"
    root = Path(news.__file__).parent
    assert NewsModule().locale_dirs()["news"] == root / "locales"
    assert (root / "locales" / "en.json").is_file()
    assert (root / "locales" / "de.json").is_file()
    assert (root / "pages" / "NewsList.tsx").is_file()
    # pagebuilder discovers this module's blocks using its root-level glob.
    blocks = list(root.parent.parent.glob("*/*/pagebuilder-blocks.ts"))
    assert root / "pagebuilder-blocks.ts" in blocks
    assert "NewsFeed" in (root / "pagebuilder-blocks.ts").read_text()
    assert importlib.import_module("news.contracts.schemas").ArticleRead
