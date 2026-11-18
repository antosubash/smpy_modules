// @vitest-environment happy-dom

import { afterEach, expect, it } from 'vitest';
import { TimezoneToggle } from '../calendar/TimezoneToggle';
import { EventPlace } from '../public/EventPlace';
import { LanguageSwitch } from '../public/LanguageSwitch';
import { ItemRow } from '../public/UpcomingList';
import { item } from './public-support';
import { mount } from './test-dom';

afterEach(() => {
  document.body.innerHTML = '';
});

it('names each language in itself, whatever language the page is in', async () => {
  const alternates = [
    { locale: 'en', url: '/events/a' },
    { locale: 'de', url: '/de/events/a' },
    { locale: 'x-default', url: '/events/a' },
  ];
  const english = await mount(<LanguageSwitch alternates={alternates} locale="en" />);
  expect(english.all('a').map((a) => a.textContent)).toEqual(['English', 'Deutsch']);
  const german = await mount(<LanguageSwitch alternates={alternates} locale="de" />);
  expect(german.all('a').map((a) => a.textContent)).toEqual(['English', 'Deutsch']);
});

it('an all-day row says so', async () => {
  const view = await mount(
    <ItemRow
      locale="en"
      item={item({ all_day: true, start_date: '2026-07-06', end_date: '2026-07-06' })}
    />,
  );
  expect(view.host.textContent).toContain('All day');
});

it('an online or hybrid event says how to attend', async () => {
  const place = {
    mode: 'online',
    venue_name: null,
    address: null,
    online_url: 'https://meet.example/x',
    latitude: null,
    longitude: null,
  };
  const online = await mount(<EventPlace place={place} />);
  expect(online.host.textContent).toContain('Online');
  const hybrid = await mount(
    <EventPlace place={{ ...place, mode: 'hybrid', venue_name: 'Hall' }} />,
  );
  expect(hybrid.host.textContent).toContain('In person and online');
});

it('the zone switch offers only "my time" when there is no calendar time to offer', async () => {
  const view = await mount(
    <TimezoneToggle
      mode="mine"
      calendarZone="UTC"
      myZone="Europe/Vienna"
      calendarTime={false}
      onMode={() => {}}
    />,
  );
  expect(view.all('button').map((b) => b.textContent)).toEqual(['My time Europe/Vienna']);
});
