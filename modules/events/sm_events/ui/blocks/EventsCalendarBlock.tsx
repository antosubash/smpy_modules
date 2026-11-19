/**
 * `EventsCalendar` Puck block: a read-only calendar of public events.
 *
 * Registered through pagebuilder's `lazyBlock`, so what is eager is only the fields, the defaults
 * and the labels: neither the block's render code nor `Calendar` (and FullCalendar behind it) is
 * in the registration's import graph, and a page without this block never downloads them. The
 * fallback holds the chosen height so the page does not jump when the chunk arrives.
 */

import type { ComponentConfig } from '@puckeditor/core';
import { lazyBlock } from '@simple-module-py/pagebuilder';

import { keys, type Translate, translate } from '../utils/i18n';
import { calendarsField, loadCalendarOptions, type Option } from './calendarField';
import { type EventsCalendarProps, HEIGHT_NAMES, minHeight, VIEWS } from './calendarProps';
import { oneOf, selectionOf } from './limits';
import { localizeFields } from './localizeFields';

const copy = keys.events.blocks;
type Fields = NonNullable<ComponentConfig<EventsCalendarProps>['fields']>;

function buildFields(tr: Translate, calendars: Option[]) {
  return {
    calendars: calendarsField(tr, copy.calendar.calendars, calendars),
    defaultView: {
      type: 'select' as const,
      label: tr(copy.calendar.default_view),
      options: [
        { label: tr(copy.calendar.view_month), value: 'month' },
        { label: tr(copy.calendar.view_week), value: 'week' },
        { label: tr(copy.calendar.view_day), value: 'day' },
        { label: tr(copy.calendar.view_list), value: 'list' },
      ],
    },
    height: {
      type: 'select' as const,
      label: tr(copy.calendar.height),
      options: [
        { label: tr(copy.calendar.height_compact), value: 'compact' },
        { label: tr(copy.calendar.height_medium), value: 'medium' },
        { label: tr(copy.calendar.height_tall), value: 'tall' },
      ],
    },
  };
}

/** The picker load in flight; the next `resolveFields` supersedes it. */
let picker: AbortController | null = null;

export const EventsCalendarBlock = lazyBlock<EventsCalendarProps>(
  () => import('./EventsCalendarRender').then((m) => m.EventsCalendarRender),
  {
    label: copy.calendar.label,
    // Static labels are keys; `resolveFields` below replaces them with text.
    fields: buildFields((key) => key, []) as unknown as Fields,
    defaultProps: { calendars: [], defaultView: 'month', height: 'medium' },
    resolveFields: async () => {
      picker?.abort();
      picker = new AbortController();
      const calendars = await loadCalendarOptions(picker.signal);
      return localizeFields(
        buildFields((key) => key, calendars),
        translate,
      ) as unknown as Fields;
    },
    // Stored props are editor input: normalised once on load; the render and the server bound
    // them again.
    resolveData: ({ props }, { trigger }) =>
      trigger === 'load'
        ? {
            props: {
              ...props,
              ...(selectionOf(props.calendars).bad
                ? {}
                : { calendars: selectionOf(props.calendars).slugs.map((slug) => ({ slug })) }),
              defaultView: oneOf(props.defaultView, VIEWS, 'month'),
              height: oneOf(props.height, HEIGHT_NAMES, 'medium'),
            },
          }
        : { props },
  },
  (props) => (
    <div className="container mx-auto px-4 py-4">
      <div aria-busy="true" style={{ minHeight: minHeight(props.height) }} />
    </div>
  ),
);
