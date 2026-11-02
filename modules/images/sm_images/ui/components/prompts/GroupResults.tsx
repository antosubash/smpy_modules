import { Button } from '@simple-module-py/ui/components/ui/button';

import { usePromptResults } from '../../hooks/usePromptResults';
import { keys, useT } from '../../utils/i18n';
import { errorCodeLabel } from '../../utils/labels';
import type { GroupItem } from '../../utils/types';

function show(value: unknown): string {
  return typeof value === 'string' ? value : JSON.stringify(value, null, 2);
}

/** `quota_exceeded: the plan's …` → its code and the stored detail (if any). */
function splitError(error: string): { code: string; detail: string | null } {
  const at = error.indexOf(':');
  if (at < 0) return { code: error.trim(), detail: null };
  return { code: error.slice(0, at).trim(), detail: error.slice(at + 1).trim() || null };
}

/** A failed run's error: its label (the code as a tooltip) and the stored
 *  detail, the same two lines the image viewer shows for a failed step. */
function GroupError({ id, error }: { id: number; error: string }) {
  const { t } = useT();
  const { code, detail } = splitError(error);
  return (
    <>
      <p className="text-destructive" title={code} data-testid={`images-group-result-error-${id}`}>
        {errorCodeLabel(t, code)}
      </p>
      {detail && (
        <p
          className="break-words text-xs text-destructive"
          data-testid={`images-group-result-detail-${id}`}
        >
          {detail}
        </p>
      )}
    </>
  );
}

/**
 * A group prompt's results, one per group. A `failed` row still carries the
 * output of the last run that worked: it is shown as the previous result,
 * under the failure, never as this run's answer. (A run that is missing
 * members also stores its partial summary as `failed`, and reads the same.)
 */
export function GroupResults({
  promptId,
  groups,
  version,
}: {
  promptId: string;
  groups: GroupItem[];
  /** Bumped when a run of this prompt is launched: the results are read again. */
  version: number;
}) {
  const { t } = useT();
  const { rows, error, hasMore, loadMore } = usePromptResults(promptId, version);

  if (error) return <p className="text-sm text-destructive">{error}</p>;
  if (rows === null) return null;
  if (rows.length === 0) {
    return <p className="text-sm text-muted-foreground">{t(keys.images.prompts.results.empty)}</p>;
  }
  const names = new Map(groups.map((g) => [g.id, g.name || g.key]));
  return (
    <ul className="space-y-2 text-sm" data-testid={`images-group-results-${promptId}`}>
      {rows.map((row) => {
        const data = row.result_data ?? row.result_text;
        const failed = row.status === 'failed';
        return (
          <li
            key={row.id}
            className="rounded-md border p-2"
            data-testid={`images-group-result-${row.id}`}
            data-status={row.status}
          >
            <div className="flex flex-wrap gap-2 font-medium">
              <span>{(row.group_id && names.get(row.group_id)) || row.group_id}</span>
              <span className="text-muted-foreground">{row.status}</span>
              {row.stale && (
                <span className="text-muted-foreground">
                  {t(keys.images.prompts.results.stale)}
                </span>
              )}
            </div>
            {failed && row.error && <GroupError id={row.id} error={row.error} />}
            {data !== null && data !== undefined && failed && (
              <div data-testid={`images-group-result-previous-${row.id}`}>
                <p className="text-muted-foreground">{t(keys.images.prompts.results.previous)}</p>
                <pre className="whitespace-pre-wrap text-xs opacity-70">{show(data)}</pre>
              </div>
            )}
            {data !== null && data !== undefined && !failed && (
              <pre
                className="whitespace-pre-wrap text-xs"
                data-testid={`images-group-result-current-${row.id}`}
              >
                {show(data)}
              </pre>
            )}
            {!failed && row.cross_check && (
              <div>
                <p className="text-muted-foreground">
                  {t(keys.images.prompts.results.cross_check)}
                </p>
                <pre className="whitespace-pre-wrap text-xs">{show(row.cross_check)}</pre>
              </div>
            )}
          </li>
        );
      })}
      {hasMore && (
        <li>
          <Button
            type="button"
            size="sm"
            variant="outline"
            data-testid={`images-group-results-more-${promptId}`}
            onClick={loadMore}
          >
            {t(keys.images.prompts.results.more)}
          </Button>
        </li>
      )}
    </ul>
  );
}
