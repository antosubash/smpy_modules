/** One source in the Sources dialog: its checkbox (asking before a configured one is turned off),
 *  badges, and its settings (the module's own section, else a JSON editor); and the row of an entry
 *  no module provides. */
import { Badge } from '@simple-module-py/ui/components/ui/badge';
import { Button } from '@simple-module-py/ui/components/ui/button';
import { PluginBoundary } from '../../extensions/PluginBoundary';
import { source as registered } from '../../extensions/registry';
import { translateKey } from '../../extensions/translateKey';
import type { SourceInfo } from '../../utils/api-extensions';
import { keys, useT } from '../../utils/i18n';
import { Name, withName } from '../../utils/isolate';
import type { Calendar } from '../../utils/types';
import { ConfirmDialog } from '../ConfirmDialog';
import { JsonSettings } from './JsonSettings';

type Settings = Record<string, unknown>;

export function SourceRow({
  info,
  settings,
  errors,
  codes,
  calendar,
  onToggle,
  onSettings,
}: {
  info: SourceInfo;
  /** `null`: the source is off. */
  settings: Settings | null;
  errors: Record<string, string>;
  codes: Record<string, string>;
  calendar: Calendar;
  onToggle: () => void;
  onSettings: (next: Settings | null) => void;
}) {
  const { t } = useT();
  const copy = keys.events.sources;
  const label = translateKey(t, info.label_key, info.id);
  const on = settings !== null;
  const Section = registered(info.id)?.SettingsSection;
  const json = (
    <JsonSettings
      id={`json-${info.id}`}
      settings={settings ?? {}}
      errors={errors}
      onChange={onSettings}
    />
  );
  return (
    <li className="grid gap-2 rounded-md border p-3">
      <div className="flex flex-wrap items-center gap-2">
        {on && Object.keys(settings).length > 0 ? (
          <ConfirmDialog
            trigger={
              <input
                id={`source-${info.id}`}
                type="checkbox"
                className="size-4 accent-primary"
                checked
                readOnly
              />
            }
            title={withName(t, copy.turn_off_title, label)}
            description={t(copy.turn_off_description)}
            confirmLabel={t(copy.turn_off)}
            onConfirm={async () => onToggle()}
          />
        ) : (
          <input
            id={`source-${info.id}`}
            type="checkbox"
            className="size-4 accent-primary"
            checked={on}
            onChange={onToggle}
          />
        )}
        <label htmlFor={`source-${info.id}`} className="font-medium">
          <Name>{label}</Name>
        </label>
        {info.public ? (
          <>
            <Badge variant="outline" data-testid="source-public">
              {t(copy.public)}
            </Badge>
            <span className="text-xs text-muted-foreground">{t(copy.public_hint)}</span>
          </>
        ) : null}
      </div>
      {on && info.has_settings ? (
        Section ? (
          <PluginBoundary name={`${info.id}/settings`} fallback={json}>
            <Section
              settings={settings}
              onChange={onSettings}
              errors={errors}
              codes={codes}
              calendar={{
                id: calendar.id,
                name: calendar.name,
                default_timezone: calendar.default_timezone,
              }}
            />
          </PluginBoundary>
        ) : (
          json
        )
      ) : null}
    </li>
  );
}

export function KeptSourceRow({ id, onRemove }: { id: string; onRemove: () => void }) {
  const { t } = useT();
  const copy = keys.events.sources;
  return (
    <li className="grid gap-2 rounded-md border border-dashed p-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-medium">
          <Name>{id}</Name>
        </span>
        <Badge variant="outline">{t(copy.not_installed)}</Badge>
        <ConfirmDialog
          trigger={
            <Button type="button" variant="outline" size="sm">
              {t(copy.remove)}
            </Button>
          }
          title={withName(t, copy.remove_title, id)}
          description={t(copy.remove_description)}
          confirmLabel={t(copy.remove)}
          onConfirm={async () => onRemove()}
        />
      </div>
      <p className="text-sm text-muted-foreground">{t(copy.not_installed_hint)}</p>
    </li>
  );
}
