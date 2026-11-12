import { Button } from '@simple-module-py/ui/components/ui/button';
import { Checkbox } from '@simple-module-py/ui/components/ui/checkbox';
import { Input } from '@simple-module-py/ui/components/ui/input';
import { Label } from '@simple-module-py/ui/components/ui/label';
import { NativeSelect } from '@simple-module-py/ui/components/ui/native-select';
import { Textarea } from '@simple-module-py/ui/components/ui/textarea';
import { useState } from 'react';

import { api, errorMessage } from '../../utils/api';
import { keys, useT } from '../../utils/i18n';
import type { SettingsOut, SettingsUpdate } from '../../utils/types';
import { Field, Section } from './FormParts';
import { PasswordField } from './PasswordField';
import { TestRecipientsSection } from './TestRecipientsSection';

// The server's input bounds (`web/schemas/settings.py`).
const MAX = { host: 253, username: 320, from_name: 200, physical_address: 500 } as const;

/** The fields that, when changed, make the server drop the stored password
 *  (mirrors the server's `SERVER_FIELDS`). */
const SERVER_FIELDS = ['smtp_host', 'smtp_port', 'smtp_security', 'smtp_username'] as const;

type Draft = Omit<SettingsOut, 'has_password'>;

function toDraft(s: SettingsOut): Draft {
  const { has_password: _hasPassword, ...rest } = s;
  return rest;
}

interface Props {
  initial: SettingsOut;
  /** Holds `settings.edit`; without it the form is read-only. */
  canWrite: boolean;
}

/** The newsletter settings: transport, sender, limits and tracking. The SMTP password
 *  is a separate write-only field. A change to a server field warns that the stored
 *  password goes with it; the server does the clearing and answers `password_cleared`. */
