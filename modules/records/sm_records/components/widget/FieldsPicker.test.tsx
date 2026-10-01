// @vitest-environment happy-dom
import { beforeAll, describe, expect, it, vi } from 'vitest';

import { mount } from '../../test-dom';
import { loadRecordsCatalog } from '../../utils/media-test-support';
import type { TypeRead } from '../../utils/types';
import { FieldsPicker, type FieldsPickerField } from './FieldsPicker';

vi.mock('../../utils/api', () => ({
  listTypes: async () => ({
    items: [
      {
        key: 'gallery',
        label: 'Gallery',
        is_public: true,
        fields: [
          { key: 'caption', type: 'text', label: 'Caption' },
          { key: 'image', type: 'media', label: 'Image' },
        ],
      } as unknown as TypeRead,
    ],
  }),
}));

const { RecordsListBlock } = await import('./RecordsListBlock');

beforeAll(() => loadRecordsCatalog());

/**
 * Review 4, ux F8: a `media` field ticked in the block's "Fields to show"
 * renders nothing on a public page of a stock host (no public download, so
 * no `media_url_template`), and the editor gave no hint why.
 */
describe("the Records list block's field picker", () => {
  it('notes on a media field that visitors will not see it, and nowhere else', async () => {
    const field = {
      type: 'custom',
      render: () => null,
      availableFields: [
        { value: 'caption', label: 'Caption', type: 'text' },
        { value: 'image', label: 'Image', type: 'media' },
      ],
    } as unknown as FieldsPickerField;
    const view = await mount(<FieldsPicker field={field} value={['image']} onChange={() => {}} />);
    const notes = view.all('[data-testid="records-widget-media-note"]');
    expect(notes).toHaveLength(1);
    expect(notes[0].textContent).toBe(
      'Not shown on public pages unless the media library lets visitors download files.',
    );
    const image = view.all('input').find((input) => input.parentElement?.textContent === 'Image');
    expect(image?.getAttribute('aria-describedby')).toBe(notes[0].id);
    const caption = view.all('input').find((i) => i.parentElement?.textContent === 'Caption');
    expect(caption?.hasAttribute('aria-describedby')).toBe(false);
    await view.unmount();
  });

  it("hands the picker each field's type, so it knows which one is media", async () => {
    const resolve = RecordsListBlock.resolveFields as unknown as (
      data: unknown,
    ) => Promise<{ fields: FieldsPickerField }>;
    const resolved = await resolve({ props: { typeKey: 'gallery' } });
    expect(resolved.fields.availableFields).toEqual([
      { value: 'caption', label: 'Caption', type: 'text' },
      { value: 'image', label: 'Image', type: 'media' },
    ]);
  });
});
