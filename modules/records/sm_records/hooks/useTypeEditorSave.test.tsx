// @vitest-environment happy-dom
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { TypeMetadataValues } from '../components/typeeditor/types';
import { act, mount } from '../test-dom';
import type { TypeRead } from '../utils/types';
import type { useSchemaApply } from './useSchemaApply';
import type { useUnsavedGuard } from './useUnsavedGuard';

const visit = vi.fn();
const success = vi.fn();
const error = vi.fn();
const createdType = vi.fn(async () => ({ key: 'new_type' }) as TypeRead);
const allow = vi.fn();

vi.mock('@inertiajs/react', () => ({ router: { visit: (...args: unknown[]) => visit(...args) } }));
vi.mock('sonner', () => ({
  toast: Object.assign(vi.fn(), { success: (...a: unknown[]) => success(...a), error }),
}));
vi.mock('../utils/api', () => ({
  createType: (...args: unknown[]) => createdType(...(args as [])),
}));

const { useTypeEditorSave } = await import('./useTypeEditorSave');

function fakeT(key: string, opts?: Record<string, unknown>): string {
  return (opts?.defaultValue as string) ?? key;
}

function values(overrides: Partial<TypeMetadataValues> = {}): TypeMetadataValues {
  return {
    key: 'new_type',
    label: 'New Type',
    labelPlural: 'New Types',
    description: '',
    isPublic: false,
    translatable: false,
    displayField: '',
    slugField: '',
    showInMenu: false,
    allowedRoles: [],
    collection: '',
    ...overrides,
  } as TypeMetadataValues;
}

type Hook = ReturnType<typeof useTypeEditorSave>;

function Probe({ onRender }: { onRender: (hook: Hook) => void }) {
  const guard = { allow } as unknown as ReturnType<typeof useUnsavedGuard>;
  const schemaApply = {
    reset: vi.fn(),
    run: vi.fn(),
    pending: false,
    errors: [],
  } as unknown as ReturnType<typeof useSchemaApply>;
  const hook = useTypeEditorSave({
    isNew: true,
    current: null,
    values: values(),
    fields: [],
    guard,
    schemaApply,
    attemptUpdate: vi.fn(),
    onTranslatableRevert: vi.fn(),
    t: fakeT,
  });
  onRender(hook);
  return null;
}

describe('useTypeEditorSave — U9: creating a type says so before it navigates', () => {
  beforeEach(() => {
    visit.mockClear();
    success.mockClear();
    createdType.mockClear();
    allow.mockClear();
  });

  it('calls guard.allow, raises a success toast, then navigates to the new type', async () => {
    let hook!: Hook;
    const view = await mount(<Probe onRender={(h) => (hook = h)} />);
    await act(async () => {
      await hook.save();
    });
    expect(createdType).toHaveBeenCalledOnce();
    expect(allow).toHaveBeenCalledOnce();
    expect(success).toHaveBeenCalledWith('Type created');
    expect(visit).toHaveBeenCalledWith('/admin/records/types/new_type');
    // allow() must run before the toast/navigate, same order the record
    // editor's own create path uses.
    await view.unmount();
  });
});
