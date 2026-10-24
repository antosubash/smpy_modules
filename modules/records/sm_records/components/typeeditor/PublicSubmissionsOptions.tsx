import { Input } from '@simple-module-py/ui/components/ui/input';
import { Label } from '@simple-module-py/ui/components/ui/label';
import { Switch } from '@simple-module-py/ui/components/ui/switch';
import { Textarea } from '@simple-module-py/ui/components/ui/textarea';
import { useEffect, useState } from 'react';
import { keys, useT } from '../../utils/i18n';
import { type PublicSubmissionsConfig, parseRecipients } from '../../utils/public-submissions';

/** `contracts.public_submissions.MAX_NOTIFY_TO`. */
const MAX_NOTIFY_TO = 10;

function NumberField({
  id,
  label,
  help,
  value,
  min,
  onChange,
}: {
  id: string;
  label: string;
  help?: string;
  value: number;
  min: number;
  onChange: (value: number) => void;
}) {
  return (
    <div className="grid gap-1.5">
      <Label htmlFor={id}>{label}</Label>
      <Input
        id={id}
        type="number"
        min={min}
        className="w-32"
        value={String(value)}
        onChange={(e) => {
          const next = Number.parseInt(e.target.value, 10);
          if (!Number.isNaN(next)) onChange(next);
        }}
      />
      {help && <p className="text-sm text-muted-foreground">{help}</p>}
    </div>
  );
}

function SwitchField({
  id,
  label,
  help,
  checked,
  onChange,
}: {
  id: string;
  label: string;
  help?: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
}) {
  return (
    <div className="grid gap-1">
      <div className="flex items-center gap-2">
        <Switch id={id} checked={checked} onCheckedChange={(c) => onChange(c === true)} />
        <Label htmlFor={id} className="font-normal">
          {label}
        </Label>
      </div>
      {help && <p className="text-sm text-muted-foreground">{help}</p>}
    </div>
  );
}

/**
 * The kind-specific half of the public-submissions card: who is notified and
 * how long submissions are kept (contact form), double opt-in and the purge of
 * unconfirmed signups (newsletter), and the consent checkbox both share.
 * Split out of `PublicSubmissionsCard` for the 300-line cap.
 */
export function PublicSubmissionsOptions({
  config,
  contentLocales,
  onChange,
}: {
  config: PublicSubmissionsConfig;
  contentLocales: string[];
  onChange: (patch: Partial<PublicSubmissionsConfig>) => void;
}) {
  const { t } = useT();
  const ps = keys.records.public_submissions;
  // The textarea's own text: parsing on every keystroke would eat the comma
  // or newline just typed. Re-read when a save hands back another list.
  const [recipients, setRecipients] = useState(config.notify_to.join('\n'));
  useEffect(() => {
    setRecipients((text) =>
      JSON.stringify(parseRecipients(text)) === JSON.stringify(config.notify_to)
        ? text
        : config.notify_to.join('\n'),
    );
  }, [config.notify_to]);
  const locales = contentLocales.length > 0 ? contentLocales : ['en'];
  const setConsentText = (locale: string, text: string) => {
    const next = { ...config.consent.text, [locale]: text };
    if (!text) delete next[locale];
    onChange({ consent: { ...config.consent, text: next } });
  };

  return (
    <div className="grid gap-4">
      {config.kind === 'form' ? (
        <>
          <div className="grid gap-1.5">
            <Label htmlFor="public-submissions-notify-to">{t(ps.notify_to)}</Label>
            <Textarea
              id="public-submissions-notify-to"
              rows={3}
              value={recipients}
              placeholder="team@example.com"
              onChange={(e) => {
                setRecipients(e.target.value);
                onChange({ notify_to: parseRecipients(e.target.value) });
              }}
            />
            <p className="text-sm text-muted-foreground">
              {t(ps.notify_to_help, { max: MAX_NOTIFY_TO })}
            </p>
            {config.notify_to.length === 0 && (
              <p className="text-sm text-amber-700 dark:text-amber-400" role="note">
                {t(ps.no_recipient)}
              </p>
            )}
          </div>
          <NumberField
            id="public-submissions-retention"
            label={t(ps.retention_days)}
            help={t(ps.retention_days_help)}
            value={config.retention_days}
            min={0}
            onChange={(retention_days) => onChange({ retention_days })}
          />
        </>
      ) : (
        <>
          <SwitchField
            id="public-submissions-double-opt-in"
            label={t(ps.double_opt_in)}
            help={t(ps.double_opt_in_help)}
            checked={config.double_opt_in}
            onChange={(double_opt_in) => onChange({ double_opt_in })}
          />
          <NumberField
            id="public-submissions-pending-purge"
            label={t(ps.pending_purge_days)}
            value={config.pending_purge_days}
            min={1}
            onChange={(pending_purge_days) => onChange({ pending_purge_days })}
          />
        </>
      )}

      <SwitchField
        id="public-submissions-consent"
        label={t(ps.consent_required)}
        checked={config.consent.required}
        onChange={(required) => onChange({ consent: { ...config.consent, required } })}
      />
      {config.consent.required &&
        locales.map((locale) => (
          <div key={locale} className="grid gap-1.5">
            <Label htmlFor={`public-submissions-consent-${locale}`}>
              {t(ps.consent_text, { locale })}
            </Label>
            <Textarea
              id={`public-submissions-consent-${locale}`}
              rows={2}
              value={config.consent.text[locale] ?? ''}
              onChange={(e) => setConsentText(locale, e.target.value)}
            />
          </div>
        ))}
      {config.consent.required && (
        <p className="-mt-2 text-sm text-muted-foreground">{t(ps.consent_text_help)}</p>
      )}
    </div>
  );
}
