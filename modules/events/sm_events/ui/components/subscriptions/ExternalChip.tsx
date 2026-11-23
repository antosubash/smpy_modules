/** An external entry on the calendar: the default chip, marked with an icon and, for a screen
 *  reader, where it comes from. Read-only: nothing here offers an edit. */
import { ExternalLink } from 'lucide-react';
import type { EventChipProps } from '../../calendar/types';
import { keys, useT } from '../../utils/i18n';

export default function ExternalChip(props: EventChipProps) {
  const { t } = useT();
  const { Default, occurrence } = props;
  return (
    <span
      className="flex min-w-0 max-w-full flex-1 items-center gap-1 overflow-hidden"
      data-testid="external-chip"
      title={occurrence.title}
    >
      <ExternalLink aria-hidden="true" className="size-3 shrink-0" />
      <Default {...props} />
      <span className="sr-only">
        {t(keys.events.subscriptions.from_label, { label: occurrence.origin_label ?? '' })}
      </span>
    </span>
  );
}
