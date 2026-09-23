// @vitest-environment happy-dom
import { describe, expect, it } from 'vitest';

import { mount } from '../../test-dom';
import type { PublicRecordItem } from '../../utils/public-api';
import { FieldValues } from './FieldValues';
import { publicMediaSrc } from './format';
import type { RecordsListProps } from './types';

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

  it('never renders a legacy URL or a scheme, and escapes the id', () => {
    expect(publicMediaSrc('https://cdn.example.com/a.png', TEMPLATE)).toBeNull();
    expect(publicMediaSrc('javascript:alert(1)', TEMPLATE)).toBeNull();
    expect(publicMediaSrc('', TEMPLATE)).toBeNull();
    expect(publicMediaSrc(42, TEMPLATE)).toBeNull();
    expect(publicMediaSrc('a/../../admin', TEMPLATE)).toBe(
      '/api/file-storage/files/a%2F..%2F..%2Fadmin/download',
    );
  });

  it('refuses a template that would leave the site', () => {
    expect(publicMediaSrc(ID, '//evil.example/{id}')).toBeNull();
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
