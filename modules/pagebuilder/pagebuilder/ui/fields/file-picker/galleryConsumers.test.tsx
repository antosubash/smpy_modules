// @vitest-environment happy-dom
import type { CustomField } from '@puckeditor/core';
import { act, type ReactNode } from 'react';
import { createRoot } from 'react-dom/client';
import { expect, it, vi } from 'vitest';

import { MediaPicker } from '../../components/blocks/MediaPicker';
import { StatsWidget } from '../../components/widgets/stats-widget';
import { mediaLibraryAdapter } from '../media-adapter';
import { createImageField } from './image-picker-field';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

function renderField(field: CustomField<string | undefined>, onChange: (url: string) => void) {
  return field.render({
    field,
    name: 'image',
    id: 'image',
    value: '',
    onChange: (url) => onChange(url ?? ''),
  });
}

it.each(['image field', 'MediaPicker', 'stats icon field'])(
  '%s opens the gallery, selects a URL and closes',
  async (consumer) => {
    const list = vi.spyOn(mediaLibraryAdapter, 'list').mockResolvedValue({
      items: [
        {
          id: 'cover',
          url: '/media/cover.webp',
          name: 'cover.webp',
          mimeType: 'image/webp',
          fileSize: 1024,
        },
      ],
      totalCount: 1,
    });
    const onChange = vi.fn();
    const host = document.createElement('div');
    document.body.append(host);
    const root = createRoot(host);
    try {
      let node: ReactNode;
      if (consumer === 'MediaPicker') {
        node = <MediaPicker value="" onChange={onChange} />;
      } else if (consumer === 'stats icon field') {
        const items = StatsWidget.fields?.items;
        if (items?.type !== 'array') throw new Error('Expected stats array field');
        const icon = items.arrayFields.iconUrl;
        if (icon?.type !== 'custom') throw new Error('Expected stats image field');
        node = renderField(icon, onChange);
      } else {
        node = renderField(createImageField(mediaLibraryAdapter), onChange);
      }
      await act(async () => root.render(node));
      expect(document.querySelector('[role="dialog"]')).toBeNull();
      expect(list).not.toHaveBeenCalled();

      const browse = [...host.querySelectorAll('button')].find((button) =>
        button.textContent?.includes('Browse'),
      );
      expect(browse).toBeDefined();
      await act(async () => browse?.click());
      await act(async () => {
        await vi.dynamicImportSettled();
      });
      const pick = document.querySelector<HTMLButtonElement>('[role="dialog"] ul button');
      expect(pick?.textContent).toContain('cover.webp');
      await act(async () => pick?.click());
      expect(onChange).toHaveBeenCalledExactlyOnceWith('/media/cover.webp');
      expect(document.querySelector('[role="dialog"]')).toBeNull();
    } finally {
      act(() => root.unmount());
      host.remove();
      list.mockRestore();
    }
  },
);
