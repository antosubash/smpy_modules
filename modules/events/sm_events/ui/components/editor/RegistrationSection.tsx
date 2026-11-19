/** How people register for the event: not at all, on another site, or on this site through a
 *  registration provider (a form kept by another module). The provider's own part, which picks the
 *  form, is a plugin component: lazy, contained by a `PluginBoundary`, given only its documented
 *  props. A saved event also shows how many seats each date has taken (counts, never people). */
import { Checkbox } from '@simple-module-py/ui/components/ui/checkbox';
import { FieldError } from '@simple-module-py/ui/components/ui/field';
import { Input } from '@simple-module-py/ui/components/ui/input';
import { Label } from '@simple-module-py/ui/components/ui/label';
import { NativeSelect } from '@simple-module-py/ui/components/ui/native-select';
import { PluginBoundary } from '../../extensions/PluginBoundary';
import { registrationFor, registrations } from '../../extensions/registry';
import { useRegistrationCounts } from '../../hooks/useRegistrationCounts';
import { leadLabel } from '../../reminders/leadText';
import { fieldErrorId, invalidProps } from '../../utils/field-errors';
import { keys, useT } from '../../utils/i18n';
import type { RegistrationForm } from '../../utils/registration-form';
import type { RegistrationMode } from '../../utils/types-events';

const LEADS = [15, 60, 1440, 10080];
const MODES: RegistrationMode[] = ['none', 'external', 'builtin'];

type Props = {
  value: RegistrationForm;
  onChange: (patch: Partial<RegistrationForm>) => void;
  onEdit: (path: string) => void;
  errors: Readonly<Record<string, string>>;
  disabled: boolean;
  eventId: string | null;
  timezone: string;
};

/** The server's messages for paths under `registration.`, without the prefix. */
const sectionErrors = (errors: Readonly<Record<string, string>>): Record<string, string> =>
  Object.fromEntries(
    Object.entries(errors)
      .filter(([path]) => path.startsWith('registration.'))
      .map(([path, message]) => [path.slice('registration.'.length), message]),
  );

