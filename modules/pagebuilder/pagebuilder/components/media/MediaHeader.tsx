/** Media library title bar: back-to-pages link and the file picker. */

import { router } from '@inertiajs/react';
import type { ChangeEvent, RefObject } from 'react';

interface Props {
  fileInputRef: RefObject<HTMLInputElement | null>;
  onFilesSelected: (e: ChangeEvent<HTMLInputElement>) => void;
}

export function MediaHeader({ fileInputRef, onFilesSelected }: Props) {
  return (
    <div className="flex items-center justify-between mb-6 flex-wrap gap-3">
      <h1 className="text-3xl font-bold">Media library</h1>
      <div className="flex gap-2">
        <button
          type="button"
          onClick={() => router.visit('/pagebuilder')}
          className="px-4 py-2 rounded border hover:bg-gray-50 font-medium"
        >
          ← Pages
        </button>
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
      </div>
    </div>
  );
}
