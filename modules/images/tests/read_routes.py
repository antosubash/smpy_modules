"""Every read route images serves, for the leak test (``test_read_routes.py``).

**Later tasks append here** - a new ``GET`` under ``/api/images`` (or ``/images``)
without an entry fails ``test_every_get_route_is_listed``. An entry is
``(method, path_template, needs)``:

* ``"collection"`` - the path names a collection the caller must be allowed to
  see (``{collection_id}``); a stranger gets 404, never 403 and never data.
* ``"image"`` - the path names an image inside such a collection
  (``{image_id}``, and ``{collection_id}`` if it has one); same expectation.
* ``"list"`` - returns rows; a stranger gets 200 and the private collection's
  slug, id and image id appear nowhere in the body.
* ``"public"`` - anonymous surface (``{slug}``); anonymous gets 404.

Placeholders: ``{collection_id}``, ``{image_id}``, ``{slug}``, ``{size}`` (a
rendition the seeded image has). A route that
needs a query string appends it to the template.
"""

from __future__ import annotations

from typing import NamedTuple

COLLECTION = "collection"
IMAGE = "image"
LIST = "list"
PUBLIC = "public"


class ReadRoute(NamedTuple):
    method: str
    path: str
    needs: str


READ_ROUTES: list[ReadRoute] = [
    ReadRoute("GET", "/api/images/collections", LIST),
    ReadRoute("GET", "/api/images/collections/{collection_id}", COLLECTION),
    ReadRoute("GET", "/api/images/collections/{collection_id}/share-candidates", COLLECTION),
    ReadRoute("GET", "/api/images/collections/{collection_id}/images", COLLECTION),
    ReadRoute("GET", "/api/images/images/{image_id}", IMAGE),
    ReadRoute("GET", "/api/images/collections/{collection_id}/pipeline", COLLECTION),
    ReadRoute("GET", "/api/images/images/{image_id}/r/{size}", IMAGE),
    ReadRoute("GET", "/api/images/images/{image_id}/display", IMAGE),
    ReadRoute("GET", "/api/images/images/{image_id}/original", IMAGE),
    ReadRoute("GET", "/api/images/public/c/{slug}/images/{image_id}/r/{size}", PUBLIC),
    ReadRoute("GET", "/api/images/public/c/{slug}/images/{image_id}/display", PUBLIC),
    ReadRoute("GET", "/api/images/public/c/{slug}/images/{image_id}/original", PUBLIC),
]

NOT_A_LEAK_SURFACE: frozenset[str] = frozenset()
"""``"GET /path"`` strings that are deliberately not in :data:`READ_ROUTES`
(a health probe, say). Each needs a reason beside it."""
