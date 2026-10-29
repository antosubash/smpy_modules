import { useState } from 'react';

import { keys, type Translate } from '../../utils/i18n';

/** Characters of a free-text answer shown before "Show more". */
export const TEXT_SHOWN = 600;

function show(value: unknown): string {
  return typeof value === 'string' ? value : JSON.stringify(value);
}

/** A prompt step's answer: a structured one's fields as rows, free text as a
 *  paragraph, cut at {@link TEXT_SHOWN} characters until expanded. */
export function PromptAnswer({
  answer,
  t,
}: {
  answer: { data: Record<string, unknown> | null; text: string | null };
  t: Translate;
}) {
  const [open, setOpen] = useState(false);
  const rows = Object.entries(answer.data ?? {});
  const text = answer.text ?? '';
  const long = text.length > TEXT_SHOWN;
  return (
    <div className="mt-1 space-y-1" data-testid="images-answer">
      {rows.length > 0 && (
        <dl className="grid grid-cols-[minmax(0,10rem)_1fr] gap-x-3 gap-y-1">
          {rows.map(([name, value]) => (
            <div key={name} className="contents">
              <dt className="min-w-0 break-words text-muted-foreground">{name}</dt>
              <dd className="min-w-0 break-words">{show(value)}</dd>
            </div>
          ))}
        </dl>
      )}
      {text && (
        <p className="whitespace-pre-wrap break-words" data-testid="images-answer-text">
          {open || !long ? text : `${text.slice(0, TEXT_SHOWN)}…`}
        </p>
      )}
      {long && (
        <button
          type="button"
          className="text-xs underline"
          data-testid="images-answer-more"
          onClick={() => setOpen((o) => !o)}
        >
          {t(open ? keys.images.results.show_less : keys.images.results.show_more)}
        </button>
      )}
    </div>
  );
}
