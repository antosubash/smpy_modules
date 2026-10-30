/**
 * Custom Puck field that opens the media library's picker dialog (the same
 * one every image field uses: paged, searchable by filename, #234). Selecting
 * an asset emits its URL via `onChange`; the adapter has already stashed the
 * full `MediaAssetRead` in the picked-asset cache, so the Image block's
 * `resolveData` can back-fill sibling props without a second fetch. A
 * manually typed URL is also accepted, stored as typed; `resolveData` then
 * falls back to a fresh list lookup.
 */

import { useState } from 'react';

import { FileGallery } from '../../fields/file-picker/file-gallery';
import { mediaLibraryAdapter } from '../../fields/media-adapter';
import { keys, useT } from '../../utils/i18n';

interface MediaPickerProps {
  value: string;
  onChange: (value: string) => void;
  readOnly?: boolean;
}

export function MediaPicker({ value, onChange, readOnly }: MediaPickerProps) {
  const { t } = useT();
  const [open, setOpen] = useState(false);

  return (
    <div className="space-y-2">
      <input
        type="text"
        value={value || ''}
        onChange={(e) => onChange(e.target.value)}
        readOnly={readOnly}
        placeholder={t(keys.pagebuilder.media_picker.placeholder)}
        className="w-full px-2 py-1.5 border rounded text-sm"
      />
      <div className="flex gap-2">
        <button
          type="button"
          disabled={readOnly}
          onClick={() => setOpen(true)}
          className="px-3 py-1.5 text-sm rounded bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50"
        >
          {t(keys.pagebuilder.media_picker.browse)}
        </button>
        {value && (
          <button
            type="button"
            disabled={readOnly}
            onClick={() => onChange('')}
            className="px-3 py-1.5 text-sm rounded border hover:bg-gray-50 disabled:opacity-50"
          >
            {t(keys.pagebuilder.media_picker.clear)}
          </button>
        )}
      </div>
      {value && (
        <img src={value} alt="" className="max-h-24 rounded border bg-gray-50 object-contain" />
      )}
      <FileGallery
        adapter={mediaLibraryAdapter}
        open={open}
        onClose={() => setOpen(false)}
        onSelect={(url) => onChange(url)}
      />
    </div>
  );
}
