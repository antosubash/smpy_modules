/** Why an occurrence cannot be changed, in words, for the chip's lock and the popover. */
import { keys } from '../utils/i18n';
import type { Occurrence } from '../utils/types-events';
import type { CalendarEditing, CalendarInfo } from './types';

export function lockReason(
  o: Occurrence,
  calendar: CalendarInfo | undefined,
  editing: CalendarEditing | undefined,
  tr: (key: string) => string,
): string | null {
  if (!editing || o.editable) return null;
  const copy = keys.events.calendar.detail;
  if (o.event_id === null) return tr(copy.external);
  if (!calendar?.can_write_events) return tr(copy.read_only);
  return o.event_status === 'published' ? tr(copy.needs_publish) : null;
}
