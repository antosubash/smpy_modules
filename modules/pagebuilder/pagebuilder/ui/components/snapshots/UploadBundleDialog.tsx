import { Button } from '@simple-module-py/ui/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@simple-module-py/ui/components/ui/dialog';
import { Input } from '@simple-module-py/ui/components/ui/input';
import { Label } from '@simple-module-py/ui/components/ui/label';
import { type ReactNode, useState } from 'react';

import { usePendingDialog } from '../../hooks/usePendingDialog';
import { keys, useT } from '../../utils/i18n';
import { uploadBundle } from '../../utils/snapshotsApi';

const FILE_INPUT = 'snapshot-bundle-file';

/**
 * Bring a bundle in from another host.
 *
 * Uploading only stores the bundle — it does not touch the site. Saying so on
 * the dialog matters: "Upload" next to a list of restore points reads like it
 * might apply, and someone who believes that will not use the feature at all.
 *
 * The server's rejection reason is shown verbatim. A malformed bundle has an
 * actual cause — wrong format version, a missing image, a tampered blob — and
 * "upload failed" would throw all of it away.
 */
export function UploadBundleDialog({
  trigger,
  onUploaded,
}: {
  trigger: ReactNode;
  onUploaded: () => void;
}) {
  const { t } = useT();
  const [file, setFile] = useState<File | null>(null);
  const { open, pending, error, change, run } = usePendingDialog(
    t(keys.pagebuilder.bundle.upload_failed),
    () => setFile(null),
  );

  return (
    <Dialog open={open} onOpenChange={change}>
      <DialogTrigger asChild>{trigger}</DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t(keys.pagebuilder.bundle.title)}</DialogTitle>
          <DialogDescription>{t(keys.pagebuilder.bundle.description)}</DialogDescription>
        </DialogHeader>

        <div className="grid gap-2 py-2">
          <Label htmlFor={FILE_INPUT}>{t(keys.pagebuilder.bundle.file_label)}</Label>
          <Input
            id={FILE_INPUT}
            type="file"
            accept=".zip,application/zip"
            disabled={pending}
            onChange={(event) => setFile(event.target.files?.[0] ?? null)}
          />
        </div>

        {error && <p className="text-sm text-destructive">{error}</p>}

        <DialogFooter>
          <Button variant="outline" onClick={() => change(false)} disabled={pending}>
            {t(keys.pagebuilder.bundle.cancel)}
          </Button>
          <Button
            disabled={!file || pending}
            onClick={() =>
              run(async () => {
                if (!file) return;
                await uploadBundle(file);
                onUploaded();
              })
            }
          >
            {pending ? t(keys.pagebuilder.bundle.uploading) : t(keys.pagebuilder.bundle.upload)}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
