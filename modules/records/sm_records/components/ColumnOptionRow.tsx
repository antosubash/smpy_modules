import { useT } from '@simple-module-py/i18n';
import { Badge } from '@simple-module-py/ui/components/ui/badge';
import { Button } from '@simple-module-py/ui/components/ui/button';
import { Checkbox } from '@simple-module-py/ui/components/ui/checkbox';
import { Label } from '@simple-module-py/ui/components/ui/label';
import {
  AlignLeftIcon,
  ArrowDownIcon,
  ArrowUpIcon,
  AtSignIcon,
  BracesIcon,
  CalendarCheckIcon,
  CalendarClockIcon,
  CalendarIcon,
  CircleDotIcon,
  ClockIcon,
  HashIcon,
  ImageIcon,
  LanguagesIcon,
  Link2Icon,
  LinkIcon,
  ListIcon,
  ListOrderedIcon,
  ToggleLeftIcon,
  TypeIcon,
} from 'lucide-react';

import { fieldTypeName } from '../utils/field-type-name';
import type { ListColumn } from '../utils/listing';

const FIELD_ICONS: Record<string, typeof TypeIcon> = {
  longtext: AlignLeftIcon,
  number: HashIcon,
  integer: HashIcon,
  boolean: ToggleLeftIcon,
  date: CalendarIcon,
  datetime: CalendarClockIcon,
  select: ListIcon,
  multiselect: ListIcon,
  email: AtSignIcon,
  url: LinkIcon,
  json: BracesIcon,
  media: ImageIcon,
  relation: Link2Icon,
};

const ENVELOPE_ICONS: Record<string, typeof TypeIcon> = {
  status: CircleDotIcon,
  locale: LanguagesIcon,
  position: ListOrderedIcon,
  published_at: CalendarCheckIcon,
  updated_at: ClockIcon,
};

function columnIcon(column: ListColumn): typeof TypeIcon {
  if (column.kind === 'envelope') return ENVELOPE_ICONS[column.key] ?? CircleDotIcon;
  return FIELD_ICONS[column.field.type] ?? TypeIcon;
}

/** The DOM id of a row's control, so the panel can put focus back on it
 *  after the row moves (keys are `[a-z0-9_]`, safe in an id). */
export function columnControlId(key: string, control: 'toggle' | 'up' | 'down'): string {
  return `records-column-${control}-${key}`;
}

/**
 * One column in the chooser: a tick box named by the column's label, its
 * type as an icon and a word, an "Indexed" badge — or, for a field that is
 * not indexed, the reason its header will not sort — and, while it is
 * shown, move-up/move-down buttons. Buttons rather than drag: every control
 * here is reachable and operable from the keyboard alone.
 */
export function ColumnOptionRow({
  column,
  label,
  chosen,
  disabled,
  first,
  last,
  onToggle,
  onMove,
}: {
  column: ListColumn;
  /** Already disambiguated against the other rows. */
  label: string;
  chosen: boolean;
  /** Unchosen and the field cap is reached. */
  disabled: boolean;
  first: boolean;
  last: boolean;
  onToggle: () => void;
  onMove: (delta: -1 | 1) => void;
}) {
  const { t } = useT();
  const Icon = columnIcon(column);
  const id = columnControlId(column.key, 'toggle');
  const field = column.kind === 'field' ? column.field : null;
  return (
    <li
      className="flex items-start gap-2 py-1.5"
      data-testid="records-column-option"
      data-column={column.key}
      data-chosen={chosen ? 'true' : 'false'}
    >
      <Checkbox
        id={id}
        className="mt-0.5"
        checked={chosen}
        disabled={disabled}
        onCheckedChange={onToggle}
      />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-1.5">
          <Icon className="size-3.5 shrink-0 text-muted-foreground" aria-hidden="true" />
          <Label htmlFor={id} className="font-normal">
            {label}
          </Label>
          {field?.indexed && (
            <Badge variant="secondary" className="font-normal">
              {t('records.columns.indexed', { defaultValue: 'Indexed' })}
            </Badge>
          )}
        </div>
        <p className="text-xs text-muted-foreground">
          {field
            ? fieldTypeName(t, field.type)
            : t('records.columns.record_column', { defaultValue: 'Record column' })}
        </p>
        {field && !field.indexed && (
          <p className="text-xs text-muted-foreground" data-testid="records-column-not-indexed">
            {t('records.columns.not_indexed_help', {
              defaultValue: "Not indexed: shown, but it can't be sorted or filtered.",
            })}
          </p>
        )}
      </div>
      {chosen && (
        <div className="flex shrink-0 items-center">
          <Button
            type="button"
            id={columnControlId(column.key, 'up')}
            variant="ghost"
            size="icon"
            className="size-7"
            disabled={first}
            aria-label={t('records.columns.move_up', { label, defaultValue: 'Move {label} up' })}
            onClick={() => onMove(-1)}
          >
            <ArrowUpIcon className="size-4" />
          </Button>
          <Button
            type="button"
            id={columnControlId(column.key, 'down')}
            variant="ghost"
            size="icon"
            className="size-7"
            disabled={last}
            aria-label={t('records.columns.move_down', {
              label,
              defaultValue: 'Move {label} down',
            })}
            onClick={() => onMove(1)}
          >
            <ArrowDownIcon className="size-4" />
          </Button>
        </div>
      )}
    </li>
  );
}
