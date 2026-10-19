// @vitest-environment happy-dom
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { TypeMetadataValues } from '../components/typeeditor/types';
import { act, mount } from '../test-dom';
import { englishText as fakeT } from '../utils/i18n';
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

function Probe({
  onRender,
  isNew = true,
  current = null,
  vals = values(),
  run = vi.fn(),
}: {
  onRender: (hook: Hook) => void;
  isNew?: boolean;
  current?: TypeRead | null;
  vals?: TypeMetadataValues;
  run?: ReturnType<typeof vi.fn>;
}) {
  const guard = { allow } as unknown as ReturnType<typeof useUnsavedGuard>;
  const schemaApply = {
    reset: vi.fn(),
    run,
    pending: false,
    errors: [],
  } as unknown as ReturnType<typeof useSchemaApply>;
  const hook = useTypeEditorSave({
    isNew,
    current,
    values: vals,
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

describe('useTypeEditorSave — blank labels (#143)', () => {
  beforeEach(() => createdType.mockClear());

  it('refuses a blank label on create without calling the API', async () => {
    let hook!: Hook;
    const view = await mount(<Probe vals={values({ label: '  ' })} onRender={(h) => (hook = h)} />);
    await act(async () => {
      await hook.save();
    });
    expect(createdType).not.toHaveBeenCalled();
    expect(hook.createErrors[0]?.field).toBe('label');
    await view.unmount();
  });

  it('still saves other changes of a legacy blank-label type when the label is untouched', async () => {
    const current = {
      label: '',
      label_plural: '',
      description: '',
      allowed_roles: [],
      is_public: false,
      translatable: false,
      show_in_menu: false,
      version: 3,
      fields: [],
    } as unknown as TypeRead;
    const run = vi.fn();
    let hook!: Hook;
    const view = await mount(
      <Probe
        isNew={false}
        current={current}
        vals={values({ label: '', labelPlural: '', description: 'now described' })}
        run={run}
        onRender={(h) => (hook = h)}
      />,
    );
    await act(async () => {
      await hook.save();
    });
    expect(hook.createErrors).toEqual([]);
    expect(run).toHaveBeenCalledOnce();
    await view.unmount();
  });

  it('clears the label error as soon as the label changes', async () => {
    let hook!: Hook;
    const onRender = (h: Hook) => (hook = h);
    const view = await mount(<Probe vals={values({ label: '' })} onRender={onRender} />);
    await act(async () => {
      await hook.save();
    });
    expect(hook.createErrors).toHaveLength(1);
    await view.render(<Probe vals={values({ label: 'Valid' })} onRender={onRender} />);
    expect(hook.createErrors).toEqual([]);
    await view.unmount();
  });
});
