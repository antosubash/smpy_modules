/**
 * `UpcomingEvents` Puck block: the next public events, as a list or as cards.
 *
 * Calendars and the category are referenced by slug and resolved by the server on every
 * request: no calendar chosen means every public calendar, a choice that resolves to nothing
 * means nothing, and a calendar that stopped being public simply shows nothing. The pickers read
 * the anonymous route, which lists exactly what a block can render.
 *
 * Labels are catalogue keys (this is a module-scope constant, so pagebuilder's `localizeConfig`
 * resolves the static ones); the fields `resolveFields` builds are resolved here.
 */

import type { ComponentConfig } from '@puckeditor/core';
import { localizeFields } from '@simple-module-py/pagebuilder';

import { keys, type Translate, translate } from '../utils/i18n';
import { fetchBlockCalendars } from './api-blocks';
import { countField } from './CountField';
import { calendarsField, type Option } from './calendarField';
import { clampCount, oneOf, selectionOf, UPCOMING_DEFAULT } from './limits';
import {
  HEADING_MAX,
  LAYOUTS,
  type UpcomingEventsProps,
  UpcomingEventsRender,
} from './UpcomingEventsRender';

const copy = keys.events.blocks;
type Fields = NonNullable<ComponentConfig<UpcomingEventsProps>['fields']>;

function buildFields(tr: Translate, calendars: Option[], categories: Option[]) {
  return {
    heading: { type: 'text' as const, label: tr(copy.upcoming.heading) },
    calendars: calendarsField(tr, copy.upcoming.calendars, calendars),
    category: {
      type: 'select' as const,
      label: tr(copy.upcoming.category),
      options: [{ label: tr(copy.fields.category_any), value: '' }, ...categories],
    },
    count: countField(tr(copy.upcoming.count)),
    layout: {
      type: 'radio' as const,
      label: tr(copy.upcoming.layout),
      options: [
        { label: tr(copy.upcoming.layout_list), value: 'list' },
        { label: tr(copy.upcoming.layout_cards), value: 'cards' },
      ],
    },
    showImages: {
      type: 'radio' as const,
      label: tr(copy.upcoming.show_images),
      options: [
        { label: 'true', value: true },
        { label: 'false', value: false },
      ],
    },
  };
}

/** The picker load in flight; the next `resolveFields` supersedes it. */
let picker: AbortController | null = null;

async function choices(
  signal: AbortSignal,
): Promise<{ calendars: Option[]; categories: Option[] }> {
  try {
    const answer = await fetchBlockCalendars([], '', signal);
    return {
      calendars: answer.calendars.map((c) => ({ label: c.name, value: c.slug })),
      categories: answer.categories.map((c) => ({ label: c.name, value: c.slug })),
    };
  } catch {
    return { calendars: [], categories: [] };
  }
}

export const UpcomingEventsBlock: ComponentConfig<UpcomingEventsProps> = {
  label: copy.upcoming.label,
  // Static labels are keys; `resolveFields` below replaces them with text.
  fields: buildFields((key) => key, [], []) as unknown as Fields,
  defaultProps: {
    heading: 'Upcoming events',
    calendars: [],
    category: '',
    count: UPCOMING_DEFAULT,
    layout: 'list',
    showImages: true,
  },
  resolveFields: async () => {
    picker?.abort();
    picker = new AbortController();
    const { calendars, categories } = await choices(picker.signal);
    return localizeFields(
      buildFields((key) => key, calendars, categories),
      translate,
    ) as unknown as Fields;
  },
  // Stored props are editor input and may predate the bounds: normalised once on load, not per
  // keystroke (clamping while the author types would snap a cleared field back). The render and
  // the server's own validation bound them again.
  resolveData: ({ props }, { trigger }) =>
    trigger === 'load'
      ? {
          props: {
            ...props,
            count: clampCount(props.count),
            layout: oneOf(props.layout, LAYOUTS, 'list'),
            // An unreadable selection is kept as it is (it shows nothing): rewriting it would
            // turn "nothing" into "every calendar".
            ...(selectionOf(props.calendars).bad
              ? {}
              : { calendars: selectionOf(props.calendars).slugs.map((slug) => ({ slug })) }),
            heading: typeof props.heading === 'string' ? props.heading.slice(0, HEADING_MAX) : '',
          },
        }
      : { props },
  render: UpcomingEventsRender,
};
