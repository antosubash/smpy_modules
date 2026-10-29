# Access and originals

One policy object answers every question about a collection, and an image is
visible exactly when its collection is. Lists, counts, tiles, renditions,
groups, the review queue and the contracts all go through it in SQL, so a
caller never sees a count or a row they cannot open.

## Visibility

| Level | Who can view |
| --- | --- |
| `private` | The owner, users with a share, and `images.manage` |
| `internal` | Any signed-in member of the tenant, read-only |
| `public` | Anyone, anonymously, at `/images/c/{slug}` and the `/api/images/public/` routes |

`internal` is what the portal calls "public" (any logged-in user). A multi-tenant
request resolves a tenant only for an active member, and on a single-tenant host
every user is one, so "member of the tenant" is decided by the tenant binding
and not by an extra check. A private or internal collection is the 404 an unknown
slug gets on the public routes, whoever asks, the owner included.

Making a collection `internal` or `public` needs `images.publish` (or
`images.manage`) as well as being its owner.

## Who may do what

The framework's `sharing` module offers two share roles, `view` and `edit`, and
images grants nothing else through a share (a future role cannot widen it).

| Action | View | Edit share | Owner or `images.manage` |
| --- | --- | --- | --- |
| Open the collection, gallery, groups, map, prompts | yes | yes | yes |
| Rename, change the description | | yes | yes |
| Upload, import, edit an image's metadata | | yes | yes |
| Create and edit groups, assign images | | yes | yes |
| Create and edit prompts; review results | | yes | yes |
| Run a prompt on named images (`missing` or `stale`) | | yes | yes |
| Re-process one image (not `force`) | | yes | yes |
| See pipeline progress and step outputs | | yes | yes |
| Run a prompt over the whole collection, run with `all`, switch `auto_run` on | | | yes |
| Edit the pipeline, restart it, apply a preset, `force` a re-run | | | yes |
| Delete images or the collection | | | yes |
| Change visibility, manage shares | | | yes |

The portal's four roles (view, contribute, manage, own) collapse to this on
purpose: contribute and manage are both an `edit` share here, with the
destructive and cost-bearing actions kept for the owner. A portal user who needs
"manage" as a share needs a roles extension in `sharing`, not a table here.

## Sharing

Images builds its own share dialog on `/api/sharing/shares`, and a user picker,
`GET /api/images/collections/{id}/share-candidates?q=`. The picker is for the
owner and `images.manage`, uses the host's user directory (503
`user_directory_unavailable` without one), skips inactive users and the owner,
and on a multi-tenant host lists only members of the bound tenant.

**Purging a collection does not remove its share rows.** The janitor deletes the
collection's images and objects, but the framework's `sharing` module has no
per-resource cleanup hook yet, so the rows for a purged collection stay in its
table until that exists upstream. They grant nothing: the resource they name is
gone.

## Originals and display copies

When an image has a display copy (a step such as `anonymize` wrote one), every
viewer, gallery, rendition and public route serves the display copy. The
original is served by `GET /api/images/images/{id}/original` only to **the owner
and holders of `images.originals.view`**. `images.manage` alone does not open
it, and an edit share does not either. A refused request is a 403.

The public twin answers as the anonymous surface for everyone, so a protected
original is a 403 there even for its owner.

### Withheld images

A display mutator (the `anonymize` step, or a plugin's) must have finished
before the original or any rendition cut earlier can be trusted. Until it has,
the image is **withheld**: no display copy, no renditions, and the original is
protected. This is decided from stored state, never from the live registry
alone, so it fails closed:

- A withheld image is a **404 for everyone who may not edit the collection**,
  with the same body and negotiation (JSON, HTML or Inertia) as an id that does
  not exist, so the two cannot be told apart. Editors see it, marked as pending.
  That holds for writes too: a viewer's `PATCH`/`DELETE` of a withheld image or
  of a group whose images are all withheld (and `POST …/reprocess`) is that 404,
  not the 403 an image they can see gets.
- A viewer's counts, bounding box, gallery, groups, map points and PMTiles cover
  only display-safe images. An editor sees the raw numbers.
- A viewer's prompt-result list leaves out **group-level** results, because a
  group summary describes members that may be withheld.
- A viewer sees a step's name, status and error code but not its output or
  message. The pipeline overview is an editor's, so viewers have no progress
  read-out.
- A non-editor holding `images.originals.view` cannot read a withheld original;
  they can read it once processing has finished.

Uninstalling a plugin that provided the display mutator leaves the collection's
`protect_originals` set, so its displays are **withheld until the owner re-saves
the pipeline** without the missing step (a save with a display mutator beside an
uninstalled step is refused). This costs availability and is deliberate.
When a step publishes a new display copy, the runs of every other display
mutator, and of every uninstalled step that might be one, go back to pending, so
those results are lost until they are re-run.

## The public surface

Public routes are `GET` and `HEAD` only: the collection page, the gallery
(`/api/images/public/c/{slug}/images`), points, `map.pmtiles`, and the
`r/{size}`, `display` and `original` byte routes. An unknown slug, a foreign
tenant and an unbound tenant all get the one 404 body.

Every byte response can be revoked later (the collection goes private,
`protect_originals` is switched on, anonymization is enabled, a share is
withdrawn), so **every response revalidates**: nothing is `immutable` or carries
a `max-age`. Each one has a strong `ETag`, a cache must send `If-None-Match`
before reusing it, and the 304 is answered only after the full access and
redaction check, so a revoked image stops being served from caches too. The
cost is one small round trip (a 304) per reuse. `?v=` in a URL still names the
bytes, so a regenerated rendition or display copy gets a new URL.

Who may share the answer:

- `public, no-cache` only for a rendition or display copy of a public
  collection through the anonymous twin, when the request's tenant was not
  picked by anything request-specific (a multi-tenant host never qualifies).
- Everything else is `private, no-cache`.
- A protected original is `private, no-store` for everyone, the owner included.
- The map surfaces (points, `map.pmtiles`) follow the same split.
- Error answers on the public routes carry `no-store`.

`public_asset_base_url`, when set, makes public pages link renditions of public
collections to that origin (a bucket or CDN) instead of this application. It is
single-tenant only: on a multi-tenant host the public routes learn the tenant
from the request's organisation subdomain, which one CDN origin cannot carry,
so the setting is ignored there and a warning is logged at boot.

## Tenancy

Every router binds a tenant through `sm_images.tenancy`, a copy of records':
a single-tenant host uses `default`; a multi-tenant host uses the tenant the
framework resolved (`request.state.tenant_id`); none resolved is a 403
`tenant_required` for the console and API and a 404 for public routes. A tenant
resolved upstream always wins. Beat and recovery tasks enumerate tenants and
work under `tenant_context` for each.

## Background work runs under the starter's right

An import or regroup runs for hours. The right it was accepted under (owner, an
edit share, or `images.manage`) is recorded on the job and re-checked by the
worker when a runner starts, before each chunk and before each download batch.
When the right is gone the job is cancelled with `access_revoked`.

For a job started under `images.manage`, the worker does not re-resolve the
permission: it checks that the user still exists, is active and (multi-tenant)
is still a member. A manager who loses `images.manage` but keeps membership
therefore finishes a job already running.
