/** What the calendar block is configured with, kept apart from its render so the eager
 *  registration (`EventsCalendarBlock`) can name the type and the bounds without reaching the
 *  render, `Calendar` or FullCalendar. */

export type EventsCalendarProps = {
  calendars: { slug: string }[];
  defaultView: 'month' | 'week' | 'day' | 'list';
  height: 'compact' | 'medium' | 'tall';
};

export const VIEWS = ['month', 'week', 'day', 'list'] as const;
/** The block's minimum heights in pixels: no free number, so a stored value cannot be absurd. */
export const HEIGHTS = { compact: 480, medium: 640, tall: 800 } as const;
export const HEIGHT_NAMES = ['compact', 'medium', 'tall'] as const;

export function minHeight(height: unknown): number {
  return HEIGHTS[
    HEIGHT_NAMES.includes(height as never) ? (height as keyof typeof HEIGHTS) : 'medium'
  ];
}
