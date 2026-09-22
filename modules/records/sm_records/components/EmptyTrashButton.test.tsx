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

/** Every case passes the type key: the capped guard asks for it, and the
 *  uncapped one still asks for the count. */
function trashButton(props: Partial<Parameters<typeof EmptyTrashButton>[0]> = {}) {
  return (
    <EmptyTrashButton
      count={12}
      typeKey="product"
      filtered={false}
      onEmpty={vi.fn(async () => undefined)}
      {...props}
    />
  );
}

describe('EmptyTrashButton — unbounded and irreversible, so it is typed', () => {
  beforeEach(() => {
    document.body.innerHTML = '';
  });

  it('is not offered on an empty trash', async () => {
    const view = await mount(trashButton({ count: 0 }));
    expect(view.find('[data-testid="records-empty-trash"]')).toBeNull();
  });

  it('keeps the confirm disabled until the exact count is typed', async () => {
    const onEmpty = vi.fn(async () => undefined);
    const view = await mount(trashButton({ onEmpty }));
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
    const view = await mount(trashButton({ count: 2, filtered: true, onEmpty }));
    await click(view.find('[data-testid="records-empty-trash"]'));
    await setValue(countInput() as HTMLInputElement, '2');
    await click(confirmButton());
    expect(onEmpty).toHaveBeenCalledWith(true);
  });

  it('asks for the type key instead of a number when the count is capped', async () => {
    // A capped total is a floor, not a total: asking for it would teach
    // people to type whatever the dialog shows, and dropping the guard would
    // leave the largest, least reversible case the only one a single
    // mis-click can reach.
    const onEmpty = vi.fn(async () => undefined);
    const view = await mount(trashButton({ count: 10000, capped: true, onEmpty }));
    await click(view.find('[data-testid="records-empty-trash"]'));

    const input = countInput();
    expect(input).not.toBeNull();
    expect(confirmButton()?.disabled).toBe(true);

    // The count is exactly what it must *not* accept here.
    await setValue(input as HTMLInputElement, '10000');
    expect(confirmButton()?.disabled).toBe(true);

    await setValue(input as HTMLInputElement, 'produc');
    expect(confirmButton()?.disabled).toBe(true);

    await setValue(input as HTMLInputElement, 'product');
    expect(confirmButton()?.disabled).toBe(false);

    await click(confirmButton());
    expect(onEmpty).toHaveBeenCalledWith(false);
  });

  it('keeps asking for the count when it is not capped', async () => {
    const view = await mount(trashButton());
    await click(view.find('[data-testid="records-empty-trash"]'));

    // The type key is not the answer here — the number is.
    await setValue(countInput() as HTMLInputElement, 'product');
    expect(confirmButton()?.disabled).toBe(true);

    await setValue(countInput() as HTMLInputElement, '12');
    expect(confirmButton()?.disabled).toBe(false);
  });

  it('U8: focuses the confirmation input on open, not Cancel', async () => {
    const view = await mount(trashButton());
    await click(view.find('[data-testid="records-empty-trash"]'));
    expect(document.activeElement?.id).toBe('records-empty-trash-confirm');
  });

  it('U16: never renders the confirm trigger disabled — the empty-trash case returns null instead', async () => {
    const view = await mount(trashButton());
    const trigger = view.find<HTMLButtonElement>('[data-testid="records-empty-trash"]');
    expect(trigger?.disabled).toBe(false);
  });

  it('forgets a half-typed count when the dialog is closed', async () => {
    const view = await mount(trashButton());
    await click(view.find('[data-testid="records-empty-trash"]'));
    await setValue(countInput() as HTMLInputElement, '12');

    await click(document.querySelector('[data-slot="alert-dialog-cancel"]'));
    await click(view.find('[data-testid="records-empty-trash"]'));

    expect(countInput()?.value).toBe('');
    expect(confirmButton()?.disabled).toBe(true);
  });
});
