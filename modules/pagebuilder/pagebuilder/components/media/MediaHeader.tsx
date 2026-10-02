/** Media library actions: back-to-pages link and the file picker.
 *
 * Rendered into PageShell's `actions` slot, so the heading lives there
 * rather than here.
 */

import { router } from '@inertiajs/react';
import { Button } from '@simple-module-py/ui/components/ui/button';
import type { ChangeEvent, RefObject } from 'react';

import { keys, useT } from '../../utils/i18n';

interface Props {
  fileInputRef: RefObject<HTMLInputElement | null>;
  onFilesSelected: (e: ChangeEvent<HTMLInputElement>) => void;
}

export function MediaHeader({ fileInputRef, onFilesSelected }: Props) {
  const { t } = useT();
  return (
    <>
      <Button variant="outline" onClick={() => router.visit('/pagebuilder')}>
        {t(keys.pagebuilder.media_header.back)}
      </Button>
      {/* Stays a <label> wrapping the input: that pairing is what makes the
          hidden file input clickable, and a <button> cannot wrap it. */}
      <label className="inline-flex h-9 cursor-pointer items-center rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground shadow-xs hover:bg-primary/90">
        {t(keys.pagebuilder.media_header.upload)}
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
