import { keys, useT } from '../utils/i18n';

/** Above the title of a cancelled event or occurrence. `role="status"` so it is read out. */
export function CancelledBanner({ occurrence }: { occurrence: boolean }) {
  const { t } = useT();
  const copy = keys.events.public.event;
  return (
    <p role="status" className="rounded-md border border-destructive p-3 font-medium">
      {t(occurrence ? copy.cancelled_occurrence : copy.cancelled_banner)}
    </p>
  );
}
