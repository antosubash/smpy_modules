// @vitest-environment happy-dom
import { describe, expect, it } from 'vitest';

import { act, mount } from '../test-dom';
import type { FieldDef, RecordRead, TypeRead } from '../utils/types';
import { useRecordForm } from './useRecordForm';

function field(key: string, extra: Partial<FieldDef> = {}): FieldDef {
  return {
    key,
    type: 'text',
    label: key,
    required: false,
    unique: false,
    indexed: false,
    default: null,
    help: null,
    constraints: {},
    options: {},
    ...extra,
  };
}

const type = {
  key: 'contact',
  label: 'Contact',
  label_plural: 'Contacts',
  fields: [
    field('name'),
    field('sm_submitted_at', { type: 'datetime', system: 'readonly' }),
    field('sm_nonce', { system: 'internal' }),
  ],
  version: 1,
  reindex_pending: {},
} as unknown as TypeRead;

function record(name: string, version = 1): RecordRead {
  return {
    uuid: 'r1',
    version,
    status: 'draft',
    slug: null,
    position: 0,
    invalid: [],
    data: { name, sm_submitted_at: '2026-10-01T10:00:00Z', sm_nonce: 'secret-nonce' },
  } as unknown as RecordRead;
}

type Form = ReturnType<typeof useRecordForm>;

function Probe({ onRender }: { onRender: (form: Form) => void }) {
  onRender(useRecordForm(type, record('Ada')));
  return null;
}

async function mountForm() {
  let latest: Form | null = null;
  await mount(
    <Probe
      onRender={(form) => {
        latest = form;
      }}
    />,
  );
  return () => latest as unknown as Form;
}

describe('useRecordForm raw editor and system fields (#101)', () => {
  it('a reset in raw mode never puts an internal value in the raw text', async () => {
    const form = await mountForm();
    await act(async () => form().toggleRaw());
    expect(form().raw).toBe(true);
    // A save in raw mode and a revision restore both land here.
    await act(async () => form().reset(record('Grace', 2)));
    const text = form().rawText;
    expect(text).not.toContain('sm_nonce');
    expect(text).not.toContain('secret-nonce');
    expect(JSON.parse(text)).toMatchObject({ name: 'Grace' });
    // Showing the stored readonly values is not an edit.
    expect(form().dirty).toBe(false);
  });

  it('saving from raw mode sends no system values back', async () => {
    const form = await mountForm();
    await act(async () => form().toggleRaw());
    await act(async () =>
      form().setRawText(
        JSON.stringify({ name: 'Ada', sm_nonce: 'typed', sm_submitted_at: 'typed' }),
      ),
    );
    let payload: Record<string, unknown> | null = null;
    await act(async () => {
      payload = form().validateAndBuild();
    });
    expect(payload).toEqual({ name: 'Ada' });
  });
});