export function SettingsForm({ initial, canWrite }: Props) {
  const { t } = useT();
  const copy = keys.newsletter.settings;
  const [saved, setSaved] = useState<SettingsOut>(initial);
  const [draft, setDraft] = useState<Draft>(toDraft(initial));
  const [hasPassword, setHasPassword] = useState(initial.has_password);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const set = <K extends keyof Draft>(key: K, value: Draft[K]) =>
    setDraft((d) => ({ ...d, [key]: value }));
  const num = (key: 'smtp_port' | 'daily_limit' | 'per_minute_limit', raw: string) =>
    set(key, raw === '' ? 0 : Number(raw));

  const serverChanged = SERVER_FIELDS.some((f) => draft[f] !== saved[f]);
  const readOnly = !canWrite;
  const busy = pending || readOnly;
  const smtp = draft.transport === 'smtp';

  const save = async () => {
    setPending(true);
    setError(null);
    setNotice(null);
    try {
      const out = await api.putSettings(draft as SettingsUpdate);
      const { password_cleared, ...next } = out;
      setSaved(next);
      setDraft(toDraft(next));
      setHasPassword(next.has_password);
      setNotice(password_cleared ? t(copy.password_cleared_notice) : t(copy.saved_notice));
    } catch (e) {
      setError(errorMessage(e, t));
    } finally {
      setPending(false);
    }
  };

  const id = (name: string) => `newsletter-settings-${name}`;

  return (
    <form
      className="grid max-w-3xl gap-6"
      onSubmit={(e) => {
        e.preventDefault();
        if (!busy) void save();
      }}
    >
      {readOnly && <p className="text-sm text-muted-foreground">{t(copy.read_only_note)}</p>}

      <Section title={t(copy.transport.title)}>
        <Field id={id('transport')} label={t(copy.transport.label)}>
          <NativeSelect
            id={id('transport')}
            value={draft.transport}
            disabled={busy}
            onChange={(e) => set('transport', e.target.value as Draft['transport'])}
          >
            <option value="smtp">{t(copy.transport.smtp)}</option>
            <option value="console">{t(copy.transport.console)}</option>
          </NativeSelect>
        </Field>
        <Field id={id('host')} label={t(copy.transport.host)}>
          <Input
            id={id('host')}
            maxLength={MAX.host}
            value={draft.smtp_host}
            disabled={busy || !smtp}
            onChange={(e) => set('smtp_host', e.target.value)}
          />
        </Field>
        <Field id={id('port')} label={t(copy.transport.port)}>
          <Input
            id={id('port')}
            type="number"
            min={1}
            max={65535}
            value={draft.smtp_port}
            disabled={busy || !smtp}
            onChange={(e) => num('smtp_port', e.target.value)}
          />
        </Field>
        <Field id={id('security')} label={t(copy.transport.security)}>
          <NativeSelect
            id={id('security')}
            value={draft.smtp_security}
            disabled={busy || !smtp}
            onChange={(e) => set('smtp_security', e.target.value as Draft['smtp_security'])}
          >
            <option value="starttls">{t(copy.transport.starttls)}</option>
            <option value="tls">{t(copy.transport.tls)}</option>
          </NativeSelect>
        </Field>
        <Field id={id('username')} label={t(copy.transport.username)}>
          <Input
            id={id('username')}
            maxLength={MAX.username}
            autoComplete="off"
            value={draft.smtp_username}
            disabled={busy || !smtp}
            onChange={(e) => set('smtp_username', e.target.value)}
          />
        </Field>
        <PasswordField
          hasPassword={hasPassword}
          disabled={pending || serverChanged}
          canWrite={canWrite}
          onSaved={() => {
            setHasPassword(true);
            setError(null);
            setNotice(t(copy.password_saved_notice));
          }}
        />
        {serverChanged && hasPassword && (
          <p role="alert" className="text-sm text-amber-700 dark:text-amber-400">
            {t(copy.server_change_clears_password)}
          </p>
        )}
      </Section>

      <Section title={t(copy.sender.title)}>
        <Field id={id('from-address')} label={t(copy.sender.from_address)}>
          <Input
            id={id('from-address')}
            type="email"
            value={draft.from_address}
            disabled={busy}
            onChange={(e) => set('from_address', e.target.value)}
          />
        </Field>
        <Field id={id('from-name')} label={t(copy.sender.from_name)}>
          <Input
            id={id('from-name')}
            maxLength={MAX.from_name}
            value={draft.from_name}
            disabled={busy}
            onChange={(e) => set('from_name', e.target.value)}
          />
        </Field>
        <Field id={id('reply-to')} label={t(copy.sender.reply_to)}>
          <Input
            id={id('reply-to')}
            type="email"
            value={draft.reply_to}
            disabled={busy}
            onChange={(e) => set('reply_to', e.target.value)}
          />
        </Field>
        <Field
          id={id('physical')}
          label={t(copy.sender.physical_address)}
          hint={t(copy.sender.physical_address_hint)}
        >
          <Textarea
            id={id('physical')}
            maxLength={MAX.physical_address}
            rows={3}
            value={draft.physical_address}
            disabled={busy}
            onChange={(e) => set('physical_address', e.target.value)}
          />
        </Field>
      </Section>

      <Section title={t(copy.limits.title)}>
        <Field id={id('daily')} label={t(copy.limits.daily)}>
          <Input
            id={id('daily')}
            type="number"
            min={1}
            value={draft.daily_limit}
            disabled={busy}
            onChange={(e) => num('daily_limit', e.target.value)}
          />
        </Field>
        <Field id={id('per-minute')} label={t(copy.limits.per_minute)}>
          <Input
            id={id('per-minute')}
            type="number"
            min={1}
            value={draft.per_minute_limit}
            disabled={busy}
            onChange={(e) => num('per_minute_limit', e.target.value)}
          />
        </Field>
      </Section>

      <TestRecipientsSection
        key={saved.test_send_extra_recipients.join('\n')}
        value={draft.test_send_extra_recipients}
        disabled={busy}
        onChange={(next) => set('test_send_extra_recipients', next)}
      />

      <Section title={t(copy.tracking.title)}>
        <p className="text-sm text-muted-foreground">{t(copy.tracking_note)}</p>
        {(
          [
            ['tracking_opens', 'opens', copy.tracking.opens],
            ['tracking_clicks', 'clicks', copy.tracking.clicks],
          ] as const
        ).map(([key, name, label]) => (
          <div key={key} className="flex items-center gap-2">
            <Checkbox
              id={id(name)}
              checked={draft[key]}
              disabled={busy}
              onCheckedChange={(v) => set(key, v === true)}
            />
            <Label htmlFor={id(name)}>{t(label)}</Label>
          </div>
        ))}
      </Section>

      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
      {notice && (
        <p role="status" className="text-sm text-muted-foreground">
          {notice}
        </p>
      )}

      {canWrite && (
        <div>
          <Button type="submit" disabled={pending}>
            {pending ? t(copy.saving) : t(copy.save)}
          </Button>
        </div>
      )}
    </form>
  );
}
