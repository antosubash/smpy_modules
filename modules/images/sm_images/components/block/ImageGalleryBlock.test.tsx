// @vitest-environment happy-dom
import { afterEach, describe, expect, it, vi } from 'vitest';
import { flush, stubFetch } from '../../page-tests/support';
import { mount } from '../../test-dom';
import {
  COUNT_DEFAULT,
  COUNT_MAX,
  clampCount,
  ImageGalleryBlock,
  type ImageGalleryProps,
} from './ImageGalleryBlock';

afterEach(() => vi.unstubAllGlobals());

type Opt = { label: string; value: string };
const props: ImageGalleryProps = { collection: 'trees', size: 'medium', count: 4 };

describe('ImageGalleryBlock config', () => {
  it('holds catalogue keys as its labels, resolved by pagebuilder at render', () => {
    expect(ImageGalleryBlock.label).toBe('images.block.label');
    const fields = ImageGalleryBlock.fields as Record<string, { label?: string; options?: Opt[] }>;
    expect(fields.collection.label).toBe('images.block.collection');
    expect(fields.size.label).toBe('images.block.size');
    expect(fields.size.options?.map((o) => o.label)).toEqual([
      'images.block.size_small',
      'images.block.size_medium',
      'images.block.size_large',
    ]);
    expect(fields.count.label).toBe('images.block.count');
    expect(ImageGalleryBlock.defaultProps).toEqual({
      collection: '',
      size: 'medium',
      count: COUNT_DEFAULT,
    });
  });

  it('offers public collections only, by slug, with translated chrome', async () => {
    stubFetch({
      'GET /api/images/collections': {
        items: [
          { id: '1', slug: 'trees', name: 'Trees', visibility: 'public' },
          { id: '2', slug: 'secret', name: 'Secret', visibility: 'private' },
          { id: '3', slug: 'inside', name: 'Inside', visibility: 'internal' },
        ],
        next_cursor: null,
        total: 3,
      },
    });
    const resolve = ImageGalleryBlock.resolveFields as unknown as () => Promise<
      Record<string, { label: string; options?: Opt[] }>
    >;
    const fields = await resolve();
    expect(fields.collection.options).toEqual([
      { label: 'Choose a public collection', value: '' },
      { label: 'Trees', value: 'trees' },
    ]);
    expect(fields.collection.label).toBe('Collection');
  });

  it('asks the server for public collections', async () => {
    const calls = stubFetch({
      'GET /api/images/collections': { items: [], next_cursor: null, total: 0 },
    });
    await (ImageGalleryBlock.resolveFields as unknown as () => Promise<unknown>)();
    expect(calls[0]?.url).toBe('/api/images/collections?filter=public');
  });

  it('survives an editor that cannot list collections', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response('no', { status: 403 })),
    );
    const fields = await (
      ImageGalleryBlock.resolveFields as unknown as () => Promise<
        Record<string, { options?: Opt[] }>
      >
    )();
    expect(fields.collection.options).toHaveLength(1);
  });

  it('clamps a stored count on load only', () => {
    const resolveData = ImageGalleryBlock.resolveData as unknown as (
      data: { props: ImageGalleryProps },
      p: { trigger: string },
    ) => { props: ImageGalleryProps };
    expect(resolveData({ props: { ...props, count: 400 } }, { trigger: 'load' }).props.count).toBe(
      COUNT_MAX,
    );
    expect(resolveData({ props: { ...props, count: 0 } }, { trigger: 'replace' }).props.count).toBe(
      0,
    );
    expect(clampCount('x')).toBe(COUNT_DEFAULT);
    expect(clampCount(4.9)).toBe(4);
  });
});

describe('ImageGallery render', () => {
  const Render = ImageGalleryBlock.render as unknown as (
    p: ImageGalleryProps,
  ) => React.ReactElement;
  const tile = (id: string) => ({
    id,
    width: 8,
    height: 8,
    thumb_url: `/api/images/public/c/trees/images/${id}/r/small?v=1`,
    display_url: `/api/images/public/c/trees/images/${id}/display?v=1`,
  });

  it('renders the public thumbnails of the chosen collection, limited to count', async () => {
    const calls = stubFetch({
      'GET /api/images/public/c/trees/images': {
        items: [tile('a'), tile('b')],
        next_cursor: 'more',
      },
    });
    const view = await mount(<Render {...props} />);
    await flush();
    expect(calls[0]?.url).toBe('/api/images/public/c/trees/images?limit=4');
    const srcs = view.all<HTMLImageElement>('img').map((i) => i.getAttribute('src'));
    expect(srcs).toEqual([tile('a').thumb_url, tile('b').thumb_url]);
    expect(view.find('[data-testid="images-public-more"]')).toBeNull();
    await view.unmount();
  });

  it('renders nothing without a collection, and nothing when the fetch fails', async () => {
    const calls = stubFetch({});
    const none = await mount(<Render {...props} collection="" />);
    await flush();
    expect(calls).toHaveLength(0);
    expect(none.host.innerHTML).toBe('');
    await none.unmount();

    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response('gone', { status: 404 })),
    );
    const gone = await mount(<Render {...props} />);
    await flush();
    expect(gone.host.innerHTML).toBe('');
    await gone.unmount();
  });
});
