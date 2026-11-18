import { describe, expect, it } from 'vitest';
import { blankText, emptyForm, type FormState, type TextForm, toPatch } from './event-form';
import { mergeOnto } from './form-merge';

/** A loaded event's form: English present, German absent. */
function loaded(): FormState {
  const form = emptyForm('Europe/Vienna', ['en', 'de']);
  return {
    ...form,
    start: '2026-12-01T10:00',
    end: '2026-12-01T11:00',
    venue_name: 'Seminar Room B',
    rrule: 'FREQ=WEEKLY',
    texts: { en: { ...blankText(true), title: 'Talk', summary: 'S' }, de: blankText() },
  };
}
const withText = (form: FormState, locale: string, patch: Partial<TextForm>): FormState => ({
  ...form,
  texts: { ...form.texts, [locale]: { ...(form.texts[locale] ?? blankText()), ...patch } },
});

describe('mergeOnto (started → mine laid on theirs)', () => {
  it('keeps their change to a field the user left alone', () => {
    const started = loaded();
    const mine = withText(started, 'en', { title: 'My title' });
    const theirs = { ...started, venue_name: 'Auditorium' };
    const merged = mergeOnto(started, mine, theirs);
    expect(merged.venue_name).toBe('Auditorium');
    expect(merged.texts.en?.title).toBe('My title');
  });

  it('takes the user value where both changed the same field', () => {
    const started = loaded();
    const mine = withText(started, 'en', { title: 'Mine' });
    const theirs = withText(started, 'en', { title: 'Theirs' });
    expect(mergeOnto(started, mine, theirs).texts.en?.title).toBe('Mine');
  });

  it('merges inside one language, key by key', () => {
    const started = loaded();
    const mine = withText(started, 'en', { title: 'Mine' });
    const theirs = withText(started, 'en', { summary: 'Their summary' });
    const en = mergeOnto(started, mine, theirs).texts.en;
    expect(en?.title).toBe('Mine');
    expect(en?.summary).toBe('Their summary');
  });

  it('keeps their times and recurrence when the user changed only words', () => {
    const started = loaded();
    const mine = withText(started, 'en', { title: 'Mine' });
    const theirs = { ...started, start: '2026-12-02T09:00', rrule: 'FREQ=DAILY' };
    const merged = mergeOnto(started, mine, theirs);
    expect(merged.start).toBe('2026-12-02T09:00');
    expect(merged.rrule).toBe('FREQ=DAILY');
  });

  it('keeps a language they added and one the user added', () => {
    const started = loaded();
    const mine = withText(started, 'de', { present: true, title: 'Vortrag' });
    const theirs = withText(started, 'en', { title: 'Theirs' });
    const merged = mergeOnto(started, mine, theirs);
    expect(merged.texts.de).toMatchObject({ present: true, title: 'Vortrag' });
    expect(merged.texts.en?.title).toBe('Theirs');
  });
});

describe('the patch after a merge', () => {
  it('carries only the user changes over theirs, nothing they changed', () => {
    const started = loaded();
    const mine = withText(started, 'en', { title: 'My title' });
    const theirs = withText(
      { ...started, venue_name: 'Auditorium', start: '2026-12-02T10:00', end: '2026-12-02T11:00' },
      'de',
      { present: true, title: 'Ihr Titel' },
    );
    const patch = toPatch(theirs, mergeOnto(started, mine, theirs), 5);
    expect(patch).not.toBeNull();
    expect(Object.keys(patch ?? {}).sort()).toEqual(['expected_revision', 'texts']);
    expect(Object.keys(patch?.texts ?? {})).toEqual(['en']);
    expect(patch?.texts?.en?.title).toBe('My title');
  });

  it('is empty when the user changes equal theirs', () => {
    const started = loaded();
    const mine = { ...started, venue_name: 'Auditorium' };
    const theirs = { ...started, venue_name: 'Auditorium' };
    expect(toPatch(theirs, mergeOnto(started, mine, theirs), 5)).toBeNull();
  });
});
