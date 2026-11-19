/** The settings editor for a source whose module registered no form: JSON in a textarea,
 *  validated by the server. A value that is not JSON is reported here and never sent. */
import { FieldError } from '@simple-module-py/ui/components/ui/field';
import { Label } from '@simple-module-py/ui/components/ui/label';
import { Textarea } from '@simple-module-py/ui/components/ui/textarea';
import { useState } from 'react';
import { fieldErrorId, invalidProps } from '../../utils/field-errors';
import { keys, useT } from '../../utils/i18n';

type Props = {
  id: string;
  settings: Readonly<Record<string, unknown>>;
  /** `null`: what is typed is not a JSON object. */
  onChange: (next: Record<string, unknown> | null) => void;
  errors: Readonly<Record<string, string>>;
};

export function JsonSettings({ id, settings, onChange, errors }: Props) {
  const { t } = useT();
  const [text, setText] = useState(() => JSON.stringify(settings, null, 2));
  const [invalid, setInvalid] = useState(false);
  const server = Object.entries(errors)
    .map(([path, message]) => (path ? `${path}: ${message}` : message))
    .join(' ');
  const message = invalid ? t(keys.events.sources.invalid_json) : server;
  return (
    <div className="grid gap-2">
      <Label htmlFor={id}>{t(keys.events.sources.settings_json)}</Label>
      <Textarea
        id={id}
        className="font-mono"
        rows={6}
        value={text}
        spellCheck={false}
        {...invalidProps(id, message)}
        onChange={(e) => {
          setText(e.target.value);
          try {
            const parsed: unknown = JSON.parse(e.target.value);
            const ok = typeof parsed === 'object' && parsed !== null && !Array.isArray(parsed);
            setInvalid(!ok);
            onChange(ok ? (parsed as Record<string, unknown>) : null);
          } catch {
            setInvalid(true);
            onChange(null);
          }
        }}
      />
      <FieldError id={fieldErrorId(id)}>{message}</FieldError>
    </div>
  );
}
