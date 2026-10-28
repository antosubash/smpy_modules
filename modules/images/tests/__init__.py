"""Makes this test directory a package on purpose.

Without it, pytest's prepend import mode inserts this directory at
``sys.path[0]`` when it loads ``conftest.py`` — and because it sorts after every
sibling, it wins. The news and pagebuilder suites do a bare
``from conftest import PNG_BYTES`` that only works while *their* directory is
first, so a root-level ``pytest`` collected 19 errors the moment this suite
existed. As a package, pytest imports this conftest as ``tests.conftest`` and
leaves ``sys.path`` alone. CI runs each module from its own directory and never
sees this; the root run is what ``testpaths`` keeps honest.
"""
