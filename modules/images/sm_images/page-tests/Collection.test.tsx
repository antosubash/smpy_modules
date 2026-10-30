// @vitest-environment happy-dom
import { afterEach, describe, expect, it, vi } from 'vitest';

import { click, mount } from './test-dom';
import { collection, flush, image, stubFetch } from './support';

vi.mock('@inertiajs/react', async () => (await import('./support')).inertiaMock());

const Collection = (await import('../pages/Collection')).default;

const LIST = 'GET /api/images/collections/c1/images';
const page = (...ids: string[]) => ({
  items: ids.map((id) => image(id)),
  next_cursor: null,
  total: ids.length,
});
const rights = {
  can_edit: true,
  can_manage: true,
  can_share: true,
  can_publish: false,
  direct_upload_threshold: 1024,
};

afterEach(() => vi.unstubAllGlobals());

describe('Collection gallery', () => {
  it('shows the server-provided versioned small rendition for each image', async () => {
    stubFetch({ [LIST]: page('i1', 'i2') });
    const view = await mount(<Collection collection={collection()} {...rights} />);
    await flush();
    const srcs = view
      .all<HTMLImageElement>('[data-testid="images-gallery-tile"] img')
      .map((i) => i.getAttribute('src'));
    expect(srcs).toEqual([
      '/api/images/images/i1/r/small?v=1',
      '/api/images/images/i2/r/small?v=1',
    ]);
    const hrefs = view
      .all<HTMLAnchorElement>('[data-testid="images-gallery-tile"]')
      .map((a) => a.getAttribute('href'));
    expect(hrefs[0]).toBe('/admin/images/images/i1');
    await view.unmount();
  });

  it('holds a placeholder for an image whose rendition is not ready', async () => {
    stubFetch({
      [LIST]: { items: [image('i1', { thumb_url: null })], next_cursor: null, total: 1 },
    });
    const view = await mount(<Collection collection={collection()} {...rights} />);
    await flush();
    expect(view.find('[data-testid="images-gallery-tile"] img')).toBeNull();
    expect(view.host.textContent).toContain('Preparing preview');
    await view.unmount();
  });

  it('applies a filter chip as query parameters and starts over', async () => {
    const calls = stubFetch({ [LIST]: page('i1') });
    const view = await mount(<Collection collection={collection()} {...rights} />);
    await flush();
    await click(view.find('[data-testid="images-gallery-filter-located"]'));
    await flush();
    expect(calls.at(-1)?.url).toBe('/api/images/collections/c1/images?has_location=true');
    await click(view.find('[data-testid="images-gallery-filter-failed"]'));
    await flush();
    expect(calls.at(-1)?.url).toBe('/api/images/collections/c1/images?step_status=failed');
    await view.unmount();
  });

  it('pages by cursor and appends', async () => {
    const calls = stubFetch({
      [LIST]: (call: { url: string }) =>
        call.url.includes('cursor=next')
          ? page('i3')
          : { items: [image('i1'), image('i2')], next_cursor: 'next', total: 3 },
    });
    const view = await mount(<Collection collection={collection()} {...rights} />);
    await flush();
    await click(view.find('[data-testid="images-gallery-more"]'));
    await flush();
    expect(calls.at(-1)?.url).toBe('/api/images/collections/c1/images?cursor=next');
    expect(view.all('[data-testid="images-gallery-tile"]')).toHaveLength(3);
    expect(view.find('[data-testid="images-gallery-more"]')).toBeNull();
    await view.unmount();
  });

  it('keeps the current filter when a slower answer for an old one arrives late', async () => {
    let release: (() => void) | undefined;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes('has_location=true')) await gate;
        const body = url.includes('has_location=true') ? page('stale') : page('fresh');
        return new Response(JSON.stringify(body), { status: 200 });
      }),
    );
    const view = await mount(<Collection collection={collection()} {...rights} />);
    await flush();
    await click(view.find('[data-testid="images-gallery-filter-located"]'));
    await click(view.find('[data-testid="images-gallery-filter-all"]'));
    await flush();
    release?.();
    await flush();
    const ids = view
      .all('[data-testid="images-gallery-tile"]')
      .map((a) => a.getAttribute('data-image-id'));
    expect(ids).toEqual(['fresh']);
    await view.unmount();
  });
});

describe("Collection actions follow the caller's rights", () => {
  it('hides upload, share, visibility and delete from a read-only viewer', async () => {
    stubFetch({ [LIST]: page('i1') });
    const view = await mount(
      <Collection
        collection={collection()}
        can_edit={false}
        can_manage={false}
        can_share={false}
        can_publish={false}
        direct_upload_threshold={1024}
      />,
    );
    await flush();
    for (const id of [
      'images-upload',
      'images-share',
      'images-visibility',
      'images-delete-collection',
    ]) {
      expect(view.find(`[data-testid="${id}"]`), id).toBeNull();
    }
    await view.unmount();
  });

  it('hides the pipeline tab from a viewer: its counts cover withheld images', async () => {
    stubFetch({ [LIST]: page('i1') });
    const viewer = await mount(
      <Collection
        collection={collection()}
        can_edit={false}
        can_manage={false}
        can_share={false}
        can_publish={false}
        direct_upload_threshold={1024}
      />,
    );
    await flush();
    expect(viewer.find('[data-testid="images-tab-pipeline"]')).toBeNull();
    await viewer.unmount();
    const owner = await mount(<Collection collection={collection()} {...rights} />);
    await flush();
    expect(owner.find('[data-testid="images-tab-pipeline"]')).not.toBeNull();
    await owner.unmount();
  });

  it('offers all four to the owner', async () => {
    stubFetch({ [LIST]: page('i1') });
    const view = await mount(<Collection collection={collection()} {...rights} />);
    await flush();
    for (const id of [
      'images-upload',
      'images-share',
      'images-visibility',
      'images-delete-collection',
    ]) {
      expect(view.find(`[data-testid="${id}"]`), id).not.toBeNull();
    }
    await view.unmount();
  });
});
