// @vitest-environment happy-dom

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { RichTextField } from '../components/editor/RichTextField';
import { act, click, mount, setValue } from './test-dom';

const exec = vi.fn(() => true);
beforeEach(() => {
  exec.mockClear();
  Object.defineProperty(document, 'execCommand', { value: exec, configurable: true });
});
afterEach(() => {
  document.body.innerHTML = '';
});

const editable = (view: { find: <T extends Element>(s: string) => T | null }) =>
  view.find<HTMLElement>('[contenteditable="true"]');
const field = (value: string, onChange = vi.fn(), extra = {}) => (
  <RichTextField id="desc" label="Description" value={value} onChange={onChange} {...extra} />
);

async function type(el: HTMLElement | null, html: string) {
  if (!el) throw new Error('no editor');
  await act(async () => {
    el.innerHTML = html;
    el.dispatchEvent(new Event('input', { bubbles: true }));
  });
}

describe('RichTextField', () => {
  it('loads server HTML', async () => {
    const view = await mount(field('<p>Hello <strong>there</strong></p>'));
    expect(editable(view)?.innerHTML).toBe('<p>Hello <strong>there</strong></p>');
    await view.render(field('<p>Changed</p>'));
    expect(editable(view)?.innerHTML).toBe('<p>Changed</p>');
    await view.unmount();
  });

  it('cleans what it loads', async () => {
    const view = await mount(field('<p onclick="x()">a</p><script>alert(1)</script>'));
    expect(editable(view)?.innerHTML).toBe('<p>a</p>');
    await view.unmount();
  });

  it('emits HTML on input', async () => {
    const onChange = vi.fn();
    const view = await mount(field('', onChange));
    await type(editable(view), '<div>Hi <b>x</b></div><img src=x onerror=alert(1)>');
    expect(onChange).toHaveBeenLastCalledWith('<p>Hi <strong>x</strong></p>');
    await type(editable(view), '<p><br></p>');
    expect(onChange).toHaveBeenLastCalledWith('');
    await view.unmount();
  });

  it('toolbar buttons call execCommand', async () => {
    const view = await mount(field(''));
    await click(view.button('Bold'));
    await click(view.button('Italic'));
    await click(view.button('Heading'));
    await click(view.button('Bulleted list'));
    await click(view.button('Numbered list'));
    expect(exec.mock.calls).toEqual([
      ['bold'],
      ['italic'],
      ['formatBlock', false, 'h2'],
      ['insertUnorderedList'],
      ['insertOrderedList'],
    ]);
    await view.unmount();
  });

  it('link button refuses javascript:', async () => {
    const view = await mount(field(''));
    await click(view.button('Link'));
    const input = view.find<HTMLInputElement>('input[type="url"]');
    if (!input) throw new Error('no link input');
    await setValue(input, 'javascript:alert(1)');
    await click(view.button('Apply link'));
    expect(view.find('[role="alert"]')?.textContent).toContain('http://');
    expect(exec).not.toHaveBeenCalledWith('createLink', false, expect.anything());
    await setValue(input, 'https://x.test/a');
    await click(view.button('Apply link'));
    expect(exec).toHaveBeenCalledWith('createLink', false, 'https://x.test/a');
    expect(view.find('input[type="url"]')).toBeNull();
    await view.unmount();
  });

  it('cleans pasted content before it is inserted', async () => {
    const view = await mount(field(''));
    const event = new Event('paste', { bubbles: true, cancelable: true });
    Object.defineProperty(event, 'clipboardData', {
      value: {
        getData: (type: string) =>
          type === 'text/html' ? '<p onclick=x>a<script>1</script></p>' : 'a',
      },
    });
    await act(async () => {
      editable(view)?.dispatchEvent(event);
    });
    expect(event.defaultPrevented).toBe(true);
    expect(exec).toHaveBeenCalledWith('insertHTML', false, '<p>a</p>');
    await view.unmount();
  });

  it('shows a read-only description in a sandboxed frame', async () => {
    const view = await mount(field('<p>Hi</p><script>1</script>', vi.fn(), { readOnly: true }));
    expect(editable(view)).toBeNull();
    const frame = view.find<HTMLIFrameElement>('iframe');
    expect(frame?.getAttribute('sandbox')).toBe('');
    expect(frame?.getAttribute('srcdoc')).toBe('<p>Hi</p>');
    expect(view.all('button')).toHaveLength(0);
    await view.unmount();
  });

  it('wires the invalid state to its message', async () => {
    const view = await mount(field('', vi.fn(), { error: 'Too long' }));
    const el = editable(view);
    expect(el?.getAttribute('aria-invalid')).toBe('true');
    expect(el?.getAttribute('aria-describedby')).toBe('desc-error');
    expect(view.find('#desc-error')?.textContent).toBe('Too long');
    await view.unmount();
  });
});
