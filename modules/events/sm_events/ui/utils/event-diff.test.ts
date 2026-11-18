// @vitest-environment happy-dom
import { describe, expect, it } from 'vitest';
import { diffForms } from './event-diff';
import { blankText, emptyForm } from './event-form';

const base = () => {
  const form = emptyForm('Europe/Vienna', ['en', 'de']);
  form.texts.en = {
    ...blankText(true),
    title: 'Concert',
    description: '<p>Doors at <b>nine</b></p>',
  };
  return form;
};

describe('diffForms', () => {
  it('is empty for equal forms', () => {
    expect(diffForms(base(), base())).toEqual([]);
  });
  it('names each differing field with both values', () => {
    const theirs = base();
    const mine = { ...base(), venue_name: 'Hall', start: '2026-07-01T12:00', cancelled: true };
    mine.texts = {
      ...mine.texts,
      en: {
        ...(mine.texts.en ?? blankText()),
        title: 'Concert!',
        description: '<p>Doors at ten</p>',
      },
    };
    const found = diffForms(mine, theirs);
    const by = Object.fromEntries(found.map((d) => [d.id, d]));
    expect(by.venue_name).toMatchObject({ label: 'Venue', theirs: '(empty)', mine: 'Hall' });
    expect(by.cancelled).toMatchObject({ theirs: 'No', mine: 'Yes' });
    expect(by['texts.en.title']).toMatchObject({
      label: 'Title (English)',
      theirs: 'Concert',
      mine: 'Concert!',
    });
    expect(by['texts.en.description']).toMatchObject({
      theirs: 'Doors at nine',
      mine: 'Doors at ten',
    });
    expect(by.start?.mine).toBe('2026-07-01T12:00');
  });
  it('reports a language one side lacks', () => {
    const mine = base();
    mine.texts.de = { ...blankText(true), title: 'Konzert' };
    const found = diffForms(mine, base());
    expect(found).toEqual([
      expect.objectContaining({
        id: 'texts.de',
        label: 'German: text added or removed',
        mine: 'Yes',
        theirs: 'No',
      }),
    ]);
  });
});
