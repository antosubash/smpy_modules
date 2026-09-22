// @vitest-environment happy-dom
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { click, mount, setValue } from '../test-dom';

const { EmptyTrashButton } = await import('./EmptyTrashButton');

function confirmButton(): HTMLButtonElement | null {
  return document.querySelector('[data-slot="alert-dialog-action"]');
}

function countInput(): HTMLInputElement | null {
  return document.querySelector('#records-empty-trash-confirm');
}

describe('EmptyTrashButton — unbounded and irreversible, so it is typed', () => {
  beforeEach(() => {
    document.body.innerHTML = '';
  });

  it('is not offered on an empty trash', async () => {
    const view = await mount(<EmptyTrashButton count={0} filtered={false} onEmpty={vi.fn()} />);
    expect(view.find('[data-testid="records-empty-trash"]')).toBeNull();
  });

  it('keeps the confirm disabled until the exact count is typed', async () => {
    const onEmpty = vi.fn(async () => undefined);
    const view = await mount(<EmptyTrashButton count={12} filtered={false} onEmpty={onEmpty} />);
    await click(view.find('[data-testid="records-empty-trash"]'));

    expect(confirmButton()?.disabled).toBe(true);

    const input = countInput();
    expect(input).not.toBeNull();
    await setValue(input as HTMLInputElement, '11');
    expect(confirmButton()?.disabled).toBe(true);

    await setValue(input as HTMLInputElement, '12');
    expect(confirmButton()?.disabled).toBe(false);

    await click(confirmButton());
    // `filtered` travels with the call: the server empties the same part of
    // the trash the copy just promised.
    expect(onEmpty).toHaveBeenCalledWith(false);
  });

  it('passes the filter through when one is in force', async () => {
    const onEmpty = vi.fn(async () => undefined);
    const view = await mount(<EmptyTrashButton count={2} filtered onEmpty={onEmpty} />);
    await click(view.find('[data-testid="records-empty-trash"]'));
    await setValue(countInput() as HTMLInputElement, '2');
    await click(confirmButton());
    expect(onEmpty).toHaveBeenCalledWith(true);
  });

  it('asks for no number when the count is capped, since there is none to ask for', async () => {
    const view = await mount(
      <EmptyTrashButton count={10000} filtered={false} capped onEmpty={vi.fn()} />,
    );
    await click(view.find('[data-testid="records-empty-trash"]'));
    expect(countInput()).toBeNull();
    expect(confirmButton()?.disabled).toBe(false);
  });

  it('forgets a half-typed count when the dialog is closed', async () => {
    const view = await mount(<EmptyTrashButton count={12} filtered={false} onEmpty={vi.fn()} />);
    await click(view.find('[data-testid="records-empty-trash"]'));
    await setValue(countInput() as HTMLInputElement, '12');

    await click(document.querySelector('[data-slot="alert-dialog-cancel"]'));
    await click(view.find('[data-testid="records-empty-trash"]'));

    expect(countInput()?.value).toBe('');
    expect(confirmButton()?.disabled).toBe(true);
  });
});
