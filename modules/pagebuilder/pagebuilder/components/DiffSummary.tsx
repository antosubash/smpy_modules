import type React from 'react';
import type { RevisionDiff } from '../utils/api';

interface Props {
  diff: RevisionDiff;
}

function renderValue(value: unknown): string {
  if (value === null || value === undefined) return '∅';
  if (typeof value === 'string') return value || '""';
  return JSON.stringify(value);
}

/**
 * Compact, scannable diff: metadata table (only changed fields) plus
 * three lists of blocks (added / removed / changed). Designed to fit
 * inside the editor's history panel without a separate page.
 */
export function DiffSummary({ diff }: Props): React.JSX.Element {
  const { metadata, blocks } = diff;
  const metaKeys = Object.keys(metadata);
  const totalChanges =
    metaKeys.length + blocks.added.length + blocks.removed.length + blocks.changed.length;

  if (totalChanges === 0) {
    return (
      <div
        className="mt-3 rounded border border-gray-200 bg-white p-3 text-xs text-gray-500"
        data-testid="diff-summary"
      >
        No changes between these revisions.
      </div>
    );
  }

  return (
    <div
      className="mt-3 rounded border border-gray-200 bg-white p-3 text-xs space-y-2"
      data-testid="diff-summary"
    >
      {metaKeys.length > 0 && (
        <div>
          <div className="font-semibold text-gray-700">Metadata</div>
          <ul className="ml-3 list-disc">
            {metaKeys.map((key) => (
              <li key={key}>
                <span className="font-mono">{key}</span>:{' '}
                <span className="text-red-600 line-through">
                  {renderValue(metadata[key].before)}
                </span>{' '}
                → <span className="text-green-700">{renderValue(metadata[key].after)}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
      {blocks.added.length > 0 && (
        <div>
          <div className="font-semibold text-green-700">Added ({blocks.added.length})</div>
          <ul className="ml-3 list-disc">
            {blocks.added.map((b) => (
              <li key={b.id}>
                <span className="font-mono">{b.type ?? '?'}</span>{' '}
                <span className="text-gray-500">({b.id})</span>
              </li>
            ))}
          </ul>
        </div>
      )}
      {blocks.removed.length > 0 && (
        <div>
          <div className="font-semibold text-red-700">Removed ({blocks.removed.length})</div>
          <ul className="ml-3 list-disc">
            {blocks.removed.map((b) => (
              <li key={b.id}>
                <span className="font-mono">{b.type ?? '?'}</span>{' '}
                <span className="text-gray-500">({b.id})</span>
              </li>
            ))}
          </ul>
        </div>
      )}
      {blocks.changed.length > 0 && (
        <div>
          <div className="font-semibold text-amber-700">Changed ({blocks.changed.length})</div>
          <ul className="ml-3 list-disc">
            {blocks.changed.map((b) => (
              <li key={b.id}>
                <span className="font-mono">{b.type ?? '?'}</span>{' '}
                <span className="text-gray-500">({b.id})</span>
                {b.type_before && (
                  <span className="text-gray-500">
                    {' '}
                    — was <span className="font-mono">{b.type_before}</span>
                  </span>
                )}
                {b.fields.length > 0 && (
                  <span className="text-gray-700">: {b.fields.join(', ')}</span>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
