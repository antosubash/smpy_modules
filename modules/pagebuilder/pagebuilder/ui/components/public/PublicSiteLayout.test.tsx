// @vitest-environment happy-dom
import * as React from 'react';
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { expect, it, vi } from 'vitest';

vi.mock('@inertiajs/react', () => ({
  usePage: () => ({ props: {}, url: '/news/story' }),
  Head: () => null,
}));
vi.mock('@simple-module-py/ui/components/BrandingHead', () => ({ BrandingHead: () => null }));

(globalThis as { React?: unknown }).React = React;
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

it('exports the same public frame for sibling pages, loading its renderer on demand', async () => {
  const { PublicSiteLayout } = await import('../../../index');
  const container = document.createElement('div');
  const root = createRoot(container);
  try {
    await act(async () => {
      root.render(
        <PublicSiteLayout
          layout_header={{
            content: [{ type: 'Heading', props: { id: 'h', text: 'Site header' } }],
          }}
          layout_footer={{
            content: [{ type: 'Heading', props: { id: 'f', text: 'Site footer' } }],
          }}
        >
          <article>Story</article>
        </PublicSiteLayout>,
      );
    });
    await vi.waitFor(
      async () => {
        await act(async () => {});
        expect(container.querySelector('[data-testid="site-header"]')?.textContent).toContain(
          'Site header',
        );
      },
      { timeout: 10000 },
    );
    expect(container.querySelector('main article')?.textContent).toBe('Story');
    expect(container.querySelector('[data-testid="site-footer"]')?.textContent).toContain(
      'Site footer',
    );
  } finally {
    await act(async () => root.unmount());
  }
});
