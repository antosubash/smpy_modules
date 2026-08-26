import type { Page } from '@playwright/test';

import { csrfHeader, uniqueSlug } from './helpers';

/**
 * Seed an article, for the specs that need one to look at.
 *
 * Shared because it used to be copied into nine spec files, and every copy did
 * the same three-step dance: POST a page to pagebuilder, publish that page,
 * then POST news metadata pointing at its id. An article is one row now, so the
 * dance collapses to one request — and putting it here means the next change to
 * the shape is one edit rather than nine.
 *
 * `publish` defaults to false because a newly created article is a draft, which
 * is what the admin list is mostly about. Specs that need a public URL to hit
 * ask for it.
 */
export async function seedArticle(
  page: Page,
  {
    prefix = 'e2e',
    title,
    titlePrefix,
    category = '',
    publishedAt = null,
    author = '',
    publish = false,
    body,
  }: {
    prefix?: string;
    title?: string;
    /** Names the article `"<titlePrefix> <slug>"`, which is how most specs
     *  locate a heading. Ignored when `title` is given outright. */
    titlePrefix?: string;
    category?: string;
    publishedAt?: string | null;
    author?: string;
    publish?: boolean;
    /** Block document. Omitted, the article opens on an empty canvas. */
    body?: Record<string, unknown>;
  } = {},
): Promise<{ articleId: number; slug: string; title: string; url: string }> {
  const headers = await csrfHeader(page);
  const slug = uniqueSlug(prefix);
  const resolvedTitle = title ?? (titlePrefix ? `${titlePrefix} ${slug}` : slug);

  const created = await page.request.post('/api/news/articles', {
    headers,
    // The slug is passed explicitly rather than derived from the title: these
    // specs locate rows by it, so it has to be the value they already hold.
    data: { title: resolvedTitle, slug, category, published_at: publishedAt, author },
  });
  const article = (await created.json()) as { id: number; url: string };

  if (body) {
    await page.request.put(`/api/news/articles/${article.id}/body`, {
      headers,
      data: { draft_data: body },
    });
  }
  if (publish) {
    await page.request.post(`/api/news/articles/${article.id}/publish`, {
      headers,
      data: {},
    });
  }
  return { articleId: article.id, slug, title: resolvedTitle, url: article.url };
}

/** A block document with one paragraph — enough for the viewer to render. */
export function paragraphBody(text: string): Record<string, unknown> {
  return {
    root: { props: { title: text } },
    content: [{ type: 'Paragraph', props: { text, lead: false } }],
    zones: {},
  };
}

/**
 * A body with some of each block, for the walkthrough to publish and read back.
 *
 * Seeded through the body API rather than dragged onto the canvas, which is the
 * convention the rest of this suite already follows — Puck's palette is
 * dnd-kit, and driving it under Playwright is flaky enough that it would be the
 * only thing a walkthrough ever failed on. What the walkthrough *does* drive
 * through the real canvas is the inspector: seeding proves nothing about
 * whether editing a block saves, and that is the part worth watching.
 */
export function walkthroughBody(lead: string): Record<string, unknown> {
  return {
    root: { props: { title: lead } },
    content: [
      { type: 'Paragraph', props: { id: 'p-lead', text: lead, lead: true } },
      { type: 'Heading', props: { id: 'h-1', text: 'What changed', level: '2' } },
      {
        type: 'Paragraph',
        props: { id: 'p-body', text: 'Placeholder body copy.', lead: false },
      },
      {
        type: 'Quote',
        props: { id: 'q-1', text: 'One row, one owner.', attribution: 'The migration' },
      },
      {
        type: 'List',
        props: { id: 'l-1', items: 'Own table\nOwn viewer\nOwn sitemap', ordered: false },
      },
      {
        type: 'KeyPoints',
        props: {
          id: 'k-1',
          title: 'What you need to know',
          items: 'All four plots report hourly\nThe archive is its own module',
        },
      },
      {
        type: 'Table',
        props: {
          id: 't-1',
          rows: 'Site | Sensors | Live\nNorth | 12 | yes\nSouth | 9 | yes',
          header: true,
          caption: 'Coverage at the end of the rollout.',
        },
      },
      {
        type: 'Timeline',
        props: {
          id: 'tl-1',
          title: 'How it went in',
          items: 'March | Survey began\nJune | Two more plots added',
        },
      },
      {
        type: 'Callout',
        props: {
          id: 'c-1',
          tone: 'correction',
          title: '',
          text: 'An earlier version put the count at three plots.',
        },
      },
      {
        type: 'Code',
        props: { id: 'code-1', code: 'make test-py', language: 'bash', caption: '' },
      },
      {
        type: 'Sources',
        props: {
          id: 's-1',
          title: 'Sources',
          items: 'Rollout report | https://example.org/report\nInterview, March 2024',
        },
      },
      // No `style` prop, deliberately: this is the shape every divider saved
      // before that field existed still has, so the walkthrough keeps proving
      // those documents render.
      { type: 'Divider', props: { id: 'd-1', spacing: 'large' } },
    ],
    zones: {},
  };
}

/**
 * Write a screenshot only when `WALKTHROUGH_SHOTS` names a directory.
 *
 * Off by default so an ordinary suite run — CI's included — asserts without
 * leaving files behind. The walkthrough is a test first; the pictures are a
 * by-product of running it with the flag on.
 */
export async function shot(page: Page, name: string): Promise<void> {
  const dir = process.env.WALKTHROUGH_SHOTS;
  if (!dir) return;
  // Back to the top first: the step before a shot usually ends by interacting
  // with a control near the bottom of a form, and a viewport-height frame taken
  // from there shows the footer rather than the screen being demonstrated.
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({ path: `${dir}/${name}.png`, fullPage: true });
}
