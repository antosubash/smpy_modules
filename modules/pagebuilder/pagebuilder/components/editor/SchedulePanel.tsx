/** Scheduled publish / unpublish controls inside the settings drawer. */

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
  return (
    <fieldset className="md:col-span-2 border rounded p-3 bg-white">
      <legend className="px-1 text-sm font-medium text-gray-700">Schedule</legend>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        <label className="flex flex-col gap-1">
          <span className="text-xs text-gray-700">Publish at</span>
          <input
            type="datetime-local"
            value={toLocalInput(publishAt)}
            onChange={(e) => onPublishAtChange(fromLocalInput(e.target.value))}
            className="border rounded px-2 py-1"
            data-testid="schedule-publish-at"
          />
          <span className="text-xs text-gray-500">
            Draft auto-publishes at this time. Cleared after the flip.
          </span>
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-xs text-gray-700">Unpublish at</span>
          <input
            type="datetime-local"
            value={toLocalInput(unpublishAt)}
            onChange={(e) => onUnpublishAtChange(fromLocalInput(e.target.value))}
            className="border rounded px-2 py-1"
            data-testid="schedule-unpublish-at"
          />
          <span className="text-xs text-gray-500">
            Published page reverts to draft at this time.
          </span>
        </label>
      </div>
      <div className="mt-2 flex items-center gap-2">
        <button
          type="button"
          onClick={onSave}
          disabled={saveDisabled}
          className="px-3 py-1 text-sm rounded border hover:bg-gray-50 disabled:opacity-50"
          data-testid="schedule-save"
        >
          Save schedule
        </button>
        <button
          type="button"
          onClick={onClear}
          disabled={clearDisabled}
          className="px-3 py-1 text-sm rounded border hover:bg-gray-50 disabled:opacity-50"
        >
          Clear
        </button>
        {error && (
          <span className="text-xs text-red-600" data-testid="schedule-error">
            {error}
          </span>
        )}
      </div>
    </fieldset>
  );
}
