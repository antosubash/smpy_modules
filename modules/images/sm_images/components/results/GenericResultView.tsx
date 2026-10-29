import { keys } from '../../utils/i18n';
import { errorCodeLabel } from '../../utils/labels';
import type { ResultViewProps } from './registry';

function show(value: unknown): string {
  return typeof value === 'string' ? value : JSON.stringify(value);
}

/** The fallback for a result with no view of its own: its status, and its
 *  output as plain key/value rows. */
export function GenericResultView({ id, output, run, t }: ResultViewProps) {
  const rows = Object.entries(output ?? {});
  return (
    <div className="py-2 text-sm" data-testid="images-result-generic" data-result-id={id}>
      <div className="flex flex-wrap items-center gap-2 font-medium">
        <span>{id}</span>
        {run && <span className="text-muted-foreground">{run.status}</span>}
        {run?.error_code && (
          <span className="text-destructive" title={run.error_code}>
            {errorCodeLabel(t, run.error_code)}
          </span>
        )}
      </div>
      {run?.error_message && <p className="text-destructive">{run.error_message}</p>}
      {rows.length > 0 && (
        <dl className="mt-1 grid grid-cols-[8rem_1fr] gap-x-2 gap-y-1">
          {rows.map(([name, value]) => (
            <div key={name} className="contents">
              <dt className="text-muted-foreground">{name}</dt>
              <dd className="min-w-0 break-words">{show(value)}</dd>
            </div>
          ))}
        </dl>
      )}
      {output === null && run?.status === 'completed' && run.output_visible === false && (
        <p className="text-muted-foreground">{t(keys.images.results.withheld)}</p>
      )}
    </div>
  );
}
