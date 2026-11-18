/** The legend and the filters: a labelled checkbox per calendar (swatch and visibility in
 *  words, so colour is never the only cue), and optional category and type filters. */
import { keys, useT } from '../utils/i18n';
import { Name } from '../utils/isolate';
import type { CalendarInfo, CalendarState, FilterOption } from './types';

type Props = {
  state: CalendarState;
  calendars: CalendarInfo[];
  categories: FilterOption[];
  types: FilterOption[];
  onChange: (patch: Partial<CalendarState>) => void;
};

const toggle = (list: string[], id: string): string[] =>
  list.includes(id) ? list.filter((x) => x !== id) : [...list, id];

function Swatch({ color }: { color?: string | null }) {
  return (
    <span
      aria-hidden="true"
      className="inline-block size-3 shrink-0 rounded-sm border"
      style={{ backgroundColor: color || 'transparent' }}
    />
  );
}

function Check(props: {
  checked: boolean;
  onChange: () => void;
  color?: string | null;
  children: React.ReactNode;
}) {
  return (
    <label className="flex items-center gap-2 text-sm">
      <input
        type="checkbox"
        className="size-4 accent-primary [color-scheme:light] dark:[color-scheme:dark]"
        checked={props.checked}
        onChange={props.onChange}
      />
      <Swatch color={props.color} />
      <span>{props.children}</span>
    </label>
  );
}

export function Filters({ state, calendars, categories, types, onChange }: Props) {
  const { t } = useT();
  const copy = keys.events.calendar.filters;
  return (
    <section className="space-y-3" aria-label={t(copy.label)}>
      <fieldset className="space-y-1">
        <legend className="text-sm font-medium">{t(copy.calendars)}</legend>
        {calendars.map((calendar) => (
          <Check
            key={calendar.id}
            color={calendar.color}
            checked={state.calendars.includes(calendar.id)}
            onChange={() => onChange({ calendars: toggle(state.calendars, calendar.id) })}
          >
            <Name>{calendar.name}</Name>{' '}
            <span className="text-muted-foreground">
              ({t(keys.events.visibility[calendar.visibility])})
            </span>
          </Check>
        ))}
      </fieldset>
      {categories.length ? (
        <fieldset className="space-y-1">
          <legend className="text-sm font-medium">{t(copy.categories)}</legend>
          {categories.map((category) => (
            <Check
              key={category.id}
              color={category.color}
              checked={state.categories.includes(category.id)}
              onChange={() => onChange({ categories: toggle(state.categories, category.id) })}
            >
              <Name>{category.label}</Name>
            </Check>
          ))}
        </fieldset>
      ) : null}
      {types.length >= 2 ? (
        <fieldset className="space-y-1">
          <legend className="text-sm font-medium">{t(copy.types)}</legend>
          {types.map((type) => (
            <Check
              key={type.id}
              checked={state.types.includes(type.id)}
              onChange={() => onChange({ types: toggle(state.types, type.id) })}
            >
              {type.label}
            </Check>
          ))}
        </fieldset>
      ) : null}
    </section>
  );
}
