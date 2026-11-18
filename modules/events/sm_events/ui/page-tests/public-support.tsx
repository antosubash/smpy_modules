/** Fixtures for the public screens' tests. */
import type { PublicIndexProps, PublicListItem } from '../public/types';

export function item(overrides: Partial<PublicListItem> = {}): PublicListItem {
  return {
    key: 'e1:1',
    url: '/events/concert',
    title: 'Concert',
    lang: 'en',
    all_day: false,
    start_local: '2026-07-06T10:00',
    end_local: '2026-07-06T11:30',
    start_date: null,
    end_date: null,
    timezone: 'Europe/Vienna',
    show_timezone: false,
    status: 'confirmed',
    rescheduled: false,
    calendar: { slug: 'team', name: 'Team', color: '#2563eb' },
    category: null,
    venue_name: null,
    attendance_mode: 'in_person',
    summary: null,
    image: null,
    ...overrides,
  };
}

export function indexProps(overrides: Partial<PublicIndexProps> = {}): PublicIndexProps {
  return {
    locale: 'en',
    title: 'Events',
    page: 1,
    page_count: 1,
    groups: [{ month: '2026-07', items: [item()] }],
    calendars: [
      {
        id: 'c1',
        slug: 'team',
        name: 'Team',
        color: '#2563eb',
        description: null,
        default_timezone: 'Europe/Vienna',
        url: '/events/c/team',
        feed_url: '/events/c/team.ics',
      },
    ],
    calendar: null,
    categories: [{ id: 'k1', slug: 'talks', name: 'Talks', color: null }],
    category: null,
    view: 'list',
    feed_url: '/events/calendar.ics',
    default_timezone: 'Europe/Vienna',
    api_url: '/events/api/occurrences',
    alternates: [],
    ...overrides,
  };
}
