// @vitest-environment happy-dom

import { afterEach, describe, expect, it } from 'vitest';
import { mount } from '../page-tests/test-dom';
import { RichText } from './RichText';
import type { Node } from './richtext-types';

afterEach(() => {
  document.body.innerHTML = '';
});

const html = async (nodes: Node[]) => (await mount(<RichText nodes={nodes} />)).host.innerHTML;

describe('RichText', () => {
  it('styles lists, which the host stylesheet resets, so bullets and numbers show', async () => {
    const view = await mount(<RichText nodes={[{ t: 'ul', c: [{ t: 'li', c: ['x'] }] }]} />);
    const classes = view.find('div')?.className ?? '';
    for (const wanted of [
      '[&_ul]:list-disc',
      '[&_ol]:list-decimal',
      '[&_ul]:pl-6',
      '[&_ol]:pl-6',
    ]) {
      expect(classes).toContain(wanted);
    }
  });

  it('renders allowed tags', async () => {
    const out = await html([
      { t: 'h2', c: ['Title'] },
      { t: 'p', c: ['a ', { t: 'strong', c: ['b'] }, { t: 'br', c: [] }, 'c'] },
      { t: 'ul', c: [{ t: 'li', c: ['x'] }] },
    ]);
    expect(out).toContain('<h2>Title</h2>');
    expect(out).toContain('<strong>b</strong><br>');
    expect(out).toContain('<ul><li>x</li></ul>');
  });

  it('drops unknown tags to children', async () => {
    const out = await html([{ t: 'p', c: [{ t: 'marquee', c: ['still here'] }] }]);
    expect(out).toContain('still here');
    expect(out).not.toContain('marquee');
  });

  it('never renders a script element', async () => {
    const host = (
      await mount(<RichText nodes={[{ t: 'script', c: ['alert(1)'] }, '<script>x</script>']} />)
    ).host;
    expect(host.querySelector('script')).toBeNull();
    expect(host.textContent).toContain('<script>x</script>'); // text, not an element
  });

  it('refuses javascript: href and keeps safe links', async () => {
    const out = await html([
      { t: 'p', c: [{ t: 'a', href: 'javascript:alert(1)', c: ['bad'] }] },
      { t: 'p', c: [{ t: 'a', href: 'https://example.org/x', c: ['good'] }] },
      { t: 'p', c: [{ t: 'a', href: 'data:text/html,x', c: ['data'] }] },
    ]);
    expect(out).not.toContain('javascript:');
    expect(out).not.toContain('data:');
    expect(out).toContain('<a href="https://example.org/x" rel="nofollow noopener">good</a>');
    expect(out).toContain('bad');
  });

  it('uses no dangerouslySetInnerHTML outside PublicHead', () => {
    const sources = import.meta.glob(['./*.tsx', '../../pages/Public*.tsx', '!./*.test.tsx'], {
      query: '?raw',
      import: 'default',
      eager: true,
    }) as Record<string, string>;
    const files = Object.keys(sources);
    const offenders = files
      .filter((file) => sources[file]?.includes('dangerouslySetInnerHTML'))
      .map((file) => file.split('/').pop());
    expect(files.length).toBeGreaterThan(8);
    expect(offenders).toEqual(['PublicHead.tsx']);
  });
});
