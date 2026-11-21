/** The grid's time zone. Conversion itself lives in `utils/zones.ts`, re-exported here for
 *  the calendar's own code. */
import { browserZone } from '../../utils/zones';
import type { CalendarInfo } from '../types';

export * from '../../utils/zones';
export { browserZone as browserTimeZone } from '../../utils/zones';

export type TzMode = 'calendar' | 'mine';

/** The zone every shown calendar has as its default, or `null` when they differ (or none). */
export function sharedZone(shown: CalendarInfo[]): string | null {
  const zones = new Set(shown.map((c) => c.default_timezone).filter(Boolean));
  return zones.size === 1 ? ([...zones][0] ?? null) : null;
}

/** The grid's zone: the zone the shown calendars share, else the tenant's; or the browser's. */
export function gridTimeZone(
  mode: TzMode,
  shown: CalendarInfo[],
  tenantDefault: string,
  mine: string = browserZone(),
): string {
  if (mode === 'mine') return mine;
  return sharedZone(shown) ?? tenantDefault;
}
