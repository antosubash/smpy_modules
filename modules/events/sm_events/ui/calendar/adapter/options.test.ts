import interactionPlugin from '@fullcalendar/react/interaction';
import { describe, expect, it } from 'vitest';
import { baseOptions, localeFor, localeOptions, PLUGINS } from './options';

describe('localeFor', () => {
  it('loads the German locale data, which starts the week on Monday', () => {
    const de = localeFor('de');
    expect(de).not.toBe('en');
    expect((de as { week?: { dow: number } }).week?.dow).toBe(1);
  });
  it('follows a regional variant', () => {
    expect(localeFor('de-AT')).not.toBe('en');
  });
  it('falls back to the built-in English', () => {
    expect(localeFor('en')).toBe('en');
    expect(localeFor(undefined)).toBe('en');
    expect(localeFor('fr')).toBe('en');
  });
});

describe('localeOptions', () => {
  it('registers the German data and names it', () => {
    expect(localeOptions('de')).toMatchObject({ locale: 'de' });
    expect(localeOptions('de').locales).toHaveLength(1);
  });
  it('returns the same locales array every time, so the grid is not re-initialised', () => {
    expect(localeOptions('de').locales).toBe(localeOptions('de').locales);
    expect(localeOptions('de-AT').locales).toBe(localeOptions('de').locales);
  });
  it('leaves English on the built-in data', () => {
    expect(localeOptions('en')).toEqual({ locale: 'en' });
  });
});

describe('baseOptions', () => {
  it('turns the toolbar off and makes events interactive', () => {
    const options = baseOptions();
    expect(options.headerToolbar).toBe(false);
    expect(options.eventInteractive).toBe(true);
    expect(options.fixedWeekCount).toBe(false);
    expect(options.nowIndicator).toBe(true);
    expect(options.dayMaxEvents).toBe(true);
  });
});

describe('PLUGINS', () => {
  it('includes the interaction plugin, without which drag, resize and select do nothing', () => {
    expect(PLUGINS).toContain(interactionPlugin);
  });
});
