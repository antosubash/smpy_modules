// @vitest-environment happy-dom
import * as React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import type { UsageHold } from '../utils/types';
import { UsageHolds } from './UsageHolds';

(globalThis as unknown as { React: unknown }).React = React;

function holds(count: number): UsageHold[] {
  return Array.from({ length: count }, (_, i) => ({
    id: `h${i}`,
    meter: 'demo.jobs',
    quantity: 1,
    status: 'held',
    idempotency_key: `k${i}`,
    source: 'test',
    expires_at: null,
    created_at: '2026-10-01T00:00:00Z',
    settled_at: null,
  }));
}

function render(list: UsageHold[]): string {
  return renderToStaticMarkup(
    <UsageHolds holds={list} failed={false} canManage={false} busy={false} onRelease={() => {}} />,
  );
}

describe('UsageHolds', () => {
  it('says the list is cut off when the server returned its maximum', () => {
    expect(render(holds(200))).toContain('Showing the newest 200 holds only.');
  });

  it('says nothing about a cut-off below the maximum', () => {
    expect(render(holds(3))).not.toContain('newest');
  });
});
