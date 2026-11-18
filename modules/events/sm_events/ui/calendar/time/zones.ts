/** The grid's time zone. Conversion itself lives in `utils/zones.ts`, re-exported here for
 *  the calendar's own code. */
import { browserZone } from '../../utils/zones';
import type { CalendarInfo } from '../types';

export * from '../../utils/zones';
export { browserZone as browserTimeZone } from '../../utils/zones';

export type TzMode = 'calendar' | 'mine';

/** The grid's zone: the one shown calendar's own, else the tenant's; or the browser's. */
export function gridTimeZone(
  mode: TzMode,
  shown: CalendarInfo[],
  tenantDefault: string,
  mine: string = browserZone(),
): string {
  if (mode === 'mine') return mine;
  const only = shown.length === 1 ? shown[0] : undefined;
  return only?.default_timezone || tenantDefault;
}
