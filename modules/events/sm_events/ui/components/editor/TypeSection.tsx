/** The event's type and its plugin-owned `extra`: a picker on create (two or more types), the
 *  type read-only afterwards, the registered section for the type, and the notice for an event
 *  whose type no plugin on this server provides (its `extra` is kept and never sent). The section
 *  is a plugin component: lazy, contained by a `PluginBoundary`, and given only its documented
 *  props. */
import { Label } from '@simple-module-py/ui/components/ui/label';
import { NativeSelect } from '@simple-module-py/ui/components/ui/native-select';
import { useEventExtensions } from '../../extensions/load';
import { PluginBoundary } from '../../extensions/PluginBoundary';
import { eventType } from '../../extensions/registry';
import { translateKey } from '../../extensions/translateKey';
import { keys, useT } from '../../utils/i18n';

export type TypeOption = { id: string; label_key: string; icon?: string | null };

type Props = {
  types: readonly TypeOption[];
  type: string;
  extra: Readonly<Record<string, unknown>>;
  /** A new event: the type can still be chosen. */
  isNew: boolean;
  /** `false` when no plugin provides the event's type. */
  installed: boolean;
  eventId: string | null;
  locale: string;
  readOnly: boolean;
  errors: Readonly<Record<string, string>>;
  onType: (type: string) => void;
  onExtra: (extra: Record<string, unknown>) => void;
};

/** The server's messages for paths under `extra`, without the prefix. */
export function sectionErrors(errors: Readonly<Record<string, string>>): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [path, message] of Object.entries(errors)) {
    if (path.startsWith('extra.')) out[path.slice('extra.'.length)] = message;
  }
  return out;
}

export function TypeSection({
  types,
  type,
  extra,
  isNew,
  installed,
  eventId,
  locale,
  readOnly,
  errors,
  onType,
  onExtra,
}: Props) {
  const { t } = useT();
  const copy = keys.events.types;
  const label = (id: string) => translateKey(t, types.find((o) => o.id === id)?.label_key, id);
  const loaded = useEventExtensions(); // a direct visit has not loaded the plugins yet
  const Section = installed ? eventType(type)?.EditorSection : undefined;
  const waiting = installed && !loaded && type !== 'event' && !Section;
  const showType = types.length >= 2 || type !== 'event';
  return (
    <div className="grid gap-4">
      {isNew && types.length >= 2 ? (
        <div className="grid gap-2">
          <Label htmlFor="event-type">{t(copy.picker)}</Label>
          <NativeSelect id="event-type" value={type} onChange={(e) => onType(e.target.value)}>
            {types.map((o) => (
              <option key={o.id} value={o.id}>
                {label(o.id)}
              </option>
            ))}
          </NativeSelect>
        </div>
      ) : showType && !isNew ? (
        <p
          className="text-sm text-muted-foreground dark:text-zinc-400"
          data-testid="event-type-readonly"
        >
          {t(copy.current, { name: label(type) })}
        </p>
      ) : null}
      {!installed ? (
        <p
          role="status"
          className="rounded-md border border-dashed p-2 text-sm"
          data-testid="type-not-installed"
        >
          {t(copy.not_installed)}
        </p>
      ) : null}
      {waiting ? (
        <p role="status" className="text-sm text-muted-foreground dark:text-zinc-400">
          {t(copy.loading_section)}
        </p>
      ) : null}
      {Section ? (
        <PluginBoundary name={`${type}/editor`} fallback={null}>
          <Section
            extra={extra}
            onChange={onExtra}
            errors={sectionErrors(errors)}
            readOnly={readOnly}
            locale={locale}
            eventId={eventId}
          />
        </PluginBoundary>
      ) : null}
    </div>
  );
}
