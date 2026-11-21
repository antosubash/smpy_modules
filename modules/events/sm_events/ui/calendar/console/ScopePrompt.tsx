/** "Only this occurrence / All occurrences": asked when a drag or resize touches an instance
 *  of a series. Closing it any other way cancels the change. */
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@simple-module-py/ui/components/ui/alert-dialog';
import { useRef } from 'react';
import { keys, useT } from '../../utils/i18n';
import { withName } from '../../utils/isolate';
import type { Occurrence } from '../types';
import type { Scope } from './writes';

type Props = {
  /** The occurrence being changed; the prompt is open while it is set. */
  occurrence: Occurrence | null;
  onChoose: (scope: Scope | null) => void;
  /** Focus goes back to the event once the prompt closes. */
  onClosed?: (occurrence: Occurrence) => void;
};

export function ScopePrompt({ occurrence, onChoose, onClosed }: Props) {
  const { t } = useT();
  const copy = keys.events.calendar.scope;
  // The last occurrence outlives the prompt's closing, for the exit animation and the focus.
  const last = useRef(occurrence);
  if (occurrence) last.current = occurrence;
  const shown = occurrence ?? last.current;
  return (
    <AlertDialog open={occurrence !== null} onOpenChange={(open) => !open && onChoose(null)}>
      <AlertDialogContent
        onCloseAutoFocus={(event) => {
          if (!last.current || !onClosed) return;
          event.preventDefault();
          onClosed(last.current);
        }}
      >
        <AlertDialogHeader>
          <AlertDialogTitle>{t(copy.title)}</AlertDialogTitle>
          <AlertDialogDescription className="dark:text-zinc-400">
            {withName(t, copy.description, shown?.title ?? '')}
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter className="gap-2 sm:flex-wrap">
          <AlertDialogCancel>{t(keys.events.common.cancel)}</AlertDialogCancel>
          <AlertDialogAction
            variant="outline"
            onClick={(e) => {
              e.preventDefault();
              onChoose('all');
            }}
          >
            {t(copy.all)}
          </AlertDialogAction>
          <AlertDialogAction
            onClick={(e) => {
              e.preventDefault();
              onChoose('one');
            }}
          >
            {t(copy.one)}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
