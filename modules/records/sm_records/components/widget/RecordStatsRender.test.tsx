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

const { RecordStatsRender } = await import('./RecordStatsBlock');
type Item = import('./RecordStatsBlock').RecordStatItem;

const item = (over: Partial<Item> = {}): Item => ({
  typeKey: 'donation',
  metric: 'count',
  field: '',
  filter: '',
  label: 'Donations',
  prefix: '',
  suffix: '',
  ...over,
});

describe('RecordStatsRender', () => {
  let host: HTMLElement;
  let root: Root;
  let calls: { url: string; init?: RequestInit }[];
  let respond: (url: string) => Promise<Response>;

  beforeEach(() => {
    pageLocale = 'de';
    calls = [];
    respond = async () => new Response(JSON.stringify({ value: 1284 }));
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string, init?: RequestInit) => {
        calls.push({ url, init });
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

  async function mount(items: Item[], extra: Record<string, string> = {}) {
    await act(async () => {
      root.render(
        <RecordStatsRender
          title=""
          subtitle=""
          surface="default"
          items={items}
          locale=""
          tenant=""
          apiPrefix=""
          {...extra}
        />,
      );
    });
  }
  const values = () => Array.from(host.querySelectorAll('dd')).map((d) => d.textContent);
  const params = (i: number) => new URL(calls[i].url, 'http://x').searchParams;

  it('shows a dash until the response, then the formatted number', async () => {
    let release: (r: Response) => void = () => {};
    respond = () => new Promise((resolveFetch) => (release = resolveFetch));
    await mount([item()]);
    expect(values()).toEqual(['–']);
    await act(async () => release(new Response(JSON.stringify({ value: 1284 }))));
    expect(values()).toEqual(['1.284']);
  });

  it('wraps the number in the prefix and suffix', async () => {
    await mount([item({ prefix: '~', suffix: '+' })]);
    expect(values()).toEqual(['~1.284+']);
  });

  it('shows a dash when the request fails or is refused', async () => {
    respond = async () => {
      throw new Error('offline');
    };
    await mount([item()]);
    expect(values()).toEqual(['–']);
    respond = async () => new Response('{}', { status: 404 });
    await mount([item({ typeKey: 'secret' })]);
    expect(values()).toEqual(['–']);
  });

  it('sends a count to the type stats route, anonymously, with the header and locale', async () => {
    await mount([item({ filter: 'status:eq:paid' })], {
      locale: 'fr',
      tenant: 'acme',
      apiPrefix: '/api/records/public/',
    });
    expect(calls[0].url.startsWith('/api/records/public/donation/stats?')).toBe(true);
    expect(params(0).get('metric')).toBe('count');
    expect(params(0).get('filter')).toBe('status:eq:paid');
    expect(params(0).get('locale')).toBe('fr');
    expect(calls[0].init?.credentials).toBe('omit');
    const headers = (calls[0].init?.headers ?? {}) as Record<string, string>;
    expect(headers['X-Tenant-ID']).toBe('acme');
  });

  it('sends sum:<field> and formats 3.75 as 3,75 under de', async () => {
    respond = async () => new Response(JSON.stringify({ value: 3.75 }));
    await mount([item({ metric: 'sum', field: 'amount' })]);
    expect(params(0).get('metric')).toBe('sum:amount');
    expect(values()).toEqual(['3,75']);
  });

  it('shows a capped count as the ceiling and a plus, inside the prefix and suffix', async () => {
    respond = async () => new Response(JSON.stringify({ value: 10000, capped: true }));
    await mount([item(), item({ prefix: '~', suffix: ' Spenden' })]);
    expect(values()).toEqual(['10.000+', '~10.000+ Spenden']);
  });

  it('shows a dash for a capped sum, which has no value', async () => {
    respond = async () => new Response(JSON.stringify({ value: null, capped: true }));
    await mount([item({ metric: 'sum', field: 'amount', prefix: '€' })]);
    expect(values()).toEqual(['–']);
  });

  it('shows a dash for a null value that does not say it is capped', async () => {
    respond = async () => new Response(JSON.stringify({ value: null, capped: false }));
    await mount([item()]);
    expect(values()).toEqual(['–']);
  });

  it('ignores field for a count', async () => {
    await mount([item({ metric: 'count', field: 'amount' })]);
    expect(params(0).get('metric')).toBe('count');
  });

  it('shows a dash and sends nothing for an item without a type, or a sum without a field', async () => {
    await mount([item({ typeKey: '' }), item({ metric: 'sum', field: '' })]);
    expect(calls).toHaveLength(0);
    expect(values()).toEqual(['–', '–']);
  });

  it('renders at most six of a stored list, skipping an unknown metric', async () => {
    const stored = [
      ...Array.from({ length: 8 }, () => item()),
      { ...item(), metric: 'max' } as unknown as Item,
    ];
    await mount(stored);
    expect(values()).toHaveLength(6);
    expect(calls).toHaveLength(6);
  });

  it("never shows another item's number on the render after a reorder", async () => {
    respond = async (url) =>
      new Response(JSON.stringify({ value: url.includes('/donation/') ? 111 : 222 }));
    const a = item({ typeKey: 'donation', label: 'A' });
    const b = item({ typeKey: 'other', label: 'B' });
    await mount([a, b]);
    expect(values()).toEqual(['111', '222']);
    // Freeze the refetch: only the first render after the prop change counts.
    respond = () => new Promise(() => {});
    await act(async () => {
      root.render(
        <RecordStatsRender
          title=""
          subtitle=""
          surface="default"
          items={[b, a]}
          locale=""
          tenant=""
          apiPrefix=""
        />,
      );
    });
    expect(values()).toEqual(['222', '111']);
    // A different item in the same slot is a dash, not the old slot's number.
    await act(async () => {
      root.render(
        <RecordStatsRender
          title=""
          subtitle=""
          surface="default"
          items={[item({ typeKey: 'third' })]}
          locale=""
          tenant=""
          apiPrefix=""
        />,
      );
    });
    expect(values()).toEqual(['–']);
  });

  it('does not refetch when only a label changes', async () => {
    await mount([item()]);
    await mount([item({ label: 'Renamed' })]);
    expect(calls).toHaveLength(1);
  });
});

describe('registration', () => {
  it('offers RecordStats in data, page-only', async () => {
    const { registeredBlocks } = await import(
      '@simple-module-py/pagebuilder/pagebuilder/components/blockRegistry'
    );
    await import('../../pagebuilder-blocks');
    const mine = registeredBlocks().find((r) => 'RecordStats' in r.blocks);
    expect(mine?.category?.key).toBe('data');
    expect(mine?.layout).toBeFalsy();
  });
});
