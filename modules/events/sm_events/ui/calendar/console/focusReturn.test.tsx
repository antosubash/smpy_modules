// @vitest-environment happy-dom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { mount } from '../../page-tests/test-dom';
import type { Occurrence } from '../types';
import { useFocusReturn } from './focusReturn';

const o = { key: 'e1:0' } as Occurrence;
let restore: ReturnType<typeof useFocusReturn> | null = null;
const focusRef = { current: null as ((key: string) => boolean) | null };
function Probe() {
  restore = useFocusReturn(focusRef);
  return null;
}

beforeEach(() => {
  vi.useFakeTimers();
  document.body.innerHTML = '<h2 data-testid="calendar-title" tabindex="-1"></h2>';
});
afterEach(() => {
  vi.useRealTimers();
  document.body.innerHTML = '';
});

describe('the Move dialog focus return', () => {
  it('stops retrying once the rebuilt chip has focus', async () => {
    const view = await mount(<Probe />);
    const chip = vi.fn(() => true);
    focusRef.current = chip;
    restore?.(o, null);
    expect(chip).toHaveBeenCalledTimes(1); // placed at once
    (document.activeElement as HTMLElement | null)?.blur();
    vi.advanceTimersByTime(300);
    expect(chip).toHaveBeenCalledTimes(2); // the rebuild dropped it: once more, then done
    vi.advanceTimersByTime(2000);
    expect(chip).toHaveBeenCalledTimes(2);
    await view.unmount();
  });

  it('never takes focus after the user pressed or typed', async () => {
    const view = await mount(<Probe />);
    const chip = vi.fn(() => false);
    focusRef.current = chip;
    restore?.(o, null);
    chip.mockClear();
    document.dispatchEvent(new Event('pointerdown'));
    vi.advanceTimersByTime(2000);
    expect(chip).not.toHaveBeenCalled();
    expect(vi.getTimerCount()).toBe(0);
    await view.unmount();
  });

  it('clears its timer on unmount', async () => {
    const view = await mount(<Probe />);
    focusRef.current = () => false;
    restore?.(o, null);
    expect(vi.getTimerCount()).toBe(1);
    await view.unmount();
    expect(vi.getTimerCount()).toBe(0);
  });

  it('falls back to the title when the chip never comes back', async () => {
    const view = await mount(<Probe />);
    focusRef.current = () => false;
    restore?.(o, null);
    (document.activeElement as HTMLElement | null)?.blur();
    vi.advanceTimersByTime(700);
    expect(document.activeElement?.getAttribute('data-testid')).toBe('calendar-title');
    expect(vi.getTimerCount()).toBe(0);
    await view.unmount();
  });
});
