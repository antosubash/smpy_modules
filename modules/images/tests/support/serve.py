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
from sm_images.models import Image, Rendition, Visibility
from sm_images.serving import cache
from sm_images.storage import ImageStore
from sm_images.storage import keys as storage_keys
from sm_images.tenancy import DEFAULT_TENANT, tenant_scope

from tests.support.access import EDITOR, OWNER, collection, share

ATTEMPT = "a1"
BLUR = "acme.blur"
"""The step every seeded display copy is recorded as written by."""


def blob(tag: str, size: int = 2048) -> bytes:
    head = f"{tag}:".encode()
    return (head * (size // len(head) + 1))[:size]


@dataclass
class Served:
    ids: dict[str, uuid.UUID] = field(default_factory=dict)
    slugs: dict[str, str] = field(default_factory=dict)
    bytes: dict[str, bytes] = field(default_factory=dict)
    keys: dict[str, str] = field(default_factory=dict)
    generations: dict[str, int] = field(default_factory=dict)

    def version(self, label: str, tail: str) -> str | None:
        """The ``?v=`` the current representation behind *tail* answers to."""
        gen = self.generations[label]
        if tail.startswith("r/"):
            key = self.keys.get(f"{label}.{tail[2:]}")
        elif tail == "display":
            key = self.keys.get(f"{label}.display") or self.keys[f"{label}.original"]
        else:
            return None
        return None if key is None else cache.version(gen, key)

    def _tail(self, label: str, tail: str, versioned: bool) -> str:
        v = self.version(label, tail) if versioned and "?" not in tail else None
        return tail if v is None else f"{tail}?v={v}"

    def url(self, coll: str, name: str, tail: str, *, versioned: bool = True) -> str:
        label = f"{coll}.{name}"
        return f"/api/images/images/{self.ids[label]}/{self._tail(label, tail, versioned)}"

    def public_url(
        self, coll: str, name: str, tail: str, slug: str | None = None, *, versioned: bool = True
    ) -> str:
        label = f"{coll}.{name}"
        image_id = self.ids[label]
        path = self._tail(label, tail, versioned)
        return f"/api/images/public/c/{slug or self.slugs[coll]}/images/{image_id}/{path}"


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
            display_step=BLUR if blurred else None,
            display_step_version=1 if blurred else None,
            filename=f"{label}.jpg",
            content_type="image/jpeg",
            size_bytes=len(out.bytes[f"{label}.original"]),
        )
    )
    await session.flush()
    generation = 1 if blurred else 0
    session.add(
        Rendition(
            image_id=image_id,
            size="small",
            storage_key=objects["small"],
            width=8,
            height=8,
            source_generation=generation,
        )
    )
    out.ids[label] = image_id
    out.generations[label] = generation


async def seed_gallery(session_factory: Any, backend: Any, **coll_kw: Any) -> Served:
    """Seed in the bound tenant - or in ``default`` for an ``unbound_tenant``
    test, which binds nothing so its requests see no tenant bound upstream."""
    if current_tenant_id.get() is None:
        with tenant_scope(DEFAULT_TENANT):
            return await _seed(session_factory, backend, **coll_kw)
    return await _seed(session_factory, backend, **coll_kw)


async def _seed(session_factory: Any, backend: Any, **coll_kw: Any) -> Served:
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
