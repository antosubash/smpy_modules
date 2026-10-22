// @vitest-environment happy-dom
import { afterEach, describe, expect, it, vi } from 'vitest';

import { mount } from '../../test-dom';
import type { PublicRecordItem } from '../../utils/public-api';
import { publicMediaSrc } from './format';
import type { RecordsListProps } from './types';

// The Inertia page the widget sits on: `locale` on the public viewer,
// `page.locale` in the editor. Reset after each test.
const pageProps: { locale?: string; page?: { locale: string } } = {};
vi.mock('@inertiajs/react', () => ({ usePage: () => ({ props: pageProps }) }));

const { FieldValues } = await import('./FieldValues');

afterEach(() => {
  delete pageProps.locale;
  delete pageProps.page;
});

const ID = '11111111-1111-4111-8111-111111111111';
const TEMPLATE = '/api/file-storage/files/{id}/download';

const item: PublicRecordItem = {
  uuid: 'r1',
  slug: null,
  display_title: 'Harbour at dawn',
  published_at: null,
  data: { photo: ID, caption: 'Low tide' },
};

const props = {
  fieldMeta: [
    { key: 'photo', type: 'media', label: 'Photo', choices: [] },
    { key: 'caption', type: 'text', label: 'Caption', choices: [] },
  ],
} as unknown as RecordsListProps;

describe('publicMediaSrc — only a URL a visitor can load', () => {
  it('fills the template with the stored id', () => {
    expect(publicMediaSrc(ID, TEMPLATE)).toBe(`/api/file-storage/files/${ID}/download`);
  });

  it('is nothing without a template — files are not anonymous (file_storage)', () => {
    expect(publicMediaSrc(ID, null)).toBeNull();
    expect(publicMediaSrc(ID, undefined)).toBeNull();
  });

  it('never renders a legacy URL or a scheme', () => {
    expect(publicMediaSrc('https://cdn.example.com/a.png', TEMPLATE)).toBeNull();
    expect(publicMediaSrc('javascript:alert(1)', TEMPLATE)).toBeNull();
    expect(publicMediaSrc('', TEMPLATE)).toBeNull();
    expect(publicMediaSrc(42, TEMPLATE)).toBeNull();
  });

  it('refuses a template that would leave the site', () => {
    expect(publicMediaSrc(ID, '//evil.example/{id}')).toBeNull();
  });

  // Only an id-shaped value is ever templated (mediaValueKind): a value that
  // merely *looks* path-traversal-y, like everything else that is not an id,
  // a URL or a rooted path, is never looked up at all — review 4's escaping
  // of `a/../../admin` into the template no longer applies because the value
  // never reaches the template in the first place.
  it("renders nothing for a value that isn't a file id, a URL or a rooted path", () => {
    expect(publicMediaSrc('a/../../admin', TEMPLATE)).toBeNull();
    expect(publicMediaSrc('media/products/sku-000001.jpg', TEMPLATE)).toBeNull();
  });

  it('uses a `/`-rooted value directly as the src, with no template needed', () => {
    expect(publicMediaSrc('/static/products/sku-000001.jpg', TEMPLATE)).toBe(
      '/static/products/sku-000001.jpg',
    );
    expect(publicMediaSrc('/static/x.png', null)).toBe('/static/x.png');
    // Still subject to the same safe-address check as everything else here.
    expect(publicMediaSrc('//evil.example/x.png', TEMPLATE)).toBeNull();
  });
});

describe('FieldValues — a media value on the public page', () => {
  it('renders an <img> when the page came with a template', async () => {
    const view = await mount(<FieldValues item={item} props={props} mediaUrlTemplate={TEMPLATE} />);
    const img = view.find<HTMLImageElement>('[data-testid="records-widget-media"]');
    expect(img?.getAttribute('src')).toBe(`/api/file-storage/files/${ID}/download`);
    expect(img?.getAttribute('alt')).toBe('Harbour at dawn');
    expect(view.host.textContent).toContain('Photo:');
    await view.unmount();
  });

  it('renders nothing for it — not even the label — without one', async () => {
    const view = await mount(<FieldValues item={item} props={props} mediaUrlTemplate={null} />);
    expect(view.find('img')).toBeNull();
    expect(view.host.textContent).not.toContain('Photo');
    expect(view.host.textContent).not.toContain(ID);
    // The other fields are untouched.
    expect(view.host.textContent).toContain('Caption: Low tide');
    await view.unmount();
  });
});

describe('FieldValues — dates follow the page language (#189)', () => {
  const dated: PublicRecordItem = { ...item, data: { day: '2026-03-01' } };
  const dateProps = (locale: string) =>
    ({
      locale,
      fieldMeta: [{ key: 'day', type: 'date', label: 'Day', choices: [] }],
    }) as unknown as RecordsListProps;

  it("writes a German public page's dates in German", async () => {
    pageProps.locale = 'de';
    const view = await mount(
      <FieldValues item={dated} props={dateProps('')} mediaUrlTemplate={null} />,
    );
    expect(view.host.textContent).toContain('Day: 01.03.2026');
    await view.unmount();
  });

  it("uses the edited page's language in the editor canvas", async () => {
    pageProps.page = { locale: 'de' };
    const view = await mount(
      <FieldValues item={dated} props={dateProps('en')} mediaUrlTemplate={null} />,
    );
    expect(view.host.textContent).toContain('Day: 01.03.2026');
    await view.unmount();
  });

  it("falls back to the widget's language off a page", async () => {
    const view = await mount(
      <FieldValues item={dated} props={dateProps('de')} mediaUrlTemplate={null} />,
    );
    expect(view.host.textContent).toContain('Day: 01.03.2026');
    await view.unmount();
  });
});
