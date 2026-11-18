import { Button } from '@simple-module-py/ui/components/ui/button';
import { Input } from '@simple-module-py/ui/components/ui/input';
import { Label } from '@simple-module-py/ui/components/ui/label';
import { NativeSelect } from '@simple-module-py/ui/components/ui/native-select';
import { type FormEvent, useState } from 'react';
import { errorText } from '../../utils/api';
import { keys, useT } from '../../utils/i18n';
import { ownLanguageName } from '../../utils/language';

/** Name a new private link and choose its language. Submitting is the whole interaction: the
 *  link comes back through `onCreate` and is shown by the parent, not here. */
export function CreateLinkForm({
  locales,
  onCreate,
}: {
  locales: string[];
  onCreate: (input: { label: string; locale: string | null }) => Promise<void>;
}) {
  const { t } = useT();
  const copy = keys.events.feeds;
  const [label, setLabel] = useState('');
  const [locale, setLocale] = useState(locales[0] ?? '');
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (pending || !label.trim()) return;
    setPending(true);
    setError(null);
    try {
      await onCreate({ label: label.trim(), locale: locales.length > 1 ? locale : null });
      setLabel('');
    } catch (e) {
      setError(errorText(e, keys.events.errors.calendar_gone));
    } finally {
      setPending(false);
    }
  }

  return (
    <form onSubmit={(e) => void submit(e)} className="space-y-2">
      <div className="space-y-1">
        <Label htmlFor="events-feed-label">{t(copy.label)}</Label>
        <Input
          id="events-feed-label"
          value={label}
          maxLength={100}
          placeholder={t(copy.label_placeholder)}
          onChange={(e) => setLabel(e.target.value)}
        />
      </div>
      {locales.length > 1 && (
        <div className="space-y-1">
          <Label htmlFor="events-feed-locale">{t(copy.language)}</Label>
          <NativeSelect
            id="events-feed-locale"
            value={locale}
            onChange={(e) => setLocale(e.target.value)}
          >
            {locales.map((code) => (
              <option key={code} value={code}>
                {ownLanguageName(code)}
              </option>
            ))}
          </NativeSelect>
        </div>
      )}
      {error && (
        <p className="text-sm text-destructive" role="alert">
          {error}
        </p>
      )}
      <Button type="submit" disabled={pending || !label.trim()}>
        {pending ? t(copy.creating) : t(copy.create)}
      </Button>
    </form>
  );
}
