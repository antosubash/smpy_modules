// @vitest-environment happy-dom
import { router } from '@inertiajs/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { collection, image } from './support';
import { click, mount, press } from './test-dom';

vi.mock('@inertiajs/react', async () => (await import('./support')).inertiaMock());

const Image = (await import('../../pages/Image')).default;

const props = {
  collection: collection(),
  can_edit: true,
  can_manage: true,
  can_view_original: false,
};

afterEach(() => vi.mocked(router.visit).mockClear());

describe('viewer previous / next (QA TEST-006h)', () => {
  it('moves to the neighbouring images by button and by arrow key', async () => {
    const view = await mount(
      <Image image={image('i2')} neighbors={{ prev: 'i1', next: 'i3' }} {...props} />,
    );
    await click(view.find('[data-testid="images-viewer-next"]'));
    expect(router.visit).toHaveBeenLastCalledWith('/admin/images/images/i3');
    await press(window, { key: 'ArrowLeft' });
    expect(router.visit).toHaveBeenLastCalledWith('/admin/images/images/i1');
    await press(window, { key: 'ArrowRight' });
    expect(router.visit).toHaveBeenLastCalledWith('/admin/images/images/i3');
    await view.unmount();
  });

  it('offers no step past either end, and leaves arrows in a field alone', async () => {
    const view = await mount(
      <Image image={image('i1')} neighbors={{ prev: null, next: 'i2' }} {...props} />,
    );
    expect(
      (view.find('[data-testid="images-viewer-prev"]') as HTMLButtonElement | null)?.disabled,
    ).toBe(true);
    await press(window, { key: 'ArrowLeft' });
    const field = document.createElement('input');
    view.host.append(field);
    await press(field, { key: 'ArrowRight' });
    expect(router.visit).not.toHaveBeenCalled();
    await view.unmount();
  });

  it('leaves the arrows to an open dialog (QA R3-ARROW-DIALOG)', async () => {
    const view = await mount(
      <Image image={image('i2')} neighbors={{ prev: 'i1', next: 'i3' }} {...props} />,
    );
    const dialog = document.createElement('div');
    dialog.setAttribute('role', 'alertdialog');
    const button = document.createElement('button');
    dialog.append(button);
    document.body.append(dialog);
    await press(button, { key: 'ArrowRight' }); // focus inside the dialog
    await press(window, { key: 'ArrowLeft' }); // focus elsewhere, dialog still open
    expect(router.visit).not.toHaveBeenCalled();
    dialog.remove();
    await press(window, { key: 'ArrowRight' });
    expect(router.visit).toHaveBeenLastCalledWith('/admin/images/images/i3');
    await view.unmount();
  });
});
