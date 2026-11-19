// @vitest-environment happy-dom
import { act, createElement } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, expect, it } from 'vitest';

import type { EventCardHit } from '../../utils/types';
import { CardHits } from './CardHits';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
afterEach(() => {
  document.body.innerHTML = '';
});

const hit: EventCardHit = {
  kind: 'event',
  source_id: '3f2c6c1e-8f4e-4a45-9d0e-0a5b8f6f1c11',
  title: 'Open studio day',
  excerpt: '',
  image_url: '',
  url: '/events/open-studio-day',
  ics_url: '/events/open-studio-day.ics',
  locale: 'en',
  starts_at: '2026-12-02T09:00:00Z',
  ends_at: '2026-12-02T10:30:00Z',
  all_day: false,
  start_date: null,
  end_date: null,
  timezone: 'Europe/Vienna',
  attendance_mode: 'in_person',
  place: '',
  cancelled: false,
  when: 'Wednesday, December 2, 2026, 10:00 AM–11:30 AM CET',
};

it("shows the server's when-line, so the picker names the zone the email does", async () => {
  const root = createRoot(document.body.appendChild(document.createElement('div')));
  await act(async () =>
    root.render(createElement(CardHits, { hits: [hit], busy: false, onPick: () => {} })),
  );
  const text = document.body.textContent ?? '';
  expect(text).toContain('10:00 AM–11:30 AM CET');
  expect(text).not.toContain('GMT+1');
});
