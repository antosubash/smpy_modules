// @vitest-environment happy-dom
import { act, createElement } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, describe, expect, it, vi } from 'vitest';

import en from '../../../locales/en.json';
import type { Suppression } from '../../utils/types';
import { SuppressionTable } from './SuppressionTable';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const make = (id: number, reason: Suppression['reason'], liftable: boolean): Suppression => ({
  id,
  fingerprint: `fp${id}`,
  reason,
  list_type_key: reason === 'unsubscribed' ? 'news' : '',
  source: 'send',
  created_at: '2026-11-01T10:00:00Z',
  version: `v${id}`,
  liftable,
});

describe('SuppressionTable', () => {
  let root: ReturnType<typeof createRoot>;
  afterEach(() => {
    act(() => root.unmount());
    document.body.innerHTML = '';
  });

  function render(items: Suppression[], onLift = vi.fn()) {
    root = createRoot(document.body.appendChild(document.createElement('div')));
    act(() => root.render(createElement(SuppressionTable, { items, onLift })));
    return onLift;
  }
  const lifts = () =>
    [...document.querySelectorAll('button')].filter(
      (b) => b.textContent === en.suppressions.lift.action,
    );

  it('offers no lift for a complaint and translates the reasons', () => {
    const onLift = render([
      make(1, 'complaint', false),
      make(2, 'hard_bounce', true),
      make(3, 'unsubscribed', true),
    ]);
    const text = document.body.textContent ?? '';
    expect(text).toContain(en.suppressions.reasons.complaint);
    expect(text).toContain(en.suppressions.reasons.hard_bounce);
    expect(text).toContain(en.suppressions.reasons.unsubscribed);
    expect(text).toContain(en.suppressions.all_lists);
    const buttons = lifts();
    expect(buttons).toHaveLength(2);
    act(() => buttons[0].click());
    expect(onLift).toHaveBeenCalledWith(expect.objectContaining({ id: 2 }));
  });

  it('offers no lift when the row is not liftable', () => {
    render([make(1, 'hard_bounce', false)]);
    expect(lifts()).toHaveLength(0);
  });
});
