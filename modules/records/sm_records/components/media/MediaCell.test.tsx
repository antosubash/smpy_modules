// @vitest-environment happy-dom
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';

import { act, mount, settle } from '../../test-dom';
import {
  availableColumns,
  defaultColumnKeys,
  firstMediaField,
  resolveListColumns,
} from '../../utils/listing';
import { clearMediaCache } from '../../utils/media-api';
import {
  API,
  loadRecordsCatalog,
  MANUAL,
  PHOTO,
  stubLibrary,
} from '../../utils/media-test-support';
import type { FieldDef, RecordRead, TypeRead } from '../../utils/types';
import { RecordCell } from '../RecordCell';
import { MediaApiProvider } from './MediaApiContext';

vi.mock('@inertiajs/react', () => ({
  Link: ({ children, href }: { children?: unknown; href: string }) => (
    <a href={href}>{children as React.ReactNode}</a>
  ),
}));

const { RecordTable } = await import('../RecordTable');

const IMAGE: FieldDef = {
  key: 'image',
  type: 'media',
  label: 'Photo',
  required: false,
  unique: false,
  indexed: false,
  default: null,
  help: null,
  constraints: {},
  options: {},
};

async function flush(): Promise<void> {
  for (let i = 0; i < 8; i += 1) await settle();
}

function cell(value: unknown, withApi: boolean) {
  const inner = <RecordCell field={IMAGE} value={value} />;
  return withApi ? <MediaApiProvider value={API}>{inner}</MediaApiProvider> : inner;
}

beforeAll(() => loadRecordsCatalog());
beforeEach(() => clearMediaCache());
afterEach(() => vi.unstubAllGlobals());

describe('the media cell', () => {
  it('shows the stored id as text when there is no media library', async () => {
    const view = await mount(cell(PHOTO.id, false));
    const raw = view.find('[data-testid="records-media-raw"]');
    expect(raw?.getAttribute('title')).toBe(PHOTO.id);
    expect(raw?.textContent).toBe(`${PHOTO.id.slice(0, 24)}…`);
    await view.unmount();
  });

  it('shows a small thumbnail for an image, named by its file', async () => {
    stubLibrary([PHOTO]);
    const view = await mount(cell(PHOTO.id, true));
    await flush();
    const img = view.find<HTMLImageElement>('img');
    expect(img?.getAttribute('src')).toBe(`/api/file-storage/files/${PHOTO.id}/download`);
    expect(img?.getAttribute('alt')).toBe('harbour.png');
    expect(img?.getAttribute('loading')).toBe('lazy');
    await view.unmount();
  });

  it('shows a file icon and the name for anything else', async () => {
    stubLibrary([MANUAL]);
    const view = await mount(cell(MANUAL.id, true));
    await flush();
    expect(view.find('img')).toBeNull();
    expect(view.find('[data-testid="records-media-icon"]')).not.toBeNull();
    expect(view.host.textContent).toContain('manual.pdf');
    await view.unmount();
  });

  it('says a deleted file is missing', async () => {
    stubLibrary([]);
    const view = await mount(cell(PHOTO.id, true));
    await flush();
    expect(view.find('[data-testid="records-media-missing"]')?.textContent).toContain(
      'File missing',
    );
    await view.unmount();
  });

  it('a thumbnail that fails to load forgets the file, so the next render re-asks', async () => {
    stubLibrary([PHOTO]);
    const view = await mount(cell(PHOTO.id, true));
    await flush();
    const img = view.find<HTMLImageElement>('img');
    await act(async () => {
      img?.dispatchEvent(new Event('error'));
    });
    expect(view.find('[data-testid="records-media-icon"]')).not.toBeNull();
    await view.unmount();
    // Deleted in the library since it was cached: the next render finds out.
    stubLibrary([]);
    const again = await mount(cell(PHOTO.id, true));
    await flush();
    expect(again.find('[data-testid="records-media-missing"]')).not.toBeNull();
    await again.unmount();
  });

  it('a legacy URL is a link even without a media library', async () => {
    const url = 'https://example.com/legacy/photo.jpg';
    const view = await mount(cell(url, false));
    const link = view.find<HTMLAnchorElement>('[data-testid="records-media-url"]');
    expect(link?.getAttribute('href')).toBe(url);
    expect(link?.getAttribute('rel')).toBe('noopener noreferrer');
    expect(view.find('[data-testid="records-media-raw"]')).toBeNull();
    await view.unmount();
  });

  it('shows the empty dash for no value', async () => {
    const view = await mount(cell(null, true));
    expect(view.host.textContent).toBe('—');
    await view.unmount();
  });
});

describe('the media column', () => {
  const type = {
    key: 'product',
    label: 'Product',
    label_plural: 'Products',
    display_field: 'title',
    fields: [
      { ...IMAGE, key: 'title', type: 'text', label: 'Title' },
      IMAGE,
      { ...IMAGE, key: 'backside', label: 'Back' },
    ],
  } as TypeRead;

  it("is in the default view: the type's first media field, and only that one", () => {
    expect(firstMediaField(type)?.key).toBe('image');
    expect(firstMediaField({ fields: [] })).toBeNull();
    expect(defaultColumnKeys(type, false)).toEqual([
      'status',
      'image',
      'position',
      'published_at',
      'updated_at',
    ]);
  });

  it('is left out of the default without a media library, and stays choosable', () => {
    expect(defaultColumnKeys(type, false, false)).not.toContain('image');
    const resolved = resolveListColumns({
      type,
      showLocale: false,
      raw: null,
      saved: null,
      withMedia: false,
    });
    expect(resolved.columns.map((c) => c.key)).not.toContain('image');
    expect(availableColumns(type, false).map((c) => c.key)).toContain('image');
  });

  it('renders a plain header and a thumbnail cell in the default table', async () => {
    stubLibrary([PHOTO]);
    const record = {
      uuid: 'r1',
      status: 'draft',
      display_title: 'Lamp',
      position: 0,
      published_at: null,
      created_at: '2026-01-01T00:00:00+00:00',
      updated_at: null,
      data: { title: 'Lamp', image: PHOTO.id },
      invalid: [],
    } as unknown as RecordRead;
    const noop = async () => undefined;
    const view = await mount(
      <MediaApiProvider value={API}>
        <RecordTable
          type={type}
          records={[record]}
          sort={null}
          onSort={() => {}}
          onDelete={noop}
          onRestore={noop}
          onPurge={noop}
        />
      </MediaApiProvider>,
    );
    await flush();
    const headers = view.all('th').map((th) => th.textContent);
    expect(headers).toContain('Photo');
    expect(headers).not.toContain('Back');
    const mediaCell = view.find('[data-testid="records-media-cell"]');
    expect(mediaCell?.querySelector('img')?.getAttribute('alt')).toBe('harbour.png');
    // Not a sort button: a media field cannot be indexed, so it cannot sort.
    expect(
      view
        .all('th')
        .find((th) => th.textContent === 'Photo')
        ?.querySelector('button'),
    ).toBeNull();
    await view.unmount();
  });
});
