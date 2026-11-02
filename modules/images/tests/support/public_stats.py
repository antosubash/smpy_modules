"""Seeding for the ``/api/images/public/stats`` tests (#88).

Shared by ``test_public_stats`` (what is counted) and
``test_public_stats_bounded`` (where counting stops), which would not both fit
under the 300-line cap in one file.
"""

from __future__ import annotations

import uuid

from sm_images.core.tenancy import DEFAULT_TENANT, tenant_scope
from sm_images.models import Rendition, StepRun
from sm_images.models.enums import StepStatus

from tests.support.access import OWNER, collection, image

URL = "/api/images/public/stats"


async def seed(session_factory, specs, tenant=DEFAULT_TENANT):
    """``specs``: ``(visibility, trashed, n_ready, n_located, extra)`` per collection;
    ``extra`` gives the collection a blur pipeline and adds the images the gallery
    skips. Returns the collections."""
    made = []
    with tenant_scope(tenant):
        async with session_factory() as s:
            for visibility, trashed, ready, located, extra in specs:
                coll = collection(f"s-{uuid.uuid4().hex[:8]}", visibility, OWNER)
                if extra:
                    coll.pipeline_config = {"steps": {"acme.blur": {}}}
                s.add(coll)
                await s.flush()
                for i in range(ready):
                    at = {"lat": 1.0, "lng": 2.0} if i < located else {}
                    await _image(s, coll, f"r{i}.jpg", settled=bool(extra), **at)
                if extra:
                    await _image(s, coll, "trashed.jpg", settled=True, is_deleted=True)
                    await _image(s, coll, "held.jpg", settled=False, lat=1.0, lng=2.0)
                    await _image(s, coll, "bare.jpg", settled=True, small=None)
                    await _image(s, coll, "stale.jpg", settled=True, display_generation=1)
                coll.is_deleted = trashed
                made.append(coll)
            await s.commit()
    return made


async def _image(s, coll, name, *, settled, small=0, **kw):
    pic = image(coll, name, **kw)
    s.add(pic)
    await s.flush()
    if small is not None:
        s.add(Rendition(image_id=pic.id, size="small", storage_key=f"k/{name}.s", width=1,
                        height=1, source_generation=small))  # fmt: skip
    if settled:
        s.add(StepRun(image_id=pic.id, step="acme.blur", status=StepStatus.COMPLETED,
                      step_version=1))  # fmt: skip


async def stat(client, metric, slug=None, **kw) -> dict:
    """The whole ``{value, capped}`` answer, asserting a 200."""
    params = {"metric": metric} | ({"collection": slug} if slug else {})
    got = await client.get(URL, params=params, **kw)
    assert got.status_code == 200, got.text
    return got.json()
