import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from '@simple-module-py/ui/components/ui/alert-dialog';
import { type ReactNode, useState } from 'react';

import { keys, useT } from '../../utils/i18n';
import type { PromptRunScope } from '../../utils/types-prompts';

const SCOPE = {
  missing: keys.images.prompts.run.confirm.missing,
  stale: keys.images.prompts.run.confirm.stale,
  all: keys.images.prompts.run.confirm.all,
} satisfies Record<PromptRunScope, string>;

/**
 * Asks before a collection-wide run of a prompt: each image (or group) it
 * reaches is one AI request. `count` is the most it can request - the
 * collection's images, or its groups (`null` when there are more than were
 * read); the scope says which of them it actually runs.
 */
export function RunConfirm({
  trigger,
  name,
  scope,
  group,
  count,
  onConfirm,
}: {
  trigger: ReactNode;
  name: string;
  scope: PromptRunScope;
  group: boolean;
  count: number | null;
  onConfirm: () => void;
}) {
  const { t } = useT();
  const [open, setOpen] = useState(false);
  const what =
    count === null
      ? t(keys.images.prompts.run.confirm.groups_unknown)
      : t(group ? keys.images.prompts.run.confirm.groups : keys.images.prompts.run.confirm.images, {
          count,
        });
  return (
    <AlertDialog open={open} onOpenChange={setOpen}>
      <AlertDialogTrigger asChild>{trigger}</AlertDialogTrigger>
      <AlertDialogContent data-testid="images-prompt-run-confirm">
        <AlertDialogHeader>
          <AlertDialogTitle>{t(keys.images.prompts.run.confirm.title, { name })}</AlertDialogTitle>
          <AlertDialogDescription>
            {what} {t(SCOPE[scope])}
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel data-testid="images-prompt-run-confirm-cancel">
            {t(keys.images.common.cancel)}
          </AlertDialogCancel>
          <AlertDialogAction
            data-testid="images-prompt-run-confirm-go"
            onClick={() => {
              setOpen(false);
              onConfirm();
            }}
          >
            {t(keys.images.prompts.run.confirm.go)}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
