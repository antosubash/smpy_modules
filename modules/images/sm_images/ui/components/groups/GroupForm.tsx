import { Button } from '@simple-module-py/ui/components/ui/button';
import { Input } from '@simple-module-py/ui/components/ui/input';
import { Label } from '@simple-module-py/ui/components/ui/label';
import { useState } from 'react';
import { errorText } from '../../utils/api-net';
import { keys, useT } from '../../utils/i18n';

/** Create a group (key + optional name) or edit one (the same two fields).
 *  A rejected `onSubmit` keeps the form open and shows the server's reason. */
export function GroupForm({
  initial,
  submitLabel,
  onSubmit,
  onCancel,
}: {
  initial?: { key: string; name: string | null };
  submitLabel: string;
  onSubmit: (value: { key: string; name: string | null }) => Promise<unknown>;
  onCancel: () => void;
}) {
  const { t } = useT();
  const text = keys.images.groups;
  const [key, setKey] = useState(initial?.key ?? '');
  const [name, setName] = useState(initial?.name ?? '');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await onSubmit({ key: key.trim(), name: name.trim() || null });
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <form
      className="grid gap-3 rounded-md border p-3 sm:grid-cols-2"
      data-testid="images-group-form"
      onSubmit={(e) => void submit(e)}
    >
      <div className="grid gap-1">
        <Label htmlFor="images-group-key">{t(text.key)}</Label>
        <Input
          id="images-group-key"
          value={key}
          maxLength={200}
          required
          onChange={(e) => setKey(e.target.value)}
        />
      </div>
      <div className="grid gap-1">
        <Label htmlFor="images-group-name">{t(text.name)}</Label>
        <Input
          id="images-group-name"
          value={name}
          maxLength={200}
          onChange={(e) => setName(e.target.value)}
        />
      </div>
      {error && (
        <p className="text-sm text-destructive sm:col-span-2" role="alert">
          {error}
        </p>
      )}
      <div className="flex gap-2 sm:col-span-2">
        <Button type="submit" disabled={busy || !key.trim()} data-testid="images-group-submit">
          {submitLabel}
        </Button>
        <Button type="button" variant="ghost" onClick={onCancel}>
          {t(text.edit_cancel)}
        </Button>
      </div>
    </form>
  );
}
