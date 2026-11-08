/** Step 2: the Mailchimp export (`.zip` or `.csv`, several files) and *Upload*. */

import { Button } from '@simple-module-py/ui/components/ui/button';
import { Input } from '@simple-module-py/ui/components/ui/input';
import { Label } from '@simple-module-py/ui/components/ui/label';
import { useEffect, useRef, useState } from 'react';

import { keys, useT } from '../../utils/i18n';

const copy = keys.newsletter.import;
const INPUT_ID = 'newsletter-import-files';

interface Props {
  /** No list chosen yet. */
  disabled: boolean;
  busy: boolean;
  onUpload: (files: File[]) => void;
}

export function UploadStep({ disabled, busy, onUpload }: Props) {
  const { t } = useT();
  const [files, setFiles] = useState<File[]>([]);
  // Set in the click itself: `busy` only follows on the next render.
  const submitted = useRef(false);
  useEffect(() => {
    if (!busy) submitted.current = false;
  }, [busy]);
  const submit = () => {
    if (submitted.current) return;
    submitted.current = true;
    onUpload(files);
  };
  return (
    <div className="grid gap-2">
      <Label htmlFor={INPUT_ID}>{t(copy.upload_label)}</Label>
      <p className="text-sm text-muted-foreground">{t(copy.upload_hint)}</p>
      <div className="flex flex-wrap items-center gap-2">
        <Input
          id={INPUT_ID}
          type="file"
          accept=".zip,.csv"
          multiple
          disabled={busy}
          className="max-w-md"
          onChange={(e) => setFiles([...(e.target.files ?? [])])}
        />
        <Button type="button" disabled={disabled || busy || files.length === 0} onClick={submit}>
          {busy ? t(copy.uploading) : t(copy.upload)}
        </Button>
      </div>
    </div>
  );
}
