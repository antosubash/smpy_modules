import { Button } from '@simple-module-py/ui/components/ui/button';
import { useState } from 'react';
import { humanizeDryRunMessage } from '../../utils/dry-run-messages';
import { keys, useT } from '../../utils/i18n';
import type { DryRunReport } from '../../utils/types';

/**
 * The dry-run report of the change that was just forced through, kept on
 * screen (UX review R7a).
 *
 * "Apply anyway" is the one action in this module that deliberately creates
 * work for a human: N records are marked as not satisfying the schema and
 * nothing about them changes. Until R7c stores that flag server-side, this
 * report's `sample` is the only inventory of which records those are — and
 * `useSchemaApply` resets to `IDLE` on success, so before this the list was
 * gone the instant the confirm dialog closed. Keeping it here, with the
 * uuids copyable, makes the worklist survive at least as long as the page.
 */
export function LastAppliedReport({
  report,
  typeKey,
}: {
  report: DryRunReport | null;
  typeKey: string;
}) {
  const { t } = useT();
  const [copied, setCopied] = useState(false);
  if (!report || report.failing === 0) return null;

  const uuids = report.sample.map((rec) => rec.uuid);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(uuids.join('\n'));
      setCopied(true);
    } catch {
      // A browser that refuses the clipboard (no permission, insecure
      // origin) leaves the uuids on screen, which is what they are for.
      setCopied(false);
    }
  };

  return (
    <div
      className="space-y-3 rounded-md border border-amber-500/50 bg-amber-500/10 p-4 text-sm"
      data-testid="records-last-applied-report"
    >
      <p className="font-medium">
        {t(keys.records.type_editor.last_applied.title, {
          count: report.failing,
        })}
      </p>
      <p className="text-muted-foreground">
        {t(keys.records.type_editor.last_applied.help, {
          shown: report.sample.length,
        })}
      </p>
      <ul className="space-y-1.5" data-testid="records-last-applied-sample">
        {report.sample.map((rec) => (
          <li key={rec.uuid}>
            <a
              className="font-medium text-primary hover:underline"
              href={`/admin/records/${typeKey}/${rec.uuid}`}
            >
              {rec.display_title || rec.uuid.slice(0, 8)}
            </a>
            <ul className="ml-4 list-inside list-disc text-muted-foreground">
              {rec.errors.map((e) => (
                <li key={`${rec.uuid}:${e.field}`}>
                  {e.field}: {humanizeDryRunMessage(t, e.message)}
                </li>
              ))}
            </ul>
          </li>
        ))}
      </ul>
      <Button
        type="button"
        variant="outline"
        size="sm"
        data-testid="records-copy-uuids"
        onClick={() => void copy()}
      >
        {copied
          ? t(keys.records.type_editor.last_applied.copied)
          : t(keys.records.type_editor.last_applied.copy)}
      </Button>
    </div>
  );
}
