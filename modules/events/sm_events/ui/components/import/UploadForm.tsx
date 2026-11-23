import { Button } from '@simple-module-py/ui/components/ui/button';
import { Input } from '@simple-module-py/ui/components/ui/input';
import { Label } from '@simple-module-py/ui/components/ui/label';
import { NativeSelect } from '@simple-module-py/ui/components/ui/native-select';
import { type FormEvent, useState } from 'react';
import { formatBytes } from '../../utils/format';
import { keys, useT } from '../../utils/i18n';

export type TargetCalendar = { id: string; name: string; color: string; default_timezone: string };

/** Pick a calendar and a file. The size check is a courtesy (the same words as the server's
 *  refusal); the server's cap is the authority. */
export function UploadForm({
  calendars,
  maxBytes,
  busy,
  onUpload,
}: {
  calendars: TargetCalendar[];
  maxBytes: number;
  busy: boolean;
  onUpload: (calendarId: string, file: File) => void;
}) {
  const { t } = useT();
  const copy = keys.events.import;
  const [calendar, setCalendar] = useState(calendars[0]?.id ?? '');
  const [file, setFile] = useState<File | null>(null);
  const [tooLarge, setTooLarge] = useState(false);

  function submit(event: FormEvent) {
    event.preventDefault();
    if (!file || !calendar || busy) return;
    if (file.size > maxBytes) {
      setTooLarge(true);
      return;
    }
    onUpload(calendar, file);
  }

  if (calendars.length === 0) {
    return <p className="text-muted-foreground dark:text-zinc-400">{t(copy.no_calendars)}</p>;
  }
  return (
    <form onSubmit={submit} className="max-w-xl space-y-4">
      <p className="text-sm text-muted-foreground dark:text-zinc-400">{t(copy.hint)}</p>
      <div className="space-y-1">
        <Label htmlFor="events-import-calendar">{t(copy.calendar)}</Label>
        <NativeSelect
          id="events-import-calendar"
          value={calendar}
          onChange={(e) => setCalendar(e.target.value)}
        >
          {calendars.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </NativeSelect>
      </div>
      <div className="space-y-1">
        <Label htmlFor="events-import-file">{t(copy.file)}</Label>
        <Input
          id="events-import-file"
          type="file"
          accept=".ics,text/calendar"
          onChange={(e) => {
            setFile(e.target.files?.[0] ?? null);
            setTooLarge(false);
          }}
        />
      </div>
      {tooLarge && (
        <p role="alert" className="text-sm text-destructive dark:text-red-400">
          {t(copy.too_large, { max: formatBytes(maxBytes) })}
        </p>
      )}
      <Button type="submit" disabled={busy || !file}>
        {busy ? t(copy.uploading) : t(copy.upload)}
      </Button>
    </form>
  );
}
