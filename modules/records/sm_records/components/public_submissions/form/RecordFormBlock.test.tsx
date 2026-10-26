import { describe, expect, it, vi } from 'vitest';

const types = [
  { key: 'plain', label: 'Plain', fields: [], public_submissions: null },
  {
    key: 'contact',
    label: 'Contact',
    fields: [
      { key: 'name', label: 'Name' },
      { key: 'triage', label: 'Triage' },
    ],
    public_submissions: { kind: 'form', enabled: true, public_fields: ['name'] },
  },
  {
    key: 'news',
    label: 'News',
    fields: [{ key: 'sm_email', label: 'Email' }],
    public_submissions: { kind: 'subscription', enabled: false, public_fields: [] },
  },
];

vi.mock('../../../utils/api', () => ({ listTypes: async () => ({ items: types }) }));
vi.mock('@simple-module-py/pagebuilder/pagebuilder/components/widgets/_shared', () => ({
  Section: () => null,
}));

const { RecordFormBlock } = await import('./RecordFormBlock');

type Options = { label: string; value: string }[];

describe('RecordFormBlock', () => {
  it('holds catalogue keys at module scope, for localizeConfig to resolve', () => {
    expect(RecordFormBlock.label).toBe('records.public_submissions.block.block_label');
    const fields = RecordFormBlock.fields as Record<string, { label?: string }>;
    expect(fields.typeKey.label).toBe('records.public_submissions.block.field_type_key');
  });

  it('offers only types that accept submissions, and the chosen type’s public fields', async () => {
    const resolve = RecordFormBlock.resolveFields as (data: unknown) => Promise<unknown>;
    const fields = (await resolve({ props: { typeKey: 'contact' } })) as {
      typeKey: { options: Options };
      labels: { arrayFields: { field: { options: Options } } };
    };
    expect(fields.typeKey.options.map((o) => o.value)).toEqual(['', 'contact', 'news']);
    expect(fields.typeKey.options[2].label).toContain('not accepting submissions');
    expect(fields.labels.arrayFields.field.options.map((o) => o.value)).toEqual(['', 'name']);

    const list = (await resolve({ props: { typeKey: 'news' } })) as typeof fields;
    expect(list.labels.arrayFields.field.options.map((o) => o.value)).toEqual(['', 'sm_email']);
  });

  it('records the kind as an editor-only hint', async () => {
    const resolve = RecordFormBlock.resolveData as (
      data: unknown,
      params: unknown,
    ) => Promise<{ props: { kindHint: string } }>;
    const result = await resolve(
      { props: { typeKey: 'news', kindHint: '' } },
      { changed: { typeKey: true }, trigger: 'replace' },
    );
    expect(result.props.kindHint).toBe('subscription');
  });
});
