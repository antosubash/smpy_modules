// @vitest-environment happy-dom
import { describe, expect, it, vi } from 'vitest';

import { act, click, mount, press } from '../../test-dom';
import { Lightbox } from './Lightbox';

function Page({ onClose }: { onClose: () => void }) {
  return (
    <div>
      <button type="button" data-testid="opener">
        open
      </button>
      <Lightbox src="/x.jpg" alt="x" onClose={onClose} />
    </div>
  );
}

describe('Lightbox', () => {
  it('does not take focus back when the parent re-renders with a new onClose', async () => {
    const view = await mount(<Page onClose={() => {}} />);
    const outside = document.createElement('input');
    document.body.appendChild(outside);
    outside.focus();
    await view.render(<Page onClose={() => {}} />);
    expect(document.activeElement).toBe(outside);
    outside.remove();
    await view.unmount();
  });

  it('closes on Escape through the latest onClose', async () => {
    const first = vi.fn();
    const second = vi.fn();
    const view = await mount(<Page onClose={first} />);
    await view.render(<Page onClose={second} />);
    await press(window, { key: 'Escape' });
    expect(first).not.toHaveBeenCalled();
    expect(second).toHaveBeenCalledTimes(1);
    await view.unmount();
  });

  it('closes on a click outside the picture, not on the picture', async () => {
    const onClose = vi.fn();
    const view = await mount(<Lightbox src="/x.jpg" alt="x" onClose={onClose} />);
    await click(view.find('[data-testid="images-lightbox-image"]'));
    expect(onClose).not.toHaveBeenCalled();
    await click(view.find('[data-testid="images-lightbox"]'));
    expect(onClose).toHaveBeenCalledTimes(1);
    await view.unmount();
  });

  it('keeps Tab inside the dialog', async () => {
    const view = await mount(<Page onClose={() => {}} />);
    const close = view.find('[data-testid="images-lightbox"] button') as HTMLElement;
    expect(document.activeElement).toBe(close);
    const tab = new KeyboardEvent('keydown', { key: 'Tab', bubbles: true, cancelable: true });
    await act(async () => {
      close.dispatchEvent(tab);
    });
    expect(tab.defaultPrevented).toBe(true);
    expect(document.activeElement).toBe(close);
    await view.unmount();
  });

  it('gives focus back to what opened it', async () => {
    const opener = document.createElement('button');
    document.body.appendChild(opener);
    opener.focus();
    const view = await mount(<Lightbox src="/x.jpg" alt="x" onClose={() => {}} />);
    expect(document.activeElement).not.toBe(opener);
    await view.unmount();
    expect(document.activeElement).toBe(opener);
    opener.remove();
  });
});
