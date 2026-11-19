"""Events installs, boots and answers without pagebuilder.

Pagebuilder is an optional extra: events reaches it only through ``pagebuilder.contracts.public``
(the site's 404, ``sm_events/integrations/pagebuilder.py``) and ships ``pagebuilder-blocks.ts`` for
hosts that have it. With the package unimportable the module loads, the public surface answers its
own pages, and the blocks' anonymous routes still serve.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

CODE = """
import asyncio, sys
sys.modules['pagebuilder'] = None
sys.modules['pagebuilder.contracts'] = None
sys.modules['pagebuilder.contracts.public'] = None
import sm_events.module, sm_events.web.endpoints.public
from sm_events.integrations import pagebuilder as bridge
assert bridge.available() is False and bridge._public() is None
loaded = [n for n, m in sys.modules.items() if n.startswith('pagebuilder') and m is not None]
assert not loaded, loaded

from tests.support.app import public_http

async def main():
    async with public_http() as http:
        gone = await http.get('/events/no-such-event')
        assert gone.status_code == 404, gone.status_code
        assert 'PageBuilder' not in gone.text
        blocks = await http.get('/api/events/public/calendars')
        assert blocks.status_code == 200 and blocks.json()['calendars'] == []

asyncio.run(main())
print('ok')
"""


def test_events_boots_and_serves_without_pagebuilder():
    done = subprocess.run(
        [sys.executable, "-c", CODE], cwd=ROOT, capture_output=True, text=True, check=False
    )
    assert done.returncode == 0, done.stderr[-2000:]
    assert done.stdout.strip().endswith("ok")
