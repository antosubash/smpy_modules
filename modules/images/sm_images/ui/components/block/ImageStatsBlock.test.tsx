// @vitest-environment happy-dom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { flush, stubFetch } from '../../page-tests/support';
import { act, mount } from '../../page-tests/test-dom';

let pageLocale: string | undefined = 'de';
vi.mock('@inertiajs/react', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@inertiajs/react')>()),
  usePage: () => ({ props: { locale: pageLocale }, url: '/p' }),
}));

const { ImageStatsBlock, ImageStatsRender, clampStatItems } = await import('./ImageStatsBlock');
type Item = import('./ImageStatsBlock').ImageStatItem;

const item = (over: Partial<Item> = {}): Item => ({
  metric: 'images',
  collection: '',
  label: 'Images',
  prefix: '',
  suffix: '',
  ...over,
});

type Opt = { label: string; value: string };
type ResolveData = (
  data: { props: Record<string, unknown> },
  params: { trigger: string },
) => { props: Record<string, unknown> };

function resolve(trigger: string, items: unknown[]): unknown[] {
  const resolveData = ImageStatsBlock.resolveData as unknown as ResolveData;
  return resolveData({ props: { items } }, { trigger }).props.items as unknown[];
}

afterEach(() => vi.unstubAllGlobals());

describe('ImageStatsBlock config', () => {
  it('holds catalogue keys as labels and clamps on load only', () => {
    expect(ImageStatsBlock.label).toBe('images.stats.label');
    const eight = Array.from({ length: 8 }, () => item());
    expect(resolve('load', eight)).toHaveLength(6);
    expect(resolve('load', [item(), { ...item(), metric: 'max' }])).toHaveLength(1);
    expect(resolve('replace', eight)).toHaveLength(8);
    expect(clampStatItems(undefined)).toEqual([]);
    expect(clampStatItems([item(), null as unknown as Item])).toHaveLength(1);
  });

  it('offers all public collections first, then public ones by slug', async () => {
    stubFetch({
      'GET /api/images/collections': {
        items: [
          { id: '1', slug: 'trees', name: 'Trees', visibility: 'public' },
          { id: '2', slug: 'secret', name: 'Secret', visibility: 'private' },
        ],
        next_cursor: null,
        total: 2,
      },
    });
    const resolveFields = ImageStatsBlock.resolveFields as unknown as () => Promise<{
      items: { arrayFields: { collection: { options: Opt[] } } };
    }>;
    const fields = await resolveFields();
    expect(fields.items.arrayFields.collection.options).toEqual([
      { label: 'All public collections', value: '' },
      { label: 'Trees', value: 'trees' },
    ]);
  });
});

describe('ImageStatsRender', () => {
  let respond: (url: string) => Promise<Response>;
  let calls: string[];

  beforeEach(() => {
    pageLocale = 'de';
    calls = [];
    respond = async () => new Response(JSON.stringify({ value: 1284 }));
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        calls.push(url);
        return respond(url);
      }),
    );
  });

  async function render(items: Item[]) {
    const view = await mount(
      <ImageStatsRender title="" subtitle="" surface="default" items={items} />,
    );
    await flush();
    return view;
  }
  const values = (view: { all: <T extends Element>(s: string) => T[] }) =>
    view.all('dd').map((d) => d.textContent);
  const params = (i: number) => new URL(calls[i], 'http://x').searchParams;

  it('shows a dash until the response, then the formatted number', async () => {
    let release: (r: Response) => void = () => {};
    respond = () => new Promise((r) => (release = r));
    const view = await render([item()]);
    expect(values(view)).toEqual(['–']);
    await act(async () => release(new Response(JSON.stringify({ value: 1284 }))));
    expect(values(view)).toEqual(['1.284']);
    await view.unmount();
  });

  it('wraps the number in prefix and suffix, and formats decimals by page locale', async () => {
    respond = async () => new Response(JSON.stringify({ value: 3.75 }));
    const view = await render([item({ prefix: '~', suffix: '+' })]);
    expect(values(view)).toEqual(['~3,75+']);
    await view.unmount();
  });

  it('marks a capped count with a + inside the affixes, and an unavailable total with a dash', async () => {
    respond = async () => new Response(JSON.stringify({ value: 10000, capped: true }));
    const a = await render([item({ prefix: '~', suffix: ' Bilder' })]);
    expect(values(a)).toEqual(['~10.000+ Bilder']);
    await a.unmount();
    respond = async () => new Response(JSON.stringify({ value: null, capped: true }));
    const b = await render([item()]);
    expect(values(b)).toEqual(['–']);
    await b.unmount();
  });

  it('shows a dash when the request fails or is refused', async () => {
    respond = async () => {
      throw new Error('offline');
    };
    const a = await render([item()]);
    expect(values(a)).toEqual(['–']);
    await a.unmount();
    respond = async () => new Response('{}', { status: 404 });
    const b = await render([item()]);
    expect(values(b)).toEqual(['–']);
    await b.unmount();
  });

  it('sends the metric and collection, anonymously', async () => {
    const view = await render([item({ metric: 'located', collection: 'trees' })]);
    expect(calls[0].startsWith('/api/images/public/stats?')).toBe(true);
    expect(params(0).get('metric')).toBe('located');
    expect(params(0).get('collection')).toBe('trees');
    await view.unmount();
  });

  it('sends no collection for all-public, nor for a collections item', async () => {
    const view = await render([item(), item({ metric: 'collections', collection: 'trees' })]);
    expect(params(0).has('collection')).toBe(false);
    expect(params(1).get('metric')).toBe('collections');
    expect(params(1).has('collection')).toBe(false);
    await view.unmount();
  });

  it('renders at most six of a stored list, skipping an unknown metric', async () => {
    const stored = [
      ...Array.from({ length: 8 }, () => item()),
      { ...item(), metric: 'max' } as unknown as Item,
    ];
    const view = await render(stored);
    expect(values(view)).toHaveLength(6);
    expect(calls).toHaveLength(6);
    await view.unmount();
  });

  it("never shows another item's number on the render after a reorder", async () => {
    respond = async (url) =>
      new Response(JSON.stringify({ value: url.includes('metric=images') ? 111 : 222 }));
    const a = item({ metric: 'images', label: 'A' });
    const b = item({ metric: 'located', label: 'B' });
    const view = await render([a, b]);
    expect(values(view)).toEqual(['111', '222']);
    // Freeze the refetch: only the first render after the prop change counts.
    respond = () => new Promise(() => {});
    await view.render(<ImageStatsRender title="" subtitle="" surface="default" items={[b, a]} />);
    expect(values(view)).toEqual(['222', '111']);
    await view.render(
      <ImageStatsRender
        title=""
        subtitle=""
        surface="default"
        items={[item({ metric: 'located', collection: 'trees' })]}
      />,
    );
    expect(values(view)).toEqual(['–']);
    await view.unmount();
  });

  it('does not refetch when only a label changes', async () => {
    const view = await render([item()]);
    await view.render(
      <ImageStatsRender title="" subtitle="" surface="default" items={[item({ label: 'New' })]} />,
    );
    await flush();
    expect(calls).toHaveLength(1);
    await view.unmount();
  });
});

describe('registration', () => {
  it('registers ImageStats in the images group, page-only', async () => {
    const { registeredBlocks } = await import(
      '@simple-module-py/pagebuilder/pagebuilder/ui/components/blockRegistry'
    );
    await import('../../../pagebuilder-blocks');
    const mine = registeredBlocks().find((r) => 'ImageStats' in r.blocks);
    expect(mine?.category?.key).toBe('images');
    expect(mine?.layout).toBeFalsy();
  });
});
