import type { FieldDef } from '../utils/types';

const DASH = '—';

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
  return typeof value === 'object' && value !== null && 'uuid' in value;
}

/**
 * Renders one indexed-field column's value in the record list, by field
 * type (design doc §7.3's coercions, reversed for display).
 *
 * Relations show only the target uuid's first eight characters — Phase 2
 * has no batch "expand" of relation targets (design doc §16, Phase 4), so
 * there is no target record here to pull a display title from without an
 * extra query per row per relation column.
 *
 * `json`, `media` and `longtext` never reach this component: they are not
 * indexable (design doc §7.3), so `listColumns` never selects them.
 */
export function RecordCell({ field, value }: { field: FieldDef; value: unknown }) {
  if (value === null || value === undefined) {
    return <span className="text-muted-foreground">{DASH}</span>;
  }

  switch (field.type) {
    case 'boolean':
      return value ? (
        <span aria-hidden="true">✓</span>
      ) : (
        <span className="text-muted-foreground">–</span>
      );

    case 'number':
    case 'integer':
      // `number` arrives as a string (e.g. "9.99", design doc §7.3 /
      // Decimal's JSON encoding); `integer` arrives as a JSON number.
      // Either way the wire value is already the display value.
      return <span>{String(value)}</span>;

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

    case 'datetime': {
      // ISO datetime (design doc §7.3), rendered in the viewer's own zone.
      const parsed = typeof value === 'string' ? new Date(value) : null;
      if (!parsed || Number.isNaN(parsed.getTime())) return <span>{String(value)}</span>;
      return (
        <span>
          {new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(
            parsed,
          )}
        </span>
      );
    }

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
      const short = refs.map((r) => (isRef(r) ? r.uuid.slice(0, 8) : DASH)).join(', ');
      return <span className="font-mono text-xs">{short}</span>;
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
