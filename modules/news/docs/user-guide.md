# News user guide

Three permissions decide what you can do:

- **`news.view`** — see the **Articles** list.
- **`news.edit`** — create and edit articles, manage categories and tags, open
  **Trash**, **Search everything** and the preview, and submit for review.
- **`news.publish`** — publish, unpublish, approve or send back a submission,
  schedule, and delete for good. Granted separately from `news.edit` so a host
  can require a review step: an author with `news.edit` alone can only
  **Submit for review**.

The admin screens are under **News** in the sidebar (**Articles**,
**Categories**, **Trash**) and **Find → Search everything**. They live under
`/admin/news`; the public archive is at `/news/`.

## Articles (`/admin/news/`)

The header reads "{published} published · {draft} drafts · public at
/news/:slug". Above the rows:

- **Search headline or slug** — narrows the list (it also matches the summary
  and tags).
- **Filter by status** — **All**, **Draft**, **Published**, **Undated**.
  *Undated* is an article with no display date, draft or published, so the
  four counts do not add up to *All*.
- **Filter by category** and, on a multilingual site, **Filter by language**.

Undated articles sort first (they are work in progress), then newest first.
Pinning does not reorder this list: it only breaks a tie between two articles
with the same display date (readers' archives put pinned articles first). Twenty load at a time; **Load more** fetches the next batch.

Each row shows its status: **Published · {date}**, **Published · no date**,
**Pending review**, **Draft · dated {date}** or **Draft · undated**. A live
article whose draft has moved on since it was published is also marked
**Unpublished edits** — readers are still served the older version.

Click the category/date value to edit both inline (**Save** / **Cancel**).
**Edit** opens the article screen; the **···** menu offers **Publish now**
(drafts), **View on the site** (published), **Edit the body**, **Edit category
and date**, and either **Move to trash** or, if you hold `news.publish`,
**Delete** (permanent).

### Creating an article

**New article** opens a dialog with four fields, all changeable later except
the language:

| Field | What it means |
|---|---|
| **Headline** | Required. |
| **Language** | Only on a multilingual site. Fixed once the article exists. |
| **URL** | Leave blank and one is made from the headline (`my-title`, then `my-title-2` if taken). A URL you type is used exactly; if it is taken you get an error instead of a silent rename. Lowercase letters, numbers and hyphens. |
| **Category** | Or **Uncategorised**. |
| **Display date** | The date shown on the article. It does **not** schedule a publish. Clearing it makes the article undated work in progress. |

**Create draft** creates the article as a draft and opens its body canvas.

## The article screen (`/admin/news/articles/{id}/edit`)

Everything about an article except its body, saved with one **Save** button.
The header links **Preview** (the draft rendered exactly as readers will see
it, marked **Preview**), **View live** when published, and **Publish now**.
A card, **The body has its own canvas**, links to **Edit the body**.

| Field | What it means |
|---|---|
| **Headline** | Also the page `<title>`, the card title and the article's `<h1>`. |
| **URL** | Changing it moves the article. The old address keeps working: a rename records a redirect. |
| **Category** | One per article. |
| **Tags** | Many per article; a new name creates the tag. |
| **Display date** / **Time** | The date readers see. Independent of status. |
| **Author** | Free-text byline. Readers can open an archive of everything under it. |
| **Pin to the top of listings** | Sorts before the date without changing it. |
| **Show in feed blocks** | Off keeps the article at its own URL but out of the archive, the RSS feed, feed blocks and category/tag/author pages. |

If someone else saved the article since you loaded it, saving is refused with
"This article was changed somewhere else. Reload to get the latest version,
then make your change again."

### Review

What the **Review** card shows depends on status and your permissions:

- **Draft, you hold `news.publish`** — "You can publish directly. Submitting
  instead puts it in front of another reviewer." plus **Submit for review**.
- **Draft, `news.edit` only** — "Hand this to someone who can publish it." and
  **Submit for review**.
- **Pending review, `news.publish`** — **Approve** (approves *and* publishes in
  one action, so open **Preview** first) and **Send back**, which asks for a
  **Reason**. The note appears on the body canvas as **Sent back:** and clears
  when the author resubmits.
- **Pending review, `news.edit` only** — "With a reviewer…".
- **Published, `news.publish`** — **Unpublish**, which takes the article off
  the site and keeps the draft and its history.

### Schedule

Only shown to `news.publish` holders. **Go live** publishes a draft by itself;
**Come down** unpublishes a published article by itself. Both are optional,
clearing one cancels it, and **Go live** must be before **Come down**. The
change happens within one scheduler interval (30 seconds by default) of the
time you set, not exactly on it. **Save schedule** stores it.

Publishing, approving, unpublishing or sending back by hand cancels a pending
**Go live**. If both times pass while no scheduler is running, the article
stays a draft and both times are cleared.

### Search & sharing

| Field | What it means |
|---|---|
| **Summary** | Meta description, link-preview text, and the excerpt in the archive and feeds. |
| **Share image URL** | Link-preview image and the cover at the top of the article. A full `http(s)://` address or a path starting with `/`. |
| **Canonical URL** | Only for an article republished from elsewhere. Blank uses the article's own address. |
| **Allow search engines to index it** | Off sends `noindex,nofollow` and drops it from the sitemap; the article stays readable by link. |

**Save search settings** stores them.

### Languages

On a site with more than one content language the **Languages** card lists
the article's translations (**Draft**, **Pending review**, **Live**). **Add
translation** creates a sibling article in another language as a draft,
copying the category, byline, display date, pin and feed setting; the
headline starts untranslated. There is no "change language" — an article's
language is fixed.

### History

One row per status change: **Submitted for review**, **Approved and
published**, **Sent back**, **Published**, **Taken down**. **Restore this
version** copies that version's body, headline, summary and share image back
into the draft. It does not publish.

### Deleting

At the bottom: **Move article to trash** if you hold `news.edit` only, or
**Delete article** (permanent) instead if you also hold `news.publish`.

## The body canvas (`/admin/news/articles/{id}/body`)

A block editor that autosaves into the draft about 1.5 seconds after you stop
typing. Autosave never touches the URL or status, and never changes what
readers see. **Save draft** saves immediately; **Publish** (or **Update
published** on a live article) publishes the draft — this needs
`news.publish`. If another tab saved first you see an error with **Reload**.

The palette, by group:

| Group | Blocks |
|---|---|
| Text | Heading, Paragraph, List, Pull quote, Q&A |
| Set apart | Key points, Callout, Definitions, Sources, Read next, Contents |
| Media | Image, Gallery, Before / after, Video file, Audio clip, Embed (video, map…) |
| Data | Table, Chart, Key figures, Code, Timeline |
| Layout | Divider |

List-like blocks take one item per line (e.g. Key figures: `21 | sensors
installed`). **Callout** has a **Correction** kind. **Read next** lists live
articles (optionally one category), excluding the one you are in. **Contents**
lists the article's Heading blocks. Images take a URL — there is no media
picker.

## Categories (`/admin/news/categories`)

"One category per article, many tags." Type a name and **Add**. Each row can
be **Rename**d (name and slug; renaming carries its articles with it) and
dragged to set the order of the public filter. **Delete** asks **Move its
articles to** another category or **Uncategorised**; no article is deleted.
**Uncategorised** is a system row that cannot be renamed or deleted. A
category typed on an article but never added here shows with **Add to list**.

**Tags** on the same screen: **Find or create a tag**, or select two chips and
**Merge** (the second one selected is folded into the first and removed).
Renaming and deleting a tag are API-only (see the API reference).

## Trash (`/admin/news/trash`)

Binned articles are off the public site and out of every list, but keep their
URL claimed so nothing else can take it. **Restore** puts one back exactly as
it was, status included. **Delete for good** (`news.publish` only) removes the
article, its body, tags and redirects permanently and frees its URL.

## Search everything (`/admin/search`)

Searches headlines, slugs, summaries, body text (drafts included), categories
and tags of articles. Where pagebuilder is installed it adds **Pages** and
**Media** sections, each with an "N more →" link into pagebuilder's screens.
Filter with **Everything**, **Articles**, **Pages**, **Media**.

## Snapshots and restores (pagebuilder's Import / Export)

On a site running pagebuilder, a snapshot taken under **Site → Import /
Export** also holds the news content: every article that is not in the trash
(drafts, scheduled and published, in every language), categories, tags and
old-address redirects. Revision history, trashed articles and rejection notes
are not carried. A downloaded bundle includes drafts and bylines, so treat it
like a database export.

Restoring one shows a **News** card on the review screen: new articles,
articles overwritten, trashed articles brought back, articles moved back to
their snapshot address, unchanged articles, articles not in the snapshot (kept
— a restore never deletes), categories, tags, and redirects dropped because
their article is gone. Applying it restores the articles together with the
pages, in one step that is undone by restoring the automatic snapshot taken
just before.

What you can do depends on your news permissions, on top of pagebuilder's:

- Your snapshot includes news only if you hold `news.edit`; without it the
  snapshot says news was left out, and restoring it leaves the articles alone.
- You see article titles in a staged restore only with `news.edit`; without it
  the card shows counts and says what you would need.
- Restoring the articles takes `news.edit` and `news.publish`, both from the
  person who stages the restore and from the approver. Without them the pages
  restore and the plan says news was left out.

## What readers see

- `/news/` — the archive, newest first (pinned first), twelve per page, with
  **← Newer** / **Older →** and **Subscribe by RSS**.
- `/news/category/{slug}`, `/news/tag/{slug}`, `/news/author/{slug}` — the same
  archive narrowed. The search box narrows the page you are on; it matches
  headline, URL, summary and tags, not the body.
- `/news/{slug}` — one published article. A draft, one waiting for review or
  for its scheduled time, a trashed article and an unknown slug all answer the
  same 404: on a site that also runs pagebuilder, the site's own "This page
  doesn't exist" page inside its header and footer, in the address's language
  ("Diese Seite gibt es nicht" on `/de/news/…`). An old address of a renamed
  article still forwards to the new one.
- On a multilingual site other languages are prefixed (`/de/news/…`), and an
  article with live translations offers **Read this article in another
  language**.
