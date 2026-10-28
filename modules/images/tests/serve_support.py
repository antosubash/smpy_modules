"""A served gallery: collections, images and their stored objects, for the route tests.

``seed_gallery`` writes, in the bound tenant:

* ``pub`` (public) and ``priv`` (private, edit-shared with eddie), both olga's;
* in each, ``plain`` (no display copy: the original is what everyone sees) and
  ``blurred`` (a display copy, so the original is protected);
* a ``small`` rendition of every image.

Every object's bytes are distinct, so a test can tell which one was served.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from simple_module_db.listeners import current_tenant_id
from sm_images import storage_keys
from sm_images.models import Image, Rendition, Visibility
from sm_images.storage import ImageStore

from tests.access_support import EDITOR, OWNER, collection, share

ATTEMPT = "a1"


def blob(tag: str, size: int = 2048) -> bytes:
    head = f"{tag}:".encode()
    return (head * (size // len(head) + 1))[:size]


@dataclass
class Served:
    ids: dict[str, uuid.UUID] = field(default_factory=dict)
    slugs: dict[str, str] = field(default_factory=dict)
    bytes: dict[str, bytes] = field(default_factory=dict)
    keys: dict[str, str] = field(default_factory=dict)

    def url(self, coll: str, name: str, tail: str) -> str:
        return f"/api/images/images/{self.ids[f'{coll}.{name}']}/{tail}"

    def public_url(self, coll: str, name: str, tail: str, slug: str | None = None) -> str:
        image_id = self.ids[f"{coll}.{name}"]
        return f"/api/images/public/c/{slug or self.slugs[coll]}/images/{image_id}/{tail}"


async def _image(
    session: Any, store: ImageStore, out: Served, coll: Any, label: str, *, blurred: bool
) -> None:
    tenant = current_tenant_id.get()
    image_id = uuid.uuid4()
    cid, iid = str(coll.id), str(image_id)
    objects = {"original": storage_keys.original_key(tenant, cid, iid, "jpg")}
    if blurred:
        objects["display"] = storage_keys.display_key(tenant, cid, iid, 1, ATTEMPT)
    objects["small"] = storage_keys.rendition_key(tenant, cid, iid, "small", 1, ATTEMPT)
    for what, key in objects.items():
        data = blob(f"{label}.{what}")
        await store.put(key, data, content_type="image/jpeg", size=len(data))
        out.bytes[f"{label}.{what}"] = data
        out.keys[f"{label}.{what}"] = key
    session.add(
        Image(
            id=image_id,
            collection_id=coll.id,
            storage_key=objects["original"],
            display_key=objects.get("display"),
            display_generation=1 if blurred else 0,
            filename=f"{label}.jpg",
            content_type="image/jpeg",
            size_bytes=len(out.bytes[f"{label}.original"]),
        )
    )
    await session.flush()
    session.add(
        Rendition(image_id=image_id, size="small", storage_key=objects["small"], width=8, height=8)
    )
    out.ids[label] = image_id


async def seed_gallery(session_factory: Any, backend: Any, **coll_kw: Any) -> Served:
    store = ImageStore(backend)
    out = Served()
    pub = collection(f"pub-{uuid.uuid4().hex[:6]}", Visibility.PUBLIC, OWNER, **coll_kw)
    priv = collection(f"priv-{uuid.uuid4().hex[:6]}", Visibility.PRIVATE, OWNER, **coll_kw)
    async with session_factory() as s:
        s.add_all([pub, priv])
        await s.flush()
        s.add(share(priv, EDITOR, "edit"))
        for key, coll in (("pub", pub), ("priv", priv)):
            out.slugs[key] = coll.slug
            for name, blurred in (("plain", False), ("blurred", True)):
                await _image(s, store, out, coll, f"{key}.{name}", blurred=blurred)
        out.ids["pub"], out.ids["priv"] = pub.id, priv.id
        await s.commit()
    return out
