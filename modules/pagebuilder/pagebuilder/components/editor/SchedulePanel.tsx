/** Scheduled publish / unpublish controls inside the settings drawer. */

import { Button } from '@simple-module-py/ui/components/ui/button';
import { Input } from '@simple-module-py/ui/components/ui/input';
import { useId } from 'react';

import { fromLocalInput, toLocalInput } from '../../utils/datetime';

interface Props {
  publishAt: string | null;
  unpublishAt: string | null;
  onPublishAtChange: (iso: string | null) => void;
  onUnpublishAtChange: (iso: string | null) => void;
  onSave: () => void;
  onClear: () => void;
  saveDisabled: boolean;
  clearDisabled: boolean;
  error: string | null;
}

export function SchedulePanel({
  publishAt,
  unpublishAt,
  onPublishAtChange,
  onUnpublishAtChange,
  onSave,
  onClear,
  saveDisabled,
  clearDisabled,
  error,
}: Props) {
  const publishId = useId();
  const unpublishId = useId();
  return (
    <fieldset className="md:col-span-2 rounded border bg-card p-3">
      <legend className="px-1 text-sm font-medium">Schedule</legend>
      {/* Explicit htmlFor rather than wrapping: the control is a component, so
          nesting it no longer associates the two — for a screen reader or for
          `getByLabelText`. */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        <div className="flex flex-col gap-1">
          <label className="text-xs" htmlFor={publishId}>
            Publish at
          </label>
          <Input
            id={publishId}
            type="datetime-local"
            value={toLocalInput(publishAt)}
            onChange={(e) => onPublishAtChange(fromLocalInput(e.target.value))}
            className="h-9"
            data-testid="schedule-publish-at"
          />
          <span className="text-xs text-muted-foreground">
            Draft auto-publishes at this time. Cleared after the flip.
          </span>
        </div>
        <div className="flex flex-col gap-1">
          <label className="text-xs" htmlFor={unpublishId}>
            Unpublish at
          </label>
          <Input
            id={unpublishId}
            type="datetime-local"
            value={toLocalInput(unpublishAt)}
            onChange={(e) => onUnpublishAtChange(fromLocalInput(e.target.value))}
            className="h-9"
            data-testid="schedule-unpublish-at"
          />
          <span className="text-xs text-muted-foreground">
            Published page reverts to draft at this time.
          </span>
        </div>
      </div>
      <div className="mt-2 flex items-center gap-2">
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={onSave}
          disabled={saveDisabled}
          data-testid="schedule-save"
        >
          Save schedule
        </Button>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={onClear}
          disabled={clearDisabled}
        >
          Clear
        </Button>
        {error && (
          <span className="text-xs text-destructive" data-testid="schedule-error">
            {error}
          </span>
        )}
      </div>
    </fieldset>
  );
}
