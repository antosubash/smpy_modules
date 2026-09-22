import { Link } from '@inertiajs/react';
import { useT } from '@simple-module-py/i18n';

import type { ExpandedRef, FieldDef } from '../utils/types';
import { EMPTY_CELL as DASH, formatDateTime } from '../utils/values';

type Choice = { value: string; label: string };

function choices(field: FieldDef): Choice[] {
  const raw = field.options?.choices;
  return Array.isArray(raw) ? (raw as Choice[]) : [];
}

/** `select`/`multiselect` store the choice's `value` (design doc §7.3); the
 *  list shows the human `label` instead, falling back to the raw value if a
 *  choice was since removed from the schema (design doc §8.8: an orphaned
 *  value is not an error, it just no longer resolves to a label). */
function choiceLabel(field: FieldDef, raw: unknown): string {
  const match = choices(field).find((c) => c.value === raw);
  return match ? match.label : String(raw);
}

function isRef(value: unknown): value is { type: string; uuid: string } {
  return (
    typeof value === 'object' &&
    value !== null &&
    'uuid' in value &&
    typeof (value as { uuid: unknown }).uuid === 'string'
  );
}

/** One resolved relation target, rendered as a link, or a muted marker for
 *  the two states that are not a live, visible record (design §9). */
function ExpandedRefChip({ ref: exp }: { ref: ExpandedRef }) {
  const { t } = useT();
  if (exp.restricted) {
    return (
      <span className="text-muted-foreground" data-testid="records-relation-restricted">
        {t('records.relation.restricted', { defaultValue: 'Restricted' })}
      </span>
    );
  }
  if (exp.dangling) {
    return (
      <span
        className="text-muted-foreground"
        title={t('records.relation.deleted_title', {
          defaultValue: 'The record this pointed at has been deleted.',
        })}
        data-testid="records-relation-deleted"
      >
        {t('records.relation.deleted', { defaultValue: 'Deleted' })} ({exp.uuid.slice(0, 8)})
      </span>
    );
  }
  return (
    <Link
      href={`/admin/records/${exp.type_key}/${exp.uuid}`}
      className="hover:underline"
      data-testid="records-relation-link"
    >
      {exp.display_title}
    </Link>
  );
}

/**
 * Renders one indexed-field column's value in the record list, by field
 * type (design doc §7.3's coercions, reversed for display).
 *
 * A relation renders its `expanded[field.key]` entry when the caller passed
 * one — the target's `display_title` as a link, or a muted marker for a
 * `dangling`/`restricted` target (design §9) — and falls back to the target
 * uuid's first eight characters when there is none (no `?expand=` was asked,
 * or this is an older payload with nothing to look it up in).
 *
 * `json`, `media` and `longtext` never reach this component: they are not
 * indexable (design doc §7.3), so `listColumns` never selects them.
 */
