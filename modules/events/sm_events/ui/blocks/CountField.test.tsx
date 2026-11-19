// @vitest-environment happy-dom
import type { ReactElement } from 'react';
import { afterEach, expect, it, vi } from 'vitest';
import { mount, setValue } from '../page-tests/test-dom';
import { countField } from './CountField';

vi.mock('@puckeditor/core', () => ({
  FieldLabel: ({ label, children }: { label: string; children: React.ReactNode }) => (
    <div>
      <span>{label}</span>
      {children}
    </div>
  ),
}));

afterEach(() => {
  document.body.innerHTML = '';
});

const field = countField('Number of events');
const render = (value: unknown, onChange = vi.fn()) =>
  mount(
    (field as unknown as { render: (p: unknown) => ReactElement }).render({
      value,
      onChange,
      name: 'count',
      id: 'count',
      field,
    }),
  );
const message = () => document.querySelector('[data-count-error]')?.textContent ?? '';

it('accepts a whole number in range without a message', async () => {
  const view = await render(5);
  expect(message()).toBe('');
  expect((document.querySelector('input') as HTMLInputElement).step).toBe('1');
  await view.unmount();
});

it.each([0, -3, 99])('says why %s is refused, in words', async (value) => {
  const view = await render(value);
  expect(message()).toContain('whole number from 1 to 20');
  expect(document.querySelector('input')?.getAttribute('aria-invalid')).toBe('true');
  await view.unmount();
});

it('says a fraction is not a whole number, and does not round it', async () => {
  const onChange = vi.fn();
  const view = await render(2.7, onChange);
  expect(message()).toContain('whole number');
  await setValue(document.querySelector('input') as HTMLInputElement, '3.5');
  expect(onChange).toHaveBeenLastCalledWith(3.5); // handed on as typed: nothing is clamped silently
  await view.unmount();
});