export function RegistrationSection({
  value,
  onChange,
  onEdit,
  errors,
  disabled,
  eventId,
  timezone,
}: Props) {
  const { t } = useT();
  const copy = keys.events.registration;
  const providers = registrations();
  const frozen = disabled || value.hidden || !value.installed;
  const canBuiltin = providers.length > 0 || value.mode === 'builtin';
  const provider = registrationFor(value.provider);
  const Section = provider?.EditorSection;
  const counts = useRegistrationCounts(eventId, value.mode === 'builtin' && !value.hidden);
  const capacity = /^\d+$/.test(value.capacity) ? Number(value.capacity) : null;
  const set = (patch: Partial<RegistrationForm>, path?: string) => {
    onChange(patch);
    if (path) onEdit(path);
  };
  const pick = (mode: RegistrationMode) =>
    set({
      mode,
      ...(mode === 'builtin' && !value.provider && providers[0]
        ? { provider: providers[0].id }
        : {}),
    });
  const input = (
    id: string,
    path: string,
    label: string,
    field: keyof RegistrationForm,
    extra: { type?: string; max?: number; hint?: string } = {},
  ) => (
    <div className="grid gap-2">
      <Label htmlFor={id}>{label}</Label>
      <Input
        id={id}
        type={extra.type ?? 'text'}
        maxLength={extra.max}
        min={extra.type === 'number' ? 1 : undefined}
        disabled={frozen}
        value={String(value[field])}
        {...invalidProps(id, errors[path])}
        onChange={(e) => set({ [field]: e.target.value }, path)}
      />
      {extra.hint ? <p className="text-xs text-muted-foreground">{extra.hint}</p> : null}
      <FieldError id={fieldErrorId(id)}>{errors[path]}</FieldError>
    </div>
  );
  return (
    <fieldset className="grid gap-4" disabled={disabled} data-testid="registration-section">
      <legend className="mb-2 text-sm font-medium">{t(copy.title)}</legend>
      {value.hidden ? (
        <p role="status" className="rounded-md border border-dashed p-2 text-sm">
          {t(copy.hidden)}
        </p>
      ) : (
        <>
          {!value.installed ? (
            <p role="status" className="rounded-md border border-dashed p-2 text-sm">
              {t(copy.not_installed)}
            </p>
          ) : null}
          <div role="radiogroup" aria-label={t(copy.mode_label)} className="grid gap-2">
            {MODES.filter((mode) => mode !== 'builtin' || canBuiltin).map((mode) => (
              <label key={mode} className="flex items-center gap-2 text-sm">
                <input
                  type="radio"
                  name="registration-mode"
                  value={mode}
                  checked={value.mode === mode}
                  disabled={frozen}
                  onChange={() => pick(mode)}
                />
                {t(copy[`mode_${mode}`])}
              </label>
            ))}
            {!canBuiltin ? (
              <p className="text-xs text-muted-foreground">{t(copy.no_provider)}</p>
            ) : null}
          </div>
          {value.mode === 'external'
            ? input('event-registration-url', 'registration.url', t(copy.url), 'url', {
                type: 'url',
                max: 2048,
              })
            : null}
          {value.mode === 'builtin' ? (
            <div className="grid gap-4">
              {providers.length > 1 ? (
                <div className="grid gap-2">
                  <Label htmlFor="event-registration-provider">{t(copy.provider)}</Label>
                  <NativeSelect
                    id="event-registration-provider"
                    value={value.provider}
                    disabled={frozen}
                    onChange={(e) =>
                      set({ provider: e.target.value, target: '' }, 'registration.provider')
                    }
                  >
                    {providers.map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.id}
                      </option>
                    ))}
                  </NativeSelect>
                </div>
              ) : null}
              {Section ? (
                <PluginBoundary name={`${value.provider}/registration`} fallback={null}>
                  <Section
                    target={value.target || null}
                    onChange={(target) => set({ target: target ?? '' }, 'registration.target')}
                    eventId={eventId}
                    capacity={capacity}
                    readOnly={frozen}
                    errors={sectionErrors(errors)}
                  />
                </PluginBoundary>
              ) : null}
              {input(
                'event-registration-capacity',
                'registration.capacity',
                t(copy.capacity),
                'capacity',
                {
                  type: 'number',
                  hint: t(copy.capacity_hint),
                },
              )}
              <div className="grid gap-4 sm:grid-cols-2">
                {input(
                  'event-registration-opens',
                  'registration.opens_at_local',
                  t(copy.opens),
                  'opens',
                  {
                    type: 'datetime-local',
                  },
                )}
                {input(
                  'event-registration-closes',
                  'registration.closes_at_local',
                  t(copy.closes),
                  'closes',
                  {
                    type: 'datetime-local',
                  },
                )}
              </div>
              <p className="-mt-2 text-xs text-muted-foreground">
                {t(copy.window_hint, { timezone })}
              </p>
              <div className="flex items-center gap-2">
                <Checkbox
                  id="event-registration-show-seats"
                  checked={value.show_seats}
                  disabled={frozen}
                  onCheckedChange={(on) => set({ show_seats: on === true })}
                />
                <Label htmlFor="event-registration-show-seats">{t(copy.show_seats)}</Label>
              </div>
              <div className="grid gap-2">
                <Label htmlFor="event-registration-reminder">{t(copy.reminder)}</Label>
                <NativeSelect
                  id="event-registration-reminder"
                  value={value.reminder}
                  disabled={frozen}
                  onChange={(e) =>
                    set({ reminder: e.target.value }, 'registration.reminder_minutes')
                  }
                >
                  <option value="">{t(copy.reminder_none)}</option>
                  {LEADS.map((lead) => (
                    <option key={lead} value={String(lead)}>
                      {leadLabel(t, lead)}
                    </option>
                  ))}
                </NativeSelect>
              </div>
              <Counts state={counts.state} retry={counts.retry} />
            </div>
          ) : null}
        </>
      )}
    </fieldset>
  );
}

function Counts({
  state,
  retry,
}: {
  state: ReturnType<typeof useRegistrationCounts>['state'];
  retry: () => void;
}) {
  const { t } = useT();
  const copy = keys.events.registration;
  if (state.kind === 'idle') return null;
  return (
    <div className="grid gap-2" data-testid="registration-counts">
      <h3 className="text-sm font-medium">{t(copy.counts_title)}</h3>
      {state.kind === 'loading' ? (
        <p role="status" className="text-sm text-muted-foreground">
          {t(copy.counts_loading)}
        </p>
      ) : state.kind === 'error' ? (
        <p role="alert" className="text-sm text-destructive">
          {t(copy.counts_error)}{' '}
          <button type="button" className="underline" onClick={retry}>
            {t(copy.counts_retry)}
          </button>
        </p>
      ) : state.items.length === 0 ? (
        <p className="text-sm text-muted-foreground">{t(copy.counts_empty)}</p>
      ) : (
        <table className="text-sm">
          <tbody>
            {state.items.map((row) => (
              <tr key={row.occurrence_key}>
                <th scope="row" className="pr-4 text-left font-normal">
                  {row.start_local ?? t(copy.counts_gone)}
                </th>
                <td>
                  {row.capacity === null
                    ? t(copy.counts_taken_open, { taken: row.taken })
                    : t(copy.counts_taken, { taken: row.taken, capacity: row.capacity })}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
