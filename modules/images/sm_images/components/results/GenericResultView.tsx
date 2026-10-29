import { keys, type Translate } from '../../utils/i18n';
import { errorCodeLabel } from '../../utils/labels';
import { PromptAnswer } from './PromptAnswer';
import type { ResultViewProps } from './registry';

function show(value: unknown): string {
  return typeof value === 'string' ? value : JSON.stringify(value);
}

/** The built-in `exif` step's fields, named for people; any other key (a
 *  plugin's) is shown as it is. */
const EXIF = keys.images.results.exif;
type ExifField = keyof typeof EXIF;

function fieldLabel(t: Translate, step: string, name: string): string {
  if (step === 'exif' && Object.hasOwn(EXIF, name)) return t(EXIF[name as ExifField]);
  return name;
}

/** The fallback for a result with no view of its own: its status, and its
 *  output as plain key/value rows (empty values left out). A prompt step is
 *  named by its prompt (`run.label`), its id kept as the tooltip, and shows
 *  its answer (`run.answer`) in place of the run's bookkeeping output. */
export function GenericResultView({ id, output, run, t }: ResultViewProps) {
  const answer = run?.answer ?? null;
  const rows = Object.entries(answer ? {} : (output ?? {})).filter(
    ([, value]) => value !== null && value !== undefined,
  );
  return (
    <div className="py-2 text-sm" data-testid="images-result-generic" data-result-id={id}>
      <div className="flex flex-wrap items-center gap-2 font-medium">
        <span className="min-w-0 break-words" title={id} data-testid="images-result-title">
          {run?.label || id}
        </span>
        {run && <span className="text-muted-foreground">{run.status}</span>}
        {run?.error_code && (
          <span className="text-destructive" title={run.error_code}>
            {errorCodeLabel(t, run.error_code)}
          </span>
        )}
      </div>
      {run?.error_message && <p className="text-destructive">{run.error_message}</p>}
      {answer && <PromptAnswer answer={answer} t={t} />}
      {rows.length > 0 && (
        <dl className="mt-1 grid grid-cols-[minmax(0,10rem)_1fr] gap-x-3 gap-y-1">
          {rows.map(([name, value]) => (
            <div key={name} className="contents">
              <dt className="min-w-0 break-words text-muted-foreground" title={name}>
                {fieldLabel(t, id, name)}
              </dt>
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
