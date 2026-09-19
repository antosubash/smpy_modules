import { describe, expect, it } from 'vitest';

import type { ChangeClass } from '../../utils/types';
import {
  CHANGE_WHAT_DEFAULTS,
  changeKindKey,
  changeKindLabel,
  changeWhatKey,
  changeWhatLabel,
} from './changeLabels';

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
] as const;

const ALL_KINDS: ChangeClass[] = ['additive', 'index_affecting', 'restrictive', 'destructive'];

describe('changeWhatKey', () => {
  it('builds the type_editor.change.<what> family key for every known what', () => {
    for (const what of ALL_WHATS) {
      expect(changeWhatKey(what)).toBe(`records.type_editor.change.${what}`);
    }
  });

  it('builds a key even for a what this build does not recognise', () => {
    expect(changeWhatKey('something_new')).toBe('records.type_editor.change.something_new');
  });
});

describe('changeKindKey', () => {
  it('builds the type_editor.preview.kind_<kind> family key for every kind', () => {
    for (const kind of ALL_KINDS) {
      expect(changeKindKey(kind)).toBe(`records.type_editor.preview.kind_${kind}`);
    }
  });
});

describe('CHANGE_WHAT_DEFAULTS', () => {
  it('has an English default for every enumerated what', () => {
    for (const what of ALL_WHATS) {
      expect(CHANGE_WHAT_DEFAULTS[what]).toBeTruthy();
    }
  });

  it('has exactly the fifteen enumerated whats — no more, no fewer', () => {
    expect(Object.keys(CHANGE_WHAT_DEFAULTS).sort()).toEqual([...ALL_WHATS].sort());
  });
});

describe('changeWhatLabel', () => {
  it('passes the key and default through to the translator', () => {
    const calls: unknown[][] = [];
    const t = (...args: unknown[]) => {
      calls.push(args);
      return 'translated';
    };
    expect(changeWhatLabel(t, 'field_added')).toBe('translated');
    expect(calls).toEqual([
      ['records.type_editor.change.field_added', { defaultValue: 'Field added' }],
    ]);
  });

  it('falls back to the raw what for one this build does not recognise', () => {
    const t = (_key: string, opts: { defaultValue: string }) => opts.defaultValue;
    expect(changeWhatLabel(t, 'a_future_what')).toBe('a_future_what');
  });
});

describe('changeKindLabel', () => {
  it('resolves every kind to its English default via a passthrough translator', () => {
    const t = (_key: string, opts: { defaultValue: string }) => opts.defaultValue;
    expect(changeKindLabel(t, 'additive')).toBe('Additive');
    expect(changeKindLabel(t, 'index_affecting')).toBe('Rebuilds index');
    expect(changeKindLabel(t, 'restrictive')).toBe('Restrictive');
    expect(changeKindLabel(t, 'destructive')).toBe('Removes data');
  });
});
