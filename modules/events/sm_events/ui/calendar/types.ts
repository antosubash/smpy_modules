/** The public surface of the `Calendar` component (re-exported from `index.ts`) and the
 *  internal contract between the shell and the FullCalendar adapter. No FullCalendar type
 *  appears here: replacing the library means rewriting `adapter/` only. */
import type { ComponentType, ReactNode } from 'react';
import type { Visibility } from '../utils/types';
import type { Occurrence, OccurrencePage } from '../utils/types-events';
import type { Range } from './time/range';
import type { TzMode } from './time/zones';

export type { Occurrence, OccurrencePage, TzMode };

export type CalendarView = 'month' | 'week' | 'day' | 'list';
export const CALENDAR_VIEWS: readonly CalendarView[] = ['month', 'week', 'day', 'list'];

export type CalendarInfo = {
  id: string;
  name: string;
  color: string;
  visibility: Visibility;
  default_timezone: string;
  can_write_events: boolean;
};
export type FilterOption = { id: string; label: string; color?: string | null };

/** Aware ISO UTC, half-open. */
export type OccurrenceQuery = {
  start: string;
  end: string;
  calendars: string[];
  categories: string[];
  types: string[];
  locale: string;
};
export type FilterQuery = Omit<OccurrenceQuery, 'start' | 'end'>;
export type OccurrenceFetcher = (
  q: OccurrenceQuery,
  signal: AbortSignal,
) => Promise<OccurrencePage>;

/** `date` is YYYY-MM-DD in the grid's time zone. */
export type CalendarState = {
  view: CalendarView;
  date: string;
  tzMode: TzMode;
  calendars: string[];
  categories: string[];
  types: string[];
};

/** Instants for a timed slot; dates with an exclusive end for an all-day one. */
export type CreateSlot = { allDay: boolean; start: string; end: string };
export type OccurrenceChange = {
  occurrence: Occurrence;
  /** `reschedule` (the Move dialog) names both ends; a drag moves or resizes one. */
  kind: 'move' | 'resize' | 'reschedule';
  start: string;
  end: string;
  allDay: boolean;
};
export type CalendarEditing = {
  canCreate: boolean;
  onCreate: (slot: CreateSlot) => void;
  /** Resolves `true` to keep the grid's optimistic position, `false` to revert it. */
  onChange: (change: OccurrenceChange) => Promise<boolean>;
  /** Opens the Move dialog; `returnFocus` is the event's element, for when it closes. */
  onMove: (occurrence: Occurrence, returnFocus?: HTMLElement | null) => void;
  pendingKeys: ReadonlySet<string>;
};

export type EventChipProps = {
  occurrence: Occurrence;
  view: CalendarView;
  timeText: string;
  /** A write on this occurrence is in flight. */
  pending?: boolean;
  /** Why the viewer cannot change it, when they could on another occurrence. */
  lockReason?: string | null;
  Default: ComponentType<EventChipProps>;
};
export type DetailProps = {
  occurrence: Occurrence;
  gridTimeZone: string;
  close: () => void;
  actions: ReactNode;
  lockReason?: string | null;
  Default: ComponentType<DetailProps>;
};
export type ToolbarSlotProps = {
  state: CalendarState;
  range: { start: string; end: string } | null;
};
export type CalendarSlots = {
  EventChip?: ComponentType<EventChipProps>;
  Detail?: ComponentType<DetailProps>;
  ToolbarStart?: ComponentType<ToolbarSlotProps>;
  ToolbarEnd?: ComponentType<ToolbarSlotProps>;
};

export type CalendarProps = {
  fetchOccurrences: OccurrenceFetcher;
  calendars: CalendarInfo[];
  categories?: FilterOption[];
  /** The type filter shows only with two or more types. */
  types?: FilterOption[];
  /** The tenant's zone, for "calendar time" over several calendars. */
  defaultTimezone: string;
  initialState?: Partial<CalendarState>;
  onStateChange?: (state: CalendarState) => void;
  /** Absent: read-only (the public site). */
  editing?: CalendarEditing;
  slots?: CalendarSlots;
  /** Bump to invalidate the cache and refetch. */
  refreshToken?: number;
};

/** Internal: what the shell can ask of the grid. */
export type GridHandle = {
  today(): void;
  prev(): void;
  next(): void;
  setView(view: CalendarView): void;
  gotoDate(date: string): void;
  focusEvent(key: string): void;
};
export type RangeChange = { visible: Range; title: string; view: CalendarView; date: string };
export type GridProps = {
  view: CalendarView;
  date: string;
  timeZone: string;
  locale: string | undefined;
  items: Occurrence[];
  editing?: CalendarEditing;
  renderChip: (occurrence: Occurrence, timeText: string) => ReactNode;
  onRangeChange: (change: RangeChange) => void;
  onEventOpen: (occurrence: Occurrence, element: HTMLElement) => void;
  ariaLabel: string;
  noEventsText: string;
};
