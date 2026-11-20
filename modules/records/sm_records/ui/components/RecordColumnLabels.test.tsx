import { describe, expect, it } from 'vitest';
import { keys, translate } from '../utils/i18n';
import type { ListColumn } from '../utils/list-columns';
import type { FieldDef } from '../utils/types';
import { columnLabels } from './RecordColumnCells';

const field = (key: string, label: string, system: FieldDef['system'] = 'readonly'): FieldDef => ({
  key,
  type: 'text',
  label,
  required: false,
  unique: false,
  indexed: false,
  default: null,
  help: null,
  constraints: {},
  options: {},
  system,
});
const column = (f: FieldDef): ListColumn => ({ kind: 'field', key: f.key, field: f });
const envelope = (key: 'status'): ListColumn => ({ kind: 'envelope', key });

describe('column labels of a registration type', () => {
  const columns = [
    envelope('status'),
    column(field('sm_status', 'Status')),
    column(field('sm_event_title', 'Event title')),
    column(field('sm_occurrence_start', 'Occurrence start')),
  ];

  it('translates the system fields and keeps the field key out of the header', () => {
    const labels = columnLabels(translate, columns, 'Name');
    expect(labels.get('sm_status')).toBe('Sign-up status');
    expect(labels.get('sm_event_title')).toBe('Event');
    expect(labels.get('sm_occurrence_start')).toBe('Event date');
    for (const label of labels.values()) expect(label).not.toContain('(sm_');
  });

  it('has a German word for each, so the header is not half English', async () => {
    const de = await import('../../locales/de.json');
    const words = (de.default ?? de).public_submissions.system_labels as Record<string, string>;
    for (const key of ['sm_status', 'sm_event_title', 'sm_occurrence_start', 'sm_email']) {
      expect(words[key], key).toBeTruthy();
    }
    expect(keys.records.public_submissions.system_labels).toBeDefined();
  });

  it('leaves an operator-declared field label alone', () => {
    const labels = columnLabels(translate, [column(field('diet', 'Diet', undefined))], 'Name');
    expect(labels.get('diet')).toBe('Diet');
  });
});
