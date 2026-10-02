/** The bar that says "this is not what readers see".
 *
 * The preview renders `PublicArticle` — the reader's own screen, over the
 * draft body — because a preview that looked different from the real thing
 * would be worthless to the reviewer relying on it. That fidelity is exactly
 * what makes this bar necessary: without it the only way to tell a preview
 * from the live article is the URL.
 *
 * In `components/`, not `pages/`. Every file in a module's `pages` directory
 * is registered as an Inertia page by `import.meta.glob` — the path is the
 * page name — and a banner is not a screen.
 */

/** What the preview route sends about the document being previewed.
 *
 * `has_unpublished_changes` is true only when the article is genuinely live
 * *and* its draft has diverged from the snapshot readers are served — see
 * `_preview_state` in `endpoints/views.py`. A draft holding an old snapshot
 * from before it was taken down is not that case, and saying so would be a
 * sentence about readers who are not being served anything.
 */
export interface ArticlePreviewState {
  status: 'draft' | 'submitted_for_review' | 'published';
  has_unpublished_changes: boolean;
  /** The public address, when one actually resolves. `null` otherwise — the
   *  viewer 404s a draft, so a link offered here would be a link to nothing. */
  live_url: string | null;
  editor_url: string;
}

/** Which of the four things this is, in the reader's terms rather than the
 *  workflow's: what matters to whoever is looking is whether readers can see
 *  it, not which enum member the row holds. */
function reading(preview: ArticlePreviewState): { state: string; detail: string } {
  if (preview.status === 'draft') {
    return { state: 'Draft', detail: 'Readers cannot see this yet.' };
  }
  if (preview.status === 'submitted_for_review') {
    return {
      state: 'Pending review',
      detail: 'Readers cannot see this until it is approved.',
    };
  }
  if (preview.has_unpublished_changes) {
    return {
      state: 'Unpublished changes',
      detail: 'Readers are still being served the published version.',
    };
  }
  return { state: 'Published', detail: 'This matches what readers are served.' };
}

export function PreviewBanner({ preview }: { preview: ArticlePreviewState }) {
  const { state, detail } = reading(preview);

  return (
    // Inverted rather than tinted: it has to read as chrome at a glance, in
    // either theme, without borrowing a colour the article itself might use.
    // Sticky, because the thing it is disclaiming scrolls.
    <aside
      aria-label="Preview"
      className="sticky top-0 z-50 bg-foreground text-background print:hidden"
    >
      <div className="mx-auto flex max-w-3xl flex-wrap items-center gap-x-3 gap-y-1 px-4 py-2 text-sm">
        <span className="rounded bg-background/20 px-1.5 py-0.5 text-xs font-semibold uppercase tracking-wide">
          Preview
        </span>
        <span className="font-medium">{state}</span>
        <span className="text-background/70">{detail}</span>
        <span className="ml-auto flex items-center gap-3">
          <a className="underline underline-offset-2" href={preview.editor_url}>
            Back to the editor
          </a>
          {/* Only when the public URL resolves. The two answer different
              questions for a published article with pending edits — what is on
              screen, and what readers actually have — and both matter. */}
          {preview.live_url && (
            <a
              className="underline underline-offset-2"
              href={preview.live_url}
              target="_blank"
              rel="noopener noreferrer"
            >
              View live
            </a>
          )}
        </span>
      </div>
    </aside>
  );
}
