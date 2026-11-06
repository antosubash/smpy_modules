// @vitest-environment happy-dom
import { act, createElement } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, describe, expect, it } from 'vitest';

import en from '../../../locales/en.json';
import { LinkTable } from './LinkTable';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let root: ReturnType<typeof createRoot>;
async function render(props: Parameters<typeof LinkTable>[0]) {
  root = createRoot(document.body.appendChild(document.createElement('div')));
  await act(async () => root.render(createElement(LinkTable, props)));
}
afterEach(() => {
  act(() => root.unmount());
  document.body.innerHTML = '';
});

const links = [
  { position: 1, url: 'https://example.com/a', unique: 5, total: 8 },
  { position: 2, url: 'https://example.com/b', unique: 2, total: 2 },
];

describe('LinkTable', () => {
  it('lists the rows in the given order', async () => {
    await render({ links, trackingOff: false });
    const rows = [...document.querySelectorAll('tbody tr')].map((r) =>
      [...r.querySelectorAll('td')].map((c) => c.textContent),
    );
    expect(rows).toEqual([
      ['1', 'https://example.com/a', '5', '8'],
      ['2', 'https://example.com/b', '2', '2'],
    ]);
  });

  it('renders a URL as text, never a link, with the full URL as title', async () => {
    await render({ links, trackingOff: false });
    expect(document.querySelector('a')).toBeNull();
    expect(document.querySelector('[title="https://example.com/a"]')).not.toBeNull();
  });

  it('shows the empty state', async () => {
    await render({ links: [], trackingOff: false });
    expect(document.body.textContent).toContain(en.report.links.empty);
    expect(document.querySelector('table')).toBeNull();
  });

  it('shows the click-tracking note with the empty state when tracking is off', async () => {
    await render({ links: [], trackingOff: true });
    expect(document.body.textContent).toContain(en.report.tracking_off.clicks);
  });
});
