import { useEffect, useState } from 'react';
import { reminderStatusOnce } from '../../utils/api-reminders';
import { keys, useT } from '../../utils/i18n';

/** The plain sentence, for everyone, when reminders cannot be delivered right now. The reason is
 *  a manager's detail and stays on the Delivery card. A failed read says nothing: the list below
 *  has its own error. */
export function UnavailableNotice() {
  const { t } = useT();
  const [unavailable, setUnavailable] = useState(false);
  useEffect(() => {
    let alive = true;
    reminderStatusOnce()
      .then((status) => alive && setUnavailable(!status.available))
      .catch(() => undefined);
    return () => {
      alive = false;
    };
  }, []);
  if (!unavailable) return null;
  return (
    <p
      role="status"
      data-testid="reminders-unavailable"
      className="rounded-md border p-3 text-sm text-muted-foreground"
    >
      {t(keys.events.reminders.control.unavailable)}
    </p>
  );
}
