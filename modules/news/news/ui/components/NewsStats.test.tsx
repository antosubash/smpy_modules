// @vitest-environment happy-dom
import * as React from 'react';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

let pageLocale: string | undefined = 'de';
vi.mock('@inertiajs/react', () => ({
  usePage: () => ({ props: { locale: pageLocale }, url: '/p' }),
}));

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
(globalThis as { React?: unknown }).React = React;

const { NewsStatsBlock, NewsStatsRender, clampStatItems } = await import('./NewsStats');
type Item = import('./NewsStats').NewsStatItem;

const item = (over: Partial<Item> = {}): Item => ({
  language: 'page',
  category: '',
  label: 'Articles',
  prefix: '',
  suffix: '',
  ...over,
});

type ResolveData = (
  data: { props: Record<string, unknown> },
  params: { trigger: string },
) => Promise<{ props: Record<string, unknown> }> | { props: Record<string, unknown> };

async function resolve(trigger: string, items: unknown[]): Promise<unknown[]> {
  const resolveData = NewsStatsBlock.resolveData as unknown as ResolveData;
  const out = await resolveData({ props: { items } }, { trigger });
  return out.props.items as unknown[];
}

describe('NewsStatsBlock.resolveData', () => {
  it('clamps to six and drops an unknown language on load', async () => {
    const eight = Array.from({ length: 8 }, () => item());
    expect(await resolve('load', eight)).toHaveLength(6);
    const kept = await resolve('load', [item(), { ...item(), language: 'x' }]);
    expect(kept).toHaveLength(1);
  });

  it('leaves the items alone while the author edits them', async () => {
    const eight = Array.from({ length: 8 }, () => item());
    expect(await resolve('replace', eight)).toHaveLength(8);
  });
});

describe('clampStatItems', () => {
  it('survives a stored value that is not a list', () => {
    expect(clampStatItems(undefined)).toEqual([]);
    expect(clampStatItems([item(), null as unknown as Item])).toHaveLength(1);
  });
});

describe('NewsStatsRender', () => {
  let host: HTMLElement;
  let root: Root;
  let urls: string[];
  let respond: (url: string) => Promise<Response>;

  beforeEach(() => {
    pageLocale = 'de';
    urls = [];
    respond = async () => new Response(JSON.stringify({ value: 1284, capped: false }));
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        urls.push(url);
        return respond(url);
      }),
    );
    host = document.createElement('div');
    document.body.appendChild(host);
    root = createRoot(host);
  });

  afterEach(() => {
    act(() => root.unmount());
    host.remove();
    vi.unstubAllGlobals();
  });

  async function mount(items: Item[]) {
    await act(async () => {
      root.render(<NewsStatsRender title="" subtitle="" surface="default" items={items} />);
    });
  }
  const values = () => Array.from(host.querySelectorAll('dd')).map((d) => d.textContent);

  it('shows a dash until the response, then the formatted number', async () => {
    let release: (r: Response) => void = () => {};
    respond = () => new Promise((resolveFetch) => (release = resolveFetch));
    await mount([item()]);
    expect(values()).toEqual(['–']);
    await act(async () => release(new Response(JSON.stringify({ value: 1284, capped: false }))));
    expect(values()).toEqual(['1.284']);
  });

  it('wraps the number in the prefix and suffix', async () => {
    await mount([item({ prefix: '~', suffix: '+' })]);
    expect(values()).toEqual(['~1.284+']);
  });

  it('marks a capped count with a + inside the prefix and suffix', async () => {
    respond = async () => new Response(JSON.stringify({ value: 10000, capped: true }));
    await mount([item({ prefix: '~', suffix: ' Artikel' })]);
    expect(values()).toEqual(['~10.000+ Artikel']);
  });

  it('shows a dash for an answer without a number', async () => {
    respond = async () => new Response(JSON.stringify({ capped: false }));
    await mount([item()]);
    expect(values()).toEqual(['–']);
  });

  it('shows a dash when the request fails', async () => {
    respond = async () => {
      throw new Error('offline');
    };
    await mount([item()]);
    expect(values()).toEqual(['–']);
  });

  it('shows a dash for a non-2xx answer', async () => {
    respond = async () => new Response('{}', { status: 500 });
    await mount([item()]);
    expect(values()).toEqual(['–']);
  });

  it("sends the page's locale for 'page' and none for 'all'", async () => {
    await mount([item({ category: 'News' }), item({ language: 'all' })]);
    expect(urls).toHaveLength(2);
    const [page, all] = urls.map((u) => new URL(u, 'http://x').searchParams);
    expect(page.get('locale')).toBe('de');
    expect(page.get('category')).toBe('News');
    expect(page.get('metric')).toBe('published');
    expect(all.has('locale')).toBe(false);
  });

  it("never shows another item's number on the render after a reorder", async () => {
    respond = async (url) =>
      new Response(JSON.stringify({ value: url.includes('category=News') ? 111 : 222 }));
    const a = item({ category: 'News', label: 'A' });
    const b = item({ category: 'Blog', label: 'B' });
    await mount([a, b]);
    expect(values()).toEqual(['111', '222']);
    // Freeze the refetch: only the first render after the prop change counts.
    respond = () => new Promise(() => {});
    await mount([b, a]);
    expect(values()).toEqual(['222', '111']);
    await mount([item({ category: 'Events' })]);
    expect(values()).toEqual(['–']);
  });

  it('renders at most six of a stored list, skipping an unknown language', async () => {
    const stored = [
      ...Array.from({ length: 8 }, () => item()),
      { ...item(), language: 'x' } as unknown as Item,
    ];
    await mount(stored);
    expect(values()).toHaveLength(6);
    expect(urls).toHaveLength(6);
  });
});

describe('registration', () => {
  it('offers NewsStats in feeds, page-only', async () => {
    const { registeredBlocks } = await import(
      '@simple-module-py/pagebuilder/pagebuilder/ui/components/blockRegistry'
    );
    await import('../../pagebuilder-blocks');
    const mine = registeredBlocks().find((r) => 'NewsStats' in r.blocks);
    expect(mine?.category?.key).toBe('feeds');
    expect(mine?.layout).toBeFalsy();
  });
});
