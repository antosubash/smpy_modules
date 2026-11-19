import { describe, expect, it } from 'vitest';

import { localizeFields } from './localizeFields';

const tr = (key: string) => `T(${key})`;

const fields = {
  heading: { type: 'text', label: 'events.blocks.upcoming.heading' },
  layout: {
    type: 'select',
    label: 'events.blocks.upcoming.layout',
    options: [
      { label: 'events.blocks.upcoming.layout_list', value: 'list' },
      { label: 'events.blocks.upcoming.layout_cards', value: 'cards' },
    ],
  },
  calendars: {
    type: 'array',
    label: 'events.blocks.upcoming.calendars',
    arrayFields: {
      slug: {
        type: 'select',
        label: 'events.blocks.fields.calendar',
        options: [{ label: 'A calendar name', value: 'a' }],
      },
      nested: {
        type: 'object',
        label: 'events.blocks.fields.group',
        objectFields: {
          inner: { type: 'text', label: 'events.blocks.fields.inner' },
        },
      },
    },
  },
};

describe('localizeFields', () => {
  it('translates labels, option labels and nested array and object field labels', () => {
    const out = localizeFields(fields, tr) as typeof fields;
    expect(out.heading.label).toBe('T(events.blocks.upcoming.heading)');
    expect(out.layout.options.map((o) => o.label)).toEqual([
      'T(events.blocks.upcoming.layout_list)',
      'T(events.blocks.upcoming.layout_cards)',
    ]);
    expect(out.calendars.label).toBe('T(events.blocks.upcoming.calendars)');
    expect(out.calendars.arrayFields.slug.label).toBe('T(events.blocks.fields.calendar)');
    expect(out.calendars.arrayFields.nested.objectFields.inner.label).toBe(
      'T(events.blocks.fields.inner)',
    );
  });

  it('leaves values and non-label strings alone', () => {
    const out = localizeFields(fields, tr) as typeof fields;
    expect(out.layout.options.map((o) => o.value)).toEqual(['list', 'cards']);
    expect(out.heading.type).toBe('text');
    expect(out.calendars.arrayFields.slug.type).toBe('select');
  });

  it('does not mutate its input', () => {
    const before = JSON.stringify(fields);
    localizeFields(fields, tr);
    expect(JSON.stringify(fields)).toBe(before);
  });

  it('leaves an option label that is already a name (a calendar) as text', () => {
    // A resolved select's labels are the visitor-visible names, not keys: they pass through
    // `tr`, which returns an unknown key as it came.
    const echo = (key: string) => key;
    const out = localizeFields(fields, echo) as typeof fields;
    expect(out.calendars.arrayFields.slug.options[0].label).toBe('A calendar name');
  });
});
