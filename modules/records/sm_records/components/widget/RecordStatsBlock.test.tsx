// @vitest-environment happy-dom
import * as React from 'react';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { TypeRead } from '../../utils/types';

let pageLocale: string | undefined = 'de';
vi.mock('@inertiajs/react', () => ({
  usePage: () => ({ props: { locale: pageLocale }, url: '/p' }),
}));

const field = (key: string, type: string, indexed: boolean) => ({
  key,
  type,
  label: key.toUpperCase(),
  indexed,
});
vi.mock('../../utils/api', () => ({
  listTypes: async () => ({
    items: [
      {
        key: 'donation',
        label: 'Donation',
        is_public: true,
        fields: [
          field('amount', 'number', true),
          field('legacy', 'number', false),
          field('count', 'integer', true),
          field('note', 'text', true),
        ],
      } as unknown as TypeRead,
      {
        key: 'other',
        label: 'Other',
        is_public: true,
        fields: [field('weight', 'number', true)],
      } as unknown as TypeRead,
    ],
  }),
}));

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
(globalThis as { React?: unknown }).React = React;

const { RecordStatsBlock, RecordStatsRender, clampStatItems } = await import('./RecordStatsBlock');
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

type ResolveData = (
  data: { props: Record<string, unknown> },
  params: { trigger: string },
) => Promise<{ props: Record<string, unknown> }> | { props: Record<string, unknown> };

async function resolve(trigger: string, items: unknown[]): Promise<unknown[]> {
  const resolveData = RecordStatsBlock.resolveData as unknown as ResolveData;
  const out = await resolveData({ props: { items } }, { trigger });
  return out.props.items as unknown[];
}

describe('RecordStatsBlock.resolveData', () => {
  it('clamps to six and drops an unknown metric on load', async () => {
    expect(
      await resolve(
        'load',
        Array.from({ length: 8 }, () => item()),
      ),
    ).toHaveLength(6);
    const kept = await resolve('load', [item(), { ...item(), metric: 'max' }]);
    expect(kept).toHaveLength(1);
  });

  it('leaves the items alone while the author edits them', async () => {
    expect(
      await resolve(
        'replace',
        Array.from({ length: 8 }, () => item()),
      ),
    ).toHaveLength(8);
  });
});

describe('clampStatItems', () => {
  it('survives a stored value that is not a list', () => {
    expect(clampStatItems(undefined)).toEqual([]);
    expect(clampStatItems([item(), null as unknown as Item])).toHaveLength(1);
  });
});

describe('field options', () => {
  it('lists only the chosen types indexed number fields', async () => {
    const resolveFields = RecordStatsBlock.resolveFields as unknown as (data: {
      props: Record<string, unknown>;
    }) => Promise<{
      items: {
        arrayFields: {
          field: { options: { value: string }[] };
          typeKey: { options: { value: string }[] };
        };
      };
    }>;
    const out = await resolveFields({ props: { items: [item({ typeKey: 'donation' })] } });
    const values = out.items.arrayFields.field.options.map((o) => o.value);
    expect(values).toContain('amount');
    expect(values).toContain('count');
    expect(values).not.toContain('legacy');
    expect(values).not.toContain('note');
    expect(values).not.toContain('weight');
    const types = out.items.arrayFields.typeKey.options.map((o) => o.value);
    expect(types).toEqual(expect.arrayContaining(['donation', 'other']));
  });
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
