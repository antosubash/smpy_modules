// @vitest-environment happy-dom
import * as React from 'react';
import { describe, expect, it, vi } from 'vitest';

import type { TypeRead } from '../../utils/types';

vi.mock('@inertiajs/react', () => ({
  usePage: () => ({ props: { locale: 'de' }, url: '/p' }),
}));

const field = (key: string, type: string, indexed: boolean) => ({
  key,
  type,
  label: key.toUpperCase(),
  indexed,
});
vi.mock('../../utils/api', () => ({
  listTypes: async () => ({
    items: [
      {
        key: 'donation',
        label: 'Donation',
        is_public: true,
        fields: [
          field('amount', 'number', true),
          field('legacy', 'number', false),
          field('count', 'integer', true),
          field('note', 'text', true),
        ],
      } as unknown as TypeRead,
      {
        key: 'other',
        label: 'Other',
        is_public: true,
        fields: [field('weight', 'number', true)],
      } as unknown as TypeRead,
      {
        key: 'draft',
        label: 'Draft',
        is_public: false,
        fields: [],
      } as unknown as TypeRead,
    ],
  }),
}));

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
(globalThis as { React?: unknown }).React = React;

const { RecordStatsBlock, clampStatItems } = await import('./RecordStatsBlock');
type Item = import('./RecordStatsBlock').RecordStatItem;

const item = (over: Partial<Item> = {}): Item => ({
  typeKey: 'donation',
  metric: 'count',
  field: '',
  filter: '',
  label: 'Donations',
  prefix: '',
  suffix: '',
  ...over,
});

type ResolveData = (
  data: { props: Record<string, unknown> },
  params: { trigger: string },
) => Promise<{ props: Record<string, unknown> }> | { props: Record<string, unknown> };

async function resolve(trigger: string, items: unknown[]): Promise<unknown[]> {
  const resolveData = RecordStatsBlock.resolveData as unknown as ResolveData;
  const out = await resolveData({ props: { items } }, { trigger });
  return out.props.items as unknown[];
}

describe('RecordStatsBlock.resolveData', () => {
  it('clamps to six and drops an unknown metric on load', async () => {
    expect(
      await resolve(
        'load',
        Array.from({ length: 8 }, () => item()),
      ),
    ).toHaveLength(6);
    const kept = await resolve('load', [item(), { ...item(), metric: 'max' }]);
    expect(kept).toHaveLength(1);
  });

  it('leaves the items alone while the author edits them', async () => {
    expect(
      await resolve(
        'replace',
        Array.from({ length: 8 }, () => item()),
      ),
    ).toHaveLength(8);
  });
});

describe('clampStatItems', () => {
  it('survives a stored value that is not a list', () => {
    expect(clampStatItems(undefined)).toEqual([]);
    expect(clampStatItems([item(), null as unknown as Item])).toHaveLength(1);
  });
});

describe('field options', () => {
  it('lists only the chosen types indexed number fields', async () => {
    const resolveFields = RecordStatsBlock.resolveFields as unknown as (data: {
      props: Record<string, unknown>;
    }) => Promise<{
      items: {
        arrayFields: {
          field: { options: { value: string }[] };
          typeKey: { options: { value: string }[] };
        };
      };
    }>;
    const out = await resolveFields({ props: { items: [item({ typeKey: 'donation' })] } });
    const values = out.items.arrayFields.field.options.map((o) => o.value);
    expect(values).toContain('amount');
    expect(values).toContain('count');
    expect(values).not.toContain('legacy');
    expect(values).not.toContain('note');
    expect(values).not.toContain('weight');
    const types = out.items.arrayFields.typeKey.options.map((o) => o.value);
    expect(types).toEqual(expect.arrayContaining(['donation', 'other']));
  });

  it('marks a type that is not public in the picker, like the list block', async () => {
    const resolveFields = RecordStatsBlock.resolveFields as unknown as (data: {
      props: Record<string, unknown>;
    }) => Promise<{
      items: { arrayFields: { typeKey: { options: { label: string; value: string }[] } } };
    }>;
    const out = await resolveFields({ props: { items: [] } });
    const labels = Object.fromEntries(
      out.items.arrayFields.typeKey.options.map((o) => [o.value, o.label]),
    );
    expect(labels.donation).toBe('Donation');
    expect(labels.draft).toBe('Draft (not public)');
  });
});
