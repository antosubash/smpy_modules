/** Drag-and-drop target and the per-file upload progress list. */

import type { DragEvent } from 'react';

import type { UploadItem } from './types';

interface DropzoneProps {
  uploadFolder: string;
  dragActive: boolean;
  onDragActiveChange: (active: boolean) => void;
  onDrop: (e: DragEvent<HTMLDivElement>) => void;
}

export function MediaDropzone({
  uploadFolder,
  dragActive,
  onDragActiveChange,
  onDrop,
}: DropzoneProps) {
  return (
    // A drag-and-drop target has no interactive ARIA role that fits. The
    // keyboard-accessible path to the same action is the header Upload button.
    // biome-ignore lint/a11y/noStaticElementInteractions: drop target; keyboard path is the Upload button
    <div
      onDragOver={(e) => {
        e.preventDefault();
        onDragActiveChange(true);
      }}
      onDragLeave={(e) => {
        e.preventDefault();
        onDragActiveChange(false);
      }}
      onDrop={onDrop}
      className={`mb-4 border-2 border-dashed rounded-lg p-6 text-center text-sm transition-colors ${
        dragActive ? 'border-primary bg-primary/5 text-primary' : 'text-muted-foreground'
      }`}
      data-testid="media-dropzone"
    >
      Drop image files here to upload to <strong>{uploadFolder.trim() || 'Unfiled'}</strong>.
      Multiple files are accepted.
    </div>
  );
}

interface QueueProps {
  uploads: UploadItem[];
  onDismiss: (id: string) => void;
}

export function MediaUploadQueue({ uploads, onDismiss }: QueueProps) {
  if (uploads.length === 0) return null;
  return (
    <div className="mb-4 space-y-1" data-testid="upload-list">
      {uploads.map((u) => (
        <div
          key={u.id}
          className="border rounded p-2 text-xs flex items-center gap-3"
          data-testid="upload-row"
        >
          <div className="flex-1 min-w-0">
            <div className="font-medium truncate" title={u.file.name}>
              {u.file.name}
            </div>
            {/* done/in-progress keep literal colours: the token set has
                --destructive but no success, and half-converting a
                red/green pair reads worse than leaving it alone. */}
            <div className="mt-1 h-1.5 overflow-hidden rounded bg-muted">
              <div
                className={`h-full transition-all ${
                  u.status === 'error'
                    ? 'bg-destructive'
                    : u.status === 'done'
                      ? 'bg-green-500'
                      : 'bg-primary'
                }`}
                style={{
                  width: u.total
                    ? `${Math.min(100, Math.round((u.loaded / u.total) * 100))}%`
                    : '0%',
                }}
              />
            </div>
            {u.error && <div className="mt-1 text-destructive">{u.error}</div>}
          </div>
          <div className="w-16 text-right tabular-nums text-muted-foreground">
            {u.status === 'done'
              ? 'Done'
              : u.status === 'error'
                ? 'Failed'
                : `${Math.round((u.loaded / Math.max(1, u.total)) * 100)}%`}
          </div>
          {(u.status === 'done' || u.status === 'error') && (
            <button
              type="button"
              onClick={() => onDismiss(u.id)}
              className="text-muted-foreground hover:text-foreground"
              aria-label="Dismiss"
            >
              ×
            </button>
          )}
        </div>
      ))}
    </div>
  );
}
