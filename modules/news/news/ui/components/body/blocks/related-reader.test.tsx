// @vitest-environment happy-dom
import * as React from 'react';
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { expect, it, vi } from 'vitest';

vi.mock('@inertiajs/react', () => ({
  Head: () => null,
  usePage: () => ({ props: { locale: 'de' } }),
}));
vi.mock('@simple-module-py/ui/components/BrandingHead', () => ({ BrandingHead: () => null }));
(globalThis as { React?: unknown }).React = React;
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const { default: PublicArticle } = await import('../../../../pages/PublicArticle');

it('passes the article identity through the real block renderer and requests its language', async () => {
  const requested: string[] = [];
  vi.stubGlobal('fetch', async (url: string) => {
    requested.push(url);
    return {
      ok: true,
      json: async () => ({
        items: [
          {
            id: 1,
            slug: 'geschichte',
            title: 'This story',
            locale: 'de',
            translation_group: 'current',
          },
          {
            id: 2,
            slug: 'story',
            title: 'Its translation',
            locale: 'en',
            translation_group: 'current',
          },
          {
            id: 3,
            slug: 'weiter',
            title: 'Another story',
            locale: 'de',
            translation_group: 'other',
            url: '/de/news/weiter',
          },
        ],
      }),
    };
  });
  const container = document.createElement('div');
  const root = createRoot(container);
  try {
    await act(async () =>
      root.render(
        <PublicArticle
          title="This story"
          slug="geschichte"
          translation_group="current"
          locale="de"
          meta_description={null}
          og_image={null}
          data={{
            content: [
              {
                type: 'Related',
                props: { id: 'related', title: 'Read next', category: '', limit: 3 },
              },
            ],
          }}
        />,
      ),
    );
    await vi.waitFor(() => {
      expect(container.querySelector('section a')?.textContent).toBe('Another story');
    });
    expect(container.querySelectorAll('section a')).toHaveLength(1);
    expect(new URL(requested[0], 'https://example.test').searchParams.get('locale')).toBe('de');
  } finally {
    await act(async () => root.unmount());
    vi.unstubAllGlobals();
  }
});
