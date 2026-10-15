# Pagebuilder: finish what the editor already promises

Status: approved 2026-10-15 (next-phase plan, Phase 1).

Three things the page editor offers but the public site ignores, plus the
Markdown gaps left over from #66.

## 1. `meta_title` reaches `<title>`

The SEO panel says "leave blank to use the page title"; the public page always
used `page.title`. `render_public_page` and the admin preview now send
`page.meta_title or page.title` as `title`, which `PublicPage` already uses for
both `<title>` and `og:title`. No frontend change.

## 2. Nav flags reach the header and footer

`show_in_header_nav` / `show_in_footer` were stored, edited and snapshotted, but
nothing read them.

- **Server** — `pagebuilder.site_nav.site_nav(db, prefix, locale)` returns
  `{"header": [...], "footer": [...]}`, each entry `{"label": title, "href": path}`,
  for published, untrashed pages *in the page's locale* with the flag set, ordered
  by lower-cased title then id. The href goes through `public_claims.resolve` (one batched
  call), so a page another module has claimed links to the claimant's address,
  and otherwise through `locales.public_path`.
- **Props** — `render_public_page` and the admin preview send it as `site_nav`.
- **ETag** — the nav list is part of the digest. Flagging, unflagging,
  publishing or renaming *another* page changes every page's chrome, and neither
  this page's `updated_at` nor the layout's would move.
- **Client** — `PublicPage` puts `site_nav` in a React context around the
  layout `<Render>`s. `SiteHeader` appends header pages to its `navItems` and
  `SiteFooter` appends footer pages to its `links`.
- **Order stays the layout's** (the model docstring's rule): flagged pages come
  *after* the layout's own entries, and a page whose href the layout already
  links to (top level or a dropdown child) is not repeated. An author who wants
  a page somewhere specific adds it in the layout editor.
- The layout editor has no provider, so it shows only the layout's own links.
- A layout with no SiteHeader/SiteFooter block shows no flagged pages. The flags
  feed those widgets, not a new chrome.

Rejected: removing the flags (the UI and API already carry them), and a separate
"pages nav" block (a second way to build the same nav).

## 3. Markdown

- **Numbered lists**: `1. x` / `1) x` lines parse as `ol`, nesting like bullets,
  with `start` taken from the first number. A switch between `-` and `1.` at
  the outermost level starts a new list. A nested list takes the kind of its
  first item.
- **The HTML export keeps links and images**: link/image parsing moves to a
  pure `utils/markdown-links.ts` shared by `rich-text.tsx` and
  `inlineMarkdownToHtml`, with the same safety rules: unsafe hrefs and image
  sources stay literal text.
- **Long words wrap**: rich text blocks, Section intro headings and
  DefinitionList rows get `overflow-wrap: anywhere` (`break-words` does not
  lower min-content width, so it fails in an `items-start` column), so a long
  URL wraps instead of widening the page.
- **The header nav wraps**: flagged pages can add any number of entries with
  any title, so the desktop nav wraps and truncates each label at 16rem, and
  footer links wrap anywhere.

## Testing

pytest for `site_nav` (locale, published-only, trash, claims, order) and for
the view (title fallback, `site_nav` prop, ETag changes when another page is
flagged). vitest for the parser, the HTML export and the widgets' merge. One
Playwright spec: flag a page, assert it appears in the public header/footer,
and assert `<title>` is the meta title.
