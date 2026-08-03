/** Media library actions: back-to-pages link and the file picker.
 *
 * Rendered into PageShell's `actions` slot, so the heading lives there
 * rather than here.
 */

import { router } from '@inertiajs/react';
import type { ChangeEvent, RefObject } from 'react';

interface Props {
  fileInputRef: RefObject<HTMLInputElement | null>;
  onFilesSelected: (e: ChangeEvent<HTMLInputElement>) => void;
}

export function MediaHeader({ fileInputRef, onFilesSelected }: Props) {
  return (
    <>
      <button
        type="button"
        onClick={() => router.visit('/pagebuilder')}
        className="px-4 py-2 rounded border hover:bg-gray-50 font-medium"
      >
        ← Pages
      </button>
      {/* Stays a <label> wrapping the input: that pairing is what makes the
          hidden file input clickable, and a <button> cannot wrap it. */}
      <label className="px-4 py-2 rounded font-medium cursor-pointer text-white bg-blue-600 hover:bg-blue-700">
        Upload
        <input
          ref={fileInputRef}
          type="file"
          accept="image/*"
          multiple
          className="hidden"
          onChange={onFilesSelected}
        />
      </label>
    </>
  );
}