export function RecordCell({
  field,
  value,
  expanded,
}: {
  field: FieldDef;
  value: unknown;
  /** This field's slice of `RecordRead.expanded`, one entry per stored
   *  reference in payload order — `undefined` when the caller did not
   *  expand this column. */
  expanded?: ExpandedRef[];
}) {
  const { t } = useT();
  if (value === null || value === undefined) {
    return <span className="text-muted-foreground">{DASH}</span>;
  }

  switch (field.type) {
    case 'boolean':
      // The glyph alone is `aria-hidden` (L1): unpaired, `true` announced as
      // empty and `false` as a bare en-dash, so a screen-reader user could
      // not tell true/false/missing apart in a boolean column. The `sr-only`
      // word next to it is the same pattern `fields/FieldShell.tsx` uses for
      // the required-field marker.
      return value ? (
        <span>
          <span aria-hidden="true">✓</span>
          <span className="sr-only">
            {t('records.fields.boolean_yes', { defaultValue: 'Yes' })}
          </span>
        </span>
      ) : (
        <span className="text-muted-foreground">
          <span aria-hidden="true">–</span>
          <span className="sr-only">{t('records.fields.boolean_no', { defaultValue: 'No' })}</span>
        </span>
      );

    case 'number':
    case 'integer': {
      // `number` arrives as a string (e.g. "9.99", design doc §7.3 /
      // Decimal's JSON encoding); `integer` arrives as a JSON number. U28:
      // both used to print the raw wire value verbatim — "2262.22",
      // "4749" — with no thousands separator, next to dates that *are*
      // locale-formatted. `Number()` on a wire value this module already
      // validated as numeric cannot produce `NaN`; the fallback is only
      // for a payload from a build old enough to have stored something
      // else under the key.
      const n = typeof value === 'number' ? value : Number(value);
      return <span>{Number.isFinite(n) ? n.toLocaleString() : String(value)}</span>;
    }

    case 'date': {
      // A bare calendar day ("YYYY-MM-DD", design doc §7.3) has no
      // timezone of its own. Anchoring it at UTC midnight and formatting in
      // UTC keeps the displayed day fixed regardless of the viewer's zone —
      // formatting in the local zone could otherwise shift it a day for a
      // negative UTC offset.
      const parsed = typeof value === 'string' ? new Date(`${value}T00:00:00Z`) : null;
      if (!parsed || Number.isNaN(parsed.getTime())) return <span>{String(value)}</span>;
      return (
        <span>
          {new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeZone: 'UTC' }).format(
            parsed,
          )}
        </span>
      );
    }

    case 'datetime':
      // ISO datetime (design doc §7.3), rendered in the viewer's own zone —
      // `formatDateTime` (utils/values.ts) is the one place that formatting
      // lives, shared with the envelope's own `published_at`/`updated_at`
      // timestamps in `RecordTable`/`RecordCardList`.
      return <span>{typeof value === 'string' ? formatDateTime(value) : String(value)}</span>;

    case 'select':
      return <span>{choiceLabel(field, value)}</span>;

    case 'multiselect': {
      const values = Array.isArray(value) ? value : [value];
      if (values.length === 0) return <span className="text-muted-foreground">{DASH}</span>;
      return <span>{values.map((v) => choiceLabel(field, v)).join(', ')}</span>;
    }

    case 'relation': {
      const refs = Array.isArray(value) ? value : [value];
      if (refs.length === 0) return <span className="text-muted-foreground">{DASH}</span>;
      if (!expanded) {
        const short = refs.map((r) => (isRef(r) ? r.uuid.slice(0, 8) : DASH)).join(', ');
        return <span className="font-mono text-xs">{short}</span>;
      }
      // Matched by position: `expanded[field.key]` carries one `ExpandedRef`
      // per stored reference, in payload order (design §9) — the same order
      // `refs` is already in.
      //
      // The separator rides *inside* each chip's wrapper and trails it
      // (UX-R17). As its own child of the `gap-x-1` flex row it was a flex
      // item in its own right, so the gap applied on both sides of it and
      // every relation column printed "A , B ,".
      return (
        <span className="flex flex-wrap items-center gap-x-1">
          {refs.map((r, index) => {
            const exp = expanded[index];
            const key = isRef(r) ? r.uuid : String(index);
            const last = index === refs.length - 1;
            return (
              <span key={exp ? exp.uuid : key} className="inline-flex items-center">
                {exp ? (
                  <ExpandedRefChip ref={exp} />
                ) : (
                  <span className="font-mono text-xs">{isRef(r) ? r.uuid.slice(0, 8) : DASH}</span>
                )}
                {!last && <span className="text-muted-foreground">,</span>}
              </span>
            );
          })}
        </span>
      );
    }

    default: {
      // `text`, `email`, `url` and anything else text-indexed: truncate for
      // the table, keep the full value reachable via `title`.
      const text = String(value);
      const truncated = text.length > 60 ? `${text.slice(0, 60)}…` : text;
      return <span title={text}>{truncated}</span>;
    }
  }
}
