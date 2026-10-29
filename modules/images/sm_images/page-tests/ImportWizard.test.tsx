// @vitest-environment happy-dom
import { afterEach, describe, expect, it, vi } from 'vitest';

import { act, click, mount, setValue } from '../test-dom';

import { flush, GEOJSON, job, pickFile, stubFetch } from './support';

vi.mock('@inertiajs/react', async () => (await import('./support')).inertiaMock());
vi.mock('sonner', () => ({ toast: Object.assign(vi.fn(), { error: vi.fn() }) }));

const { ImportsTab } = await import('../components/imports/ImportsTab');
const Collection = (await import('../pages/Collection')).default;

const LIST = 'GET /api/images/collections/c1/imports';

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe('Import wizard', () => {
  it('previews a GeoJSON file, suggests the mapping and starts a base64 import', async () => {
    const calls = stubFetch({
      [LIST]: { items: [] },
      'POST /api/images/collections/c1/imports': job({ status: 'running' }),
    });
    const settled = vi.fn();
    const view = await mount(<ImportsTab collectionId="c1" canEdit onSettled={settled} />);
    await flush();
    await click(view.find('[data-testid="images-import-new"]'));
    const submit = view.find<HTMLButtonElement>('[data-testid="images-import-submit"]');
    expect(submit?.disabled).toBe(true);

    await pickFile(
      view.find<HTMLInputElement>('[data-testid="images-import-file"]') as HTMLInputElement,
      new File([GEOJSON], 'trees.geojson'),
    );
    expect(view.find('[data-testid="images-import-preview"]')?.textContent).toContain('3 features');
    expect(view.find<HTMLSelectElement>('[data-testid="images-import-kind"]')?.value).toBe('geojson_base64');
    expect(view.find<HTMLInputElement>('[data-testid="images-map-image_prop"]')?.value).toBe('image');
    expect(view.find<HTMLInputElement>('[data-testid="images-map-lat_prop"]')?.value).toBe('lat');
    expect(view.find<HTMLInputElement>('[data-testid="images-map-external_id_prop"]')?.value).toBe('id');

    // The suggestion can be changed, and survives the edit (the file is not re-read).
    await setValue(view.find<HTMLInputElement>('[data-testid="images-map-lng_prop"]') as HTMLInputElement, 'lng');
    // Auto-run is on by default; this import opts out.
    expect(view.find<HTMLInputElement>('[data-testid="images-import-auto-run"]')?.checked).toBe(true);
    await click(view.find('[data-testid="images-import-auto-run"]'));
    await click(view.find('[data-testid="images-import-submit"]'));
    await flush();

    const post = calls.find((c) => c.method === 'POST');
    const form = post?.body as FormData;
    expect(form.get('kind')).toBe('geojson_base64');
    expect(JSON.parse(String(form.get('mapping')))).toEqual({
      image_prop: 'image',
      lat_prop: 'lat',
      lng_prop: 'lng',
      external_id_prop: 'id',
    });
    expect(form.get('auto_run_prompts')).toBe('false');
    expect((form.get('file') as File).name).toBe('trees.geojson');
    // The wizard closes and the list is fetched again.
    expect(view.find('[data-testid="images-import-wizard"]')).toBeNull();
    expect(calls.filter((c) => c.method === 'GET')).toHaveLength(2);
    expect(settled).toHaveBeenCalled(); // the gallery shows what an eager import added
    await view.unmount();
  });

  it('says why a file cannot be imported and keeps the submit disabled', async () => {
    stubFetch({ [LIST]: { items: [] } });
    const view = await mount(<ImportsTab collectionId="c1" canEdit />);
    await flush();
    await click(view.find('[data-testid="images-import-new"]'));
    await pickFile(
      view.find<HTMLInputElement>('[data-testid="images-import-file"]') as HTMLInputElement,
      new File(['{"type":"Point","coordinates":[1,2]}'], 'p.geojson'),
    );
    expect(view.find('[data-testid="images-import-problem"]')?.textContent).toContain('Point');
    expect(view.find<HTMLButtonElement>('[data-testid="images-import-submit"]')?.disabled).toBe(true);
    await view.unmount();
  });

  it('sends a ZIP through create, the parts and extract', async () => {
    const calls = stubFetch({
      [LIST]: { items: [] },
      'POST /api/images/collections/c1/imports/zip': {
        job_id: 'z1',
        upload: {
          upload_id: 'tok',
          part_size: 4,
          part_urls: ['/api/images/uploads/tok/parts/1', '/api/images/uploads/tok/parts/2'],
          direct: false,
          expires_in: 60,
        },
      },
      'PUT /api/images/uploads/tok/parts/1': { etag: 'e1' },
      'PUT /api/images/uploads/tok/parts/2': { etag: 'e2' },
      'POST /api/images/imports/z1/extract': job({ id: 'z1', kind: 'zip', status: 'running' }),
    });
    const view = await mount(<ImportsTab collectionId="c1" canEdit />);
    await flush();
    await click(view.find('[data-testid="images-import-new"]'));
    await setValue(view.find<HTMLSelectElement>('[data-testid="images-import-kind"]') as HTMLSelectElement, 'zip');
    await pickFile(
      view.find<HTMLInputElement>('[data-testid="images-import-zip"]') as HTMLInputElement,
      new File(['12345678'], 'photos.zip'),
    );
    await setValue(
      view.find<HTMLInputElement>('[data-testid="images-map-filename-pattern"]') as HTMLInputElement,
      '(?P<group>[a-z]+)_(?P<role>[a-z]+)',
    );
    await click(view.find('[data-testid="images-import-submit"]'));
    await flush(20);

    const writes = calls.filter((c) => c.method !== 'GET').map((c) => `${c.method} ${c.url}`);
    expect(writes).toEqual([
      'POST /api/images/collections/c1/imports/zip',
      'PUT /api/images/uploads/tok/parts/1',
      'PUT /api/images/uploads/tok/parts/2',
      'POST /api/images/imports/z1/extract',
    ]);
    const create = calls.find((c) => c.url.endsWith('/imports/zip'))?.body as Record<string, unknown>;
    expect(create).toMatchObject({
      filename: 'photos.zip',
      size: 8,
      mapping: { filename_pattern: '(?P<group>[a-z]+)_(?P<role>[a-z]+)' },
    });
    expect(calls.at(-2)?.body).toEqual({ parts: [{ no: 1, etag: 'e1' }, { no: 2, etag: 'e2' }] });
    await view.unmount();
  });

  it('shows the imports tab only to someone who can edit', async () => {
    stubFetch({ 'GET /api/images/collections/c1/images': { items: [], next_cursor: null, total: 0 } });
    const { collection } = await import('./support');
    const rights = { can_manage: false, can_share: false, can_publish: false, direct_upload_threshold: 1024 };
    const viewer = await mount(<Collection collection={collection()} can_edit={false} {...rights} />);
    await flush();
    expect(viewer.find('[data-testid="images-tab-imports"]')).toBeNull();
    await viewer.unmount();
    const editor = await mount(<Collection collection={collection()} can_edit {...rights} />);
    await flush();
    expect(editor.find('[data-testid="images-tab-imports"]')).not.toBeNull();
    await editor.unmount();
  });
});
