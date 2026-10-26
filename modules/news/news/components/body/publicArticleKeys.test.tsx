// @vitest-environment happy-dom
import * as React from 'react';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

/** The published article draws without React's "unique key" warning (#266).
 *
 * Puck's `<Render>` keys each block by `props.id`, and a document that reaches
 * the viewer without one — written through the body API rather than the canvas,
 * which is how every e2e seed and any script writes them — gave every block the
 * key `undefined`. This mounts the real page over a document holding every
 * block in the palette, some with ids and some without, and fails on any key
 * warning React logs while drawing it, the "Read next" list included (it only
 * appears once its fetch resolves, so a static render would never reach it).
 */

vi.mock('@inertiajs/react', () => ({
  usePage: () => ({ props: { locale: 'en' }, url: '/news/x' }),
  Head: () => null,
}));
vi.mock('@simple-module-py/ui/components/BrandingHead', () => ({ BrandingHead: () => null }));
vi.mock('../../utils/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../utils/api')>();
  const item = (id: number, slug: string) => ({
    id,
    slug,
    title: `Story ${id}`,
    url: `/news/${slug}`,
    published_at: '2026-10-01T09:00:00Z',
  });
  return {
    ...actual,
    listArticles: vi.fn(async () => ({
      items: [item(1, 'this-one'), item(2, 'two'), item(3, 'three'), item(4, 'four')],
      total: 4,
    })),
  };
});

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
(globalThis as { React?: unknown }).React = React;

const { articlePuckConfig } = await import('./articlePuckConfig');
const { default: PublicArticle } = await import('../../pages/PublicArticle');

/** Every block in the palette at its defaults — the shape a writer gets by
 *  dropping each one on the canvas — with headings to give `Contents` an
 *  outline. Ids are left off every other block, as a body written through the
 *  API leaves them off. */
function everyBlock(): Record<string, unknown> {
  const components = articlePuckConfig.components as Record<
    string,
    { defaultProps?: Record<string, unknown> }
  >;
  const content: { type: string; props: Record<string, unknown> }[] = [
    { type: 'Heading', props: { id: 'h-1', text: 'First section', level: '2' } },
    { type: 'Heading', props: { text: 'A sub-section', level: '3' } },
    { type: 'Heading', props: { text: 'Second section', level: '2' } },
  ];
  Object.entries(components).forEach(([type, block], index) => {
    const props: Record<string, unknown> = { ...(block.defaultProps ?? {}) };
    if (index % 2 === 0) props.id = `${type}-seeded`;
    content.push({ type, props });
  });
  // The same id twice is as much a duplicate key as no id at all.
  content.push({ type: 'Paragraph', props: { id: 'h-1', text: 'Repeated id', lead: false } });
  return { root: { props: {} }, content, zones: {} };
}

const KEY_WARNING = /unique "key" prop|Encountered two children with the same key/;

describe('PublicArticle — list keys (#266)', () => {
  let errors: string[];
  let container: HTMLElement;
  let root: Root;

  beforeEach(() => {
    errors = [];
    vi.spyOn(console, 'error').mockImplementation((...args: unknown[]) => {
      errors.push(args.map(String).join(' '));
    });
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
    vi.restoreAllMocks();
  });

  it('logs no key warning for a document with every block, ids or not', async () => {
    await act(async () => {
      root.render(
        <PublicArticle
          title="An article"
          slug="this-one"
          data={everyBlock()}
          meta_description="About it"
          og_image="/media/cover.png"
          category="Science"
          author="Anto Subash"
          author_url="/news/author/anto-subash"
          published_at="2026-10-02T09:00:00Z"
          locale="en"
          alternates={[
            { locale: 'x-default', url: '/news/this-one' },
            { locale: 'en', url: '/news/this-one' },
            { locale: 'de', url: '/de/news/dieser' },
            { locale: 'fr', url: '/fr/news/celui' },
          ]}
        />,
      );
    });

    // The page really drew the document, the late list included — otherwise
    // an empty render would pass this vacuously.
    expect(container.querySelector('h1')?.textContent).toBe('An article');
    expect(container.textContent).toContain('Story 2');
    expect(container.querySelectorAll('nav a').length).toBeGreaterThan(2);
    expect(errors.filter((line) => KEY_WARNING.test(line))).toEqual([]);
  });

  it('gives each id-less heading its own anchor', async () => {
    await act(async () => {
      root.render(
        <PublicArticle title="T" data={everyBlock()} meta_description={null} og_image={null} />,
      );
    });
    const ids = [...container.querySelectorAll('h2[id], h3[id]')].map((el) => el.id);
    expect(ids).toEqual(
      expect.arrayContaining(['first-section', 'a-sub-section', 'second-section']),
    );
    expect(new Set(ids).size).toBe(ids.length);
  });
});
