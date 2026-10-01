// @vitest-environment happy-dom
import { describe, expect, it } from 'vitest';

import { click, mount } from '../test-dom';
import { ConfirmDialog } from './ConfirmDialog';

/** Radix renders the dialog into a portal on `document.body`. */
function confirmButton(): HTMLElement | null {
  return document.querySelector('[data-slot="alert-dialog-action"]');
}

describe('ConfirmDialog — U1: the confirm button renders the variant it is given', () => {
  it('renders the destructive variant, not the primary one, when destructive', async () => {
    const view = await mount(
      <ConfirmDialog
        trigger={<button type="button">Open</button>}
        title="Delete this thing"
        description="Are you sure?"
        confirmLabel="Delete"
        cancelLabel="Cancel"
        pendingLabel="Deleting…"
        destructive
        onConfirm={async () => undefined}
      />,
    );
    await click(view.button('Open'));
    const btn = confirmButton();
    expect(btn).not.toBeNull();
    // The button carries `data-variant` from `buttonVariants` and its class
    // list is the destructive one — not the green primary `bg-primary`.
    expect(btn?.getAttribute('data-variant')).toBe('destructive');
    expect(btn?.className).toContain('bg-destructive');
    expect(btn?.className).not.toContain('bg-primary');
    await view.unmount();
  });

  it('renders the default variant when not destructive', async () => {
    const view = await mount(
      <ConfirmDialog
        trigger={<button type="button">Open</button>}
        title="Save this thing"
        description="Proceed?"
        confirmLabel="Save"
        cancelLabel="Cancel"
        pendingLabel="Saving…"
        onConfirm={async () => undefined}
      />,
    );
    await click(view.button('Open'));
    const btn = confirmButton();
    expect(btn?.getAttribute('data-variant')).toBe('default');
    expect(btn?.className).toContain('bg-primary');
    expect(btn?.className).not.toContain('bg-destructive');
    await view.unmount();
  });
});

describe('ConfirmDialog — U8: initial focus can be redirected off Cancel', () => {
  it('focuses the named element on open when initialFocusId is given', async () => {
    const view = await mount(
      <ConfirmDialog
        trigger={<button type="button">Open</button>}
        title="Empty trash"
        description="Type the count to confirm."
        body={<input id="confirm-dialog-focus-target" data-testid="target" />}
        confirmLabel="Empty trash"
        cancelLabel="Cancel"
        pendingLabel="Emptying…"
        destructive
        initialFocusId="confirm-dialog-focus-target"
        onConfirm={async () => undefined}
      />,
    );
    await click(view.button('Open'));
    expect(document.activeElement?.getAttribute('data-testid')).toBe('target');
    await view.unmount();
  });

  it("keeps Radix's own default (Cancel) when no initialFocusId is given", async () => {
    const view = await mount(
      <ConfirmDialog
        trigger={<button type="button">Open</button>}
        title="Delete this thing"
        description="Are you sure?"
        confirmLabel="Delete"
        cancelLabel="Cancel"
        pendingLabel="Deleting…"
        destructive
        onConfirm={async () => undefined}
      />,
    );
    await click(view.button('Open'));
    expect(document.activeElement?.getAttribute('data-slot')).toBe('alert-dialog-cancel');
    await view.unmount();
  });
});

describe('ConfirmDialog — Cancel and Saving… are the defaults every caller relies on', () => {
  it('labels Cancel, and the confirm button while pending, without being told to', async () => {
    let finish: () => void = () => {};
    const view = await mount(
      <ConfirmDialog
        trigger={<button type="button">Open</button>}
        title="Restore"
        description="Restore this record?"
        confirmLabel="Restore"
        onConfirm={() =>
          new Promise<void>((resolve) => {
            finish = resolve;
          })
        }
      />,
    );
    await click(view.button('Open'));
    expect(document.querySelector('[data-slot="alert-dialog-cancel"]')?.textContent).toBe('Cancel');
    await click(confirmButton());
    expect(confirmButton()?.textContent).toBe('Saving…');
    finish();
    await view.unmount();
  });
});
