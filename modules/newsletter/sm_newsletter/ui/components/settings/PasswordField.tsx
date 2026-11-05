import { Button } from '@simple-module-py/ui/components/ui/button';
import { Input } from '@simple-module-py/ui/components/ui/input';
import { Label } from '@simple-module-py/ui/components/ui/label';
import { useState } from 'react';

import { api, errorMessage } from '../../utils/api';
import { keys, useT } from '../../utils/i18n';

const PASSWORD_ID = 'newsletter-settings-password';

/** The server's bound on a stored password (`invalid_password`). */
const MAX_PASSWORD_LEN = 1024;

interface Props {
  hasPassword: boolean;
  disabled: boolean;
  /** Writing is allowed (`settings.edit`). Without it the field is only a status. */
  canWrite: boolean;
  onSaved: () => void;
}

/** The SMTP password, write-only: the server never returns it, so this field never
 *  pre-fills and only reports whether one is stored. A typed value lives in local
 *  state until it is sent through `putPassword`, then is dropped. */
export function PasswordField({ hasPassword, disabled, canWrite, onSaved }: Props) {
  const { t } = useT();
  const copy = keys.newsletter.settings.password;
  const [value, setValue] = useState('');
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const save = async () => {
    setPending(true);
    setError(null);
    try {
      await api.putPassword(value);
      setValue('');
      onSaved();
    } catch (e) {
      setError(errorMessage(e, t));
    } finally {
      setPending(false);
    }
  };

  return (
    <div className="grid gap-2">
      <Label htmlFor={PASSWORD_ID}>{t(copy.label)}</Label>
      <div className="flex flex-wrap gap-2">
        <Input
          id={PASSWORD_ID}
          type="password"
          className="max-w-sm"
          autoComplete="new-password"
          maxLength={MAX_PASSWORD_LEN}
          value={value}
          disabled={disabled || !canWrite || pending}
          placeholder={t(copy.placeholder)}
          onChange={(e) => setValue(e.target.value)}
        />
        {canWrite && (
          <Button
            type="button"
            variant="outline"
            disabled={disabled || pending || value.trim() === ''}
            onClick={() => void save()}
          >
            {pending ? t(copy.saving) : t(copy.save)}
          </Button>
        )}
      </div>
      <p className="text-sm text-muted-foreground">
        {hasPassword ? t(copy.saved) : t(copy.not_saved)}
        {canWrite && hasPassword ? ` ${t(copy.replace_hint)}` : ''}
      </p>
      {error && <p className="text-sm text-destructive">{error}</p>}
    </div>
  );
}
