import { keys, type Translate, useT } from '../../utils/i18n';
import type { FieldDef } from '../../utils/types';
import { formatDateTime } from '../../utils/values';

/** Shown behind a disclosure: identifying, rarely needed, and long. */
const COLLAPSED = new Set(['sm_ip_hash', 'sm_user_agent', 'sm_consent_ip_hash']);

/** The server's stored words for a status or a spam reason, as the console
 *  says them — `pending` reads "Bestätigung ausstehend" in German. */
const VALUES = keys.records.public_submissions.system_values as Record<
  string,
  Record<string, string> | undefined
>;

/** A system value as a person reads it: a datetime in the console's locale
 *  (not the browser's), a known status or spam reason translated. */
export function display(
  field: FieldDef,
  value: unknown,
  t: Translate,
  locale: string | undefined,
): string | null {
  if (value === null || value === undefined || value === '') return null;
  if (field.type === 'datetime' && typeof value === 'string') {
    return formatDateTime(value, locale);
  }
  const known = typeof value === 'string' ? VALUES[field.key]?.[value] : undefined;
  if (known) return t(known);
  return typeof value === 'string' ? value : JSON.stringify(value);
}

function Row({ label, value, empty }: { label: string; value: string | null; empty: string }) {
  return (
    <div className="grid gap-0.5 sm:grid-cols-[12rem_1fr] sm:gap-3">
      <dt className="text-sm text-muted-foreground">{label}</dt>
      <dd className="break-words text-sm">
        {value ?? <span className="text-muted-foreground">{empty}</span>}
      </dd>
    </div>
  );
}

/**
 * The read-only system fields of a record a website visitor sent (#101):
 * where it came from, its consent proof, a subscriber's status. The server
 * writes them (`public_submissions.spec`); the editor's form leaves them out
 * and an admin save carries them over unchanged, so this panel is the only
 * place they show. `internal` ones (`sm_nonce`) are not shown at all.
 *
 * Labels come from the catalogue by key, so a German console reads German
 * whatever the type stored; an unknown `sm_*` key falls back to its label.
 */
export function SubmissionDetails({
  fields,
  data,
}: {
  fields: FieldDef[];
  data: Record<string, unknown> | null | undefined;
}) {
  const { t, locale } = useT();
  const ps = keys.records.public_submissions;
  const shown = fields.filter((field) => field.system === 'readonly');
  if (shown.length === 0 || !data) return null;
  const labels = ps.system_fields as Record<string, string | undefined>;
  const label = (field: FieldDef) =>
    labels[field.key] ? t(labels[field.key] as string) : field.label;
  const empty = t(ps.details_empty);
  const open = shown.filter((field) => !COLLAPSED.has(field.key));
  const folded = shown.filter((field) => COLLAPSED.has(field.key));

  return (
    <section className="grid gap-3 rounded-lg border p-4" data-testid="records-submission-details">
      <div>
        <h2 className="text-sm font-medium">{t(ps.details_title)}</h2>
        <p className="text-sm text-muted-foreground">{t(ps.details_help)}</p>
      </div>
      <dl className="grid gap-2">
        {open.map((field) => (
          <Row
            key={field.key}
            label={label(field)}
            value={display(field, data[field.key], t, locale)}
            empty={empty}
          />
        ))}
      </dl>
      {folded.length > 0 && (
        <details>
          <summary className="cursor-pointer text-sm text-muted-foreground">
            {folded.map(label).join(', ')}
          </summary>
          <dl className="mt-2 grid gap-2">
            {folded.map((field) => (
              <Row
                key={field.key}
                label={label(field)}
                value={display(field, data[field.key], t, locale)}
                empty={empty}
              />
            ))}
          </dl>
        </details>
      )}
    </section>
  );
}
