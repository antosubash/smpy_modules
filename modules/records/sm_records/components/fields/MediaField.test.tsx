// @vitest-environment happy-dom
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';

import { click, mount, settle } from '../../test-dom';
import { clearMediaCache } from '../../utils/media-api';
import {
  API,
  loadRecordsCatalog,
  MANUAL,
  PHOTO,
  stubLibrary,
} from '../../utils/media-test-support';
import type { FieldDef } from '../../utils/types';
import { MediaApiProvider } from '../media/MediaApiContext';
import { MediaField } from './MediaField';

function field(overrides: Partial<FieldDef> = {}): FieldDef {
  return {
    key: 'image',
    type: 'media',
    label: 'Image',
    required: false,
    unique: false,
    indexed: false,
    default: null,
    help: null,
    constraints: {},
    options: {},
    ...overrides,
  };
}

async function flush(): Promise<void> {
  for (let i = 0; i < 8; i += 1) await settle();
}

function picker(value: string, onChange = vi.fn()) {
  return (
    <MediaApiProvider value={API}>
      <MediaField field={field()} value={value} onChange={onChange} />
    </MediaApiProvider>
  );
}

beforeAll(() => loadRecordsCatalog());
beforeEach(() => clearMediaCache());
afterEach(() => {
  vi.unstubAllGlobals();
  document.body.innerHTML = '';
});

describe('MediaField without a media library', () => {
  it('stays the id-or-URL text box, hint and all', async () => {
    const view = await mount(<MediaField field={field()} value="abc" onChange={() => {}} />);
    const input = view.find<HTMLInputElement>('#record-field-image');
    expect(input?.tagName).toBe('INPUT');
    expect(input?.value).toBe('abc');
    expect(view.host.textContent).toContain('media library id');
    expect(view.find('[data-testid="records-media-choose"]')).toBeNull();
    await view.unmount();
  });
});

describe('MediaField with a media library', () => {
  it('offers Choose, not a text box, when empty — named with the field', async () => {
    const view = await mount(picker(''));
    expect(view.find('input')).toBeNull();
    expect(view.find('[data-testid="records-media-none"]')?.textContent).toBe('No file chosen.');
    const choose = view.find<HTMLButtonElement>('#record-field-image');
    expect(choose?.getAttribute('data-testid')).toBe('records-media-choose');
    const [actionId, labelId] = (choose?.getAttribute('aria-labelledby') ?? '').split(' ');
    expect(document.getElementById(actionId)?.textContent).toBe('Choose file…');
    expect(document.getElementById(labelId)?.textContent).toContain('Image');
    expect(view.host.textContent).toContain('Choose a file from the media library');
    await view.unmount();
  });

  it('shows an image as a thumbnail from the derived download URL', async () => {
    stubLibrary([PHOTO]);
    const view = await mount(picker(PHOTO.id));
    await flush();
    const img = view.find<HTMLImageElement>('[data-testid="records-media-thumbnail"]');
    expect(img?.getAttribute('src')).toBe(`/api/file-storage/files/${PHOTO.id}/download`);
    expect(img?.getAttribute('alt')).toBe('harbour.png');
    expect(view.find('[data-testid="records-media-chip"]')?.textContent).toContain('image/png');
    expect(view.button('Replace')).toBeTruthy();
    await view.unmount();
  });

  it('shows any other file as an icon with its name, size and type', async () => {
    stubLibrary([MANUAL]);
    const view = await mount(picker(MANUAL.id));
    await flush();
    expect(view.find('[data-testid="records-media-thumbnail"]')).toBeNull();
    expect(view.find('[data-testid="records-media-icon"]')).not.toBeNull();
    const chip = view.find('[data-testid="records-media-chip"]')?.textContent ?? '';
    expect(chip).toContain('manual.pdf');
    expect(chip).toContain('application/pdf');
    expect(chip).toMatch(/3/);
    await view.unmount();
  });

  it('says "File missing" for a deleted file and keeps the id as the value', async () => {
    stubLibrary([]);
    const onChange = vi.fn();
    const view = await mount(picker(PHOTO.id, onChange));
    await flush();
    const missing = view.find('[data-testid="records-media-missing"]')?.textContent ?? '';
    expect(missing).toContain('File missing');
    expect(missing).toContain(PHOTO.id);
    expect(onChange).not.toHaveBeenCalled();
    expect(view.button('Remove')).toBeTruthy();
    await view.unmount();
  });

  it('renders a legacy URL value as a link and never looks it up', async () => {
    const fetchMock = stubLibrary([]);
    const view = await mount(picker('https://cdn.example.com/a.png'));
    await flush();
    const link = view.find<HTMLAnchorElement>('[data-testid="records-media-url"]');
    expect(link?.getAttribute('href')).toBe('https://cdn.example.com/a.png');
    expect(link?.getAttribute('rel')).toContain('noopener');
    expect(fetchMock).not.toHaveBeenCalled();
    await view.unmount();
  });

  it('Remove clears the value', async () => {
    stubLibrary([PHOTO]);
    const onChange = vi.fn();
    const view = await mount(picker(PHOTO.id, onChange));
    await flush();
    await click(view.find('[data-testid="records-media-remove"]'));
    expect(onChange).toHaveBeenCalledWith('');
    await view.unmount();
  });

  it('Choose opens the dialog and picking a file stores its id', async () => {
    stubLibrary([PHOTO, MANUAL]);
    const onChange = vi.fn();
    const view = await mount(picker('', onChange));
    await click(view.find('#record-field-image'));
    await flush();
    const dialog = document.querySelector('[data-testid="records-media-dialog"]');
    expect(dialog).not.toBeNull();
    const items = Array.from(document.querySelectorAll('[data-testid="records-media-item"]'));
    expect(items).toHaveLength(2);
    await click(items[1]);
    expect(onChange).toHaveBeenCalledWith(MANUAL.id);
    await flush();
    expect(document.querySelector('[data-testid="records-media-dialog"]')).toBeNull();
    await view.unmount();
  });

  it('is disabled while the editor saves', async () => {
    const view = await mount(
      <MediaApiProvider value={API}>
        <MediaField field={field()} value="" onChange={() => {}} disabled />
      </MediaApiProvider>,
    );
    expect(view.find<HTMLButtonElement>('#record-field-image')?.disabled).toBe(true);
    await view.unmount();
  });
});
