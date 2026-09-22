// @vitest-environment happy-dom
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { click, mount, setValue } from '../../test-dom';
import type { TypeRead } from '../../utils/types';

const deleteTypeMock = vi.fn(async () => undefined);

vi.mock('../../utils/api', async () => {
  const actual = await vi.importActual<typeof import('../../utils/api')>('../../utils/api');
  return {
    ...actual,
    deleteType: (...args: unknown[]) => deleteTypeMock(...(args as [])),
  };
});

const { DeleteTypeSection } = await import('./DeleteTypeSection');

function type(overrides: Partial<TypeRead> = {}): TypeRead {
  return {
    key: 'qa_ux_event',
    label: 'QA UX Event',
    label_plural: 'QA UX Events',
    description: null,
    is_public: false,
    translatable: false,
    record_count: 5,
    trashed_record_count: 2,
    version: 1,
    fields: [],
    ...overrides,
  } as TypeRead;
}

function confirmButton(): HTMLElement | null {
  return document.querySelector('[data-slot="alert-dialog-action"]');
}

function countInput(): HTMLInputElement | null {
  return document.querySelector('#type-editor-delete-confirm');
}

function hint(): HTMLElement | null {
  return document.querySelector('#type-editor-delete-confirm-hint');
}

describe('DeleteTypeSection — U2: the count guard actually disarms the button', () => {
  beforeEach(() => {
    document.body.innerHTML = '';
    deleteTypeMock.mockClear();
  });

  it('disables the confirm button and shows an inline reason for a wrong count', async () => {
    const view = await mount(<DeleteTypeSection type={type()} onDeleted={() => {}} />);
    await click(view.button('Delete this type'));
    const input = countInput();
    expect(input).not.toBeNull();
    await setValue(input as HTMLInputElement, '999');
    const btn = confirmButton();
    expect(btn?.hasAttribute('disabled')).toBe(true);
    expect(hint()?.getAttribute('role')).toBe('alert');
    expect(hint()?.textContent).toContain("doesn't match");
    await click(btn);
    expect(deleteTypeMock).not.toHaveBeenCalled();
    await view.unmount();
  });

  it('enables the confirm button once the exact total (live + trashed) is typed', async () => {
    const view = await mount(<DeleteTypeSection type={type()} onDeleted={() => {}} />);
    await click(view.button('Delete this type'));
    const input = countInput();
    await setValue(input as HTMLInputElement, '7');
    const btn = confirmButton();
    expect(btn?.hasAttribute('disabled')).toBe(false);
    expect(hint()?.getAttribute('role')).toBeNull();
    await click(btn);
    expect(deleteTypeMock).toHaveBeenCalledWith('qa_ux_event', 7);
    await view.unmount();
  });

  it('starts disabled before anything is typed', async () => {
    const view = await mount(<DeleteTypeSection type={type()} onDeleted={() => {}} />);
    await click(view.button('Delete this type'));
    expect(confirmButton()?.hasAttribute('disabled')).toBe(true);
    await view.unmount();
  });
});
