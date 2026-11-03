import { describe, expect, it } from 'vitest';

import { englishText } from '../../utils/i18n';
import type { ChangeClass } from '../../utils/types';
import { CHANGE_WHAT_KEYS, changeKindLabel, changeWhatLabel } from './changeLabels';

const ALL_WHATS = [
  'field_added',
  'field_removed',
  'type_changed',
  'required_added',
  'required_removed',
  'unique_added',
  'unique_removed',
  'indexed_on',
  'indexed_off',
  'constraint_tightened',
  'constraint_relaxed',
  'choice_added',
  'choice_removed',
  'options_changed',
  'label_changed',
  'display_field_changed',
] as const;

const ALL_KINDS: ChangeClass[] = ['additive', 'index_affecting', 'restrictive', 'destructive'];

describe('CHANGE_WHAT_KEYS', () => {
  it('has a catalogue key for every enumerated what', () => {
    for (const what of ALL_WHATS) {
      expect(CHANGE_WHAT_KEYS[what]).toBe(`records.type_editor.change.${what}`);
    }
  });

  it('has exactly the sixteen enumerated whats — no more, no fewer', () => {
    expect(Object.keys(CHANGE_WHAT_KEYS).sort()).toEqual([...ALL_WHATS].sort());
  });
});

describe('changeWhatLabel', () => {
  it('hands the translator the catalogue key', () => {
    const calls: unknown[][] = [];
    const t = (...args: unknown[]) => {
      calls.push(args);
      return 'translated';
    };
    expect(changeWhatLabel(t, 'field_added')).toBe('translated');
    expect(calls).toEqual([['records.type_editor.change.field_added']]);
  });

  it('resolves to the English text through the catalogue', () => {
    expect(changeWhatLabel(englishText, 'field_added')).toBe('Field added');
  });

  it('falls back to the raw what for one this build does not recognise', () => {
    expect(changeWhatLabel(englishText, 'a_future_what')).toBe('a_future_what');
  });
});

describe('changeKindLabel', () => {
  it('resolves every kind to its English text through the catalogue', () => {
    for (const kind of ALL_KINDS) {
      expect(changeKindLabel(englishText, kind)).not.toContain('records.');
    }
    expect(changeKindLabel(englishText, 'additive')).toBe('Additive');
    expect(changeKindLabel(englishText, 'index_affecting')).toBe('Rebuilds index');
    expect(changeKindLabel(englishText, 'restrictive')).toBe('Restrictive');
    expect(changeKindLabel(englishText, 'destructive')).toBe('Removes data');
  });
});
