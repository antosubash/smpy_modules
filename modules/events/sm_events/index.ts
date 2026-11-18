/**
 * The public TS surface of the events module.
 *
 * `Calendar` is the reusable calendar component: month, week, day and list views with
 * filters and render slots. Its FullCalendar grid is a lazy chunk, so importing this
 * package costs a consumer that never renders a grid nothing but the shell.
 */

export { Calendar } from './ui/calendar/Calendar';
export type {
  CalendarEditing,
  CalendarInfo,
  CalendarProps,
  CalendarSlots,
  CalendarState,
  CalendarView,
  CreateSlot,
  DetailProps,
  EventChipProps,
  FilterOption,
  Occurrence,
  OccurrenceChange,
  OccurrenceFetcher,
  OccurrencePage,
  OccurrenceQuery,
  ToolbarSlotProps,
  TzMode,
} from './ui/calendar/types';
