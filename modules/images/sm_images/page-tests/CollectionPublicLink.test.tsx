// @vitest-environment happy-dom
import { afterEach, describe, expect, it, vi } from 'vitest';

import { click, mount } from './test-dom';
import { collection, flush, stubFetch } from './support';

vi.mock('@inertiajs/react', async () => (await import('./support')).inertiaMock());
vi.mock('sonner', () => ({ toast: Object.assign(vi.fn(), { error: vi.fn() }) }));

const Collection = (await import('../pages/Collection')).default;

const LIST = 'GET /api/images/collections/c1/images';
const rights = {
  can_edit: true,
  can_manage: true,
  can_share: true,
  can_publish: true,
  direct_upload_threshold: 1024,
};

afterEach(() => vi.unstubAllGlobals());

describe("a public collection's link in the console (QA TEST-017)", () => {
  it('shows the public page as a link that can be copied', async () => {
    stubFetch({ [LIST]: { items: [], next_cursor: null, total: 0 } });
    const writeText = vi.fn(async () => {});
    vi.stubGlobal('navigator', { ...navigator, clipboard: { writeText } });
    const view = await mount(
      <Collection
        collection={collection({ visibility: 'public' })}
        public_path="/images/c/trees"
        {...rights}
      />,
    );
    await flush();
    const link = view.find<HTMLAnchorElement>('[data-testid="images-public-link"]');
    const url = `${window.location.origin}/images/c/trees`;
    expect(link?.getAttribute('href')).toBe(url);
    expect(link?.textContent).toBe(url);
    await click(view.find('[data-testid="images-public-link-copy"]'));
    expect(writeText).toHaveBeenCalledWith(url);
    await view.unmount();
  });

  it('shows no link while the collection is not public', async () => {
    stubFetch({ [LIST]: { items: [], next_cursor: null, total: 0 } });
    const view = await mount(
      <Collection collection={collection()} public_path="/images/c/trees" {...rights} />,
    );
    await flush();
    expect(view.find('[data-testid="images-public-link"]')).toBeNull();
    await view.unmount();
  });
});
