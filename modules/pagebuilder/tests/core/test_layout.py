"""Pin the Pagebuilder paths discovered by the host and framework."""

import ast
import importlib
import importlib.metadata
from pathlib import Path

import pagebuilder
from pagebuilder.module import PagebuilderModule


def test_root_contains_only_discovery_paths():
    root = Path(pagebuilder.__file__).parent
    assert {p.name for p in root.glob('*.py')} == {'__init__.py', 'module.py'}
    for area in ('core', 'content', 'media', 'scheduling', 'web'):
        tree = ast.parse((root / area / '__init__.py').read_text())
        assert len(tree.body) == 1 and isinstance(tree.body[0], ast.Expr)


def test_consumers_discover_package_resources():
    root = Path(pagebuilder.__file__).parent
    entry = next(ep for ep in importlib.metadata.entry_points(group='simple_module')
                 if ep.name == 'pagebuilder')
    assert entry.load() is PagebuilderModule
    assert importlib.import_module('pagebuilder.models').Page.__tablename__ == 'pagebuilder_pages'
    assert PagebuilderModule().locale_dirs()['pagebuilder'] == root / 'locales'
    for path in ('locales/en.json', 'locales/de.json', 'pages/PageEditor.tsx',
                 'static/widgets-base.css', 'py.typed'):
        assert (root / path).is_file()
    # The host loads registries by their root-level puck-blocks.ts filename.
    assert root / 'puck-blocks.ts' in root.parent.parent.glob('*/*/puck-blocks.ts')
    assert '../../*/*/pagebuilder-blocks.ts' in (root / 'puck-blocks.ts').read_text()
    assert importlib.import_module('pagebuilder.contracts.schemas').PageCreate
