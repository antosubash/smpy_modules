// @vitest-environment happy-dom

import { updateI18n } from '@simple-module-py/i18n';
import * as React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { afterEach, describe, expect, it } from 'vitest';
import type { SyncHealth } from '../utils/types';
import { SyncHealthBar } from './SyncHealthBar';

(globalThis as unknown as { React: unknown }).React = React;

const healthy: SyncHealth = {
  oldest_synced_at: '2026-01-02T03:04:05Z',
  never_synced: 0,
  unprocessed_webhooks: 0,
  reconcile_interval_minutes: 60,
  reconcile_running: true,
};

const render = (health: SyncHealth) => renderToStaticMarkup(<SyncHealthBar health={health} />);

describe('SyncHealthBar', () => {
  afterEach(() => updateI18n({ locale: 'en', messages: {} }));

  it('formats the oldest sync in the console locale (#189)', () => {
    expect(render({ ...healthy, oldest_synced_at: '2026-01-02T12:00:00Z' })).toContain(
      'Jan 2, 2026',
    );
    updateI18n({ locale: 'de', messages: {} });
    expect(render({ ...healthy, oldest_synced_at: '2026-01-02T12:00:00Z' })).toContain(
      '02.01.2026',
    );
  });

  it('shows no markdown backticks', () => {
    const html = render({ ...healthy, reconcile_interval_minutes: 0, reconcile_running: false });
    expect(html).not.toContain('`');
  });

  it('shows the oldest sync and the reconcile interval', () => {
    const html = render(healthy);
    expect(html).toContain('Oldest sync:');
    expect(html).toContain('every 60 min');
    expect(html).toContain('Unprocessed webhooks: 0');
  });

  it('says when the scheduled reconcile is off', () => {
    const html = render({ ...healthy, reconcile_interval_minutes: 0, reconcile_running: false });
    expect(html).toContain('Scheduled reconcile: off');
  });

  it('flags unprocessed webhooks and never-synced subscriptions', () => {
    const html = render({ ...healthy, unprocessed_webhooks: 3, never_synced: 2 });
    expect(html).toContain('Unprocessed webhooks: 3');
    expect(html).toContain('2 never synced');
  });

  it('says a configured loop is not running', () => {
    expect(render({ ...healthy, reconcile_running: false })).toContain('restart the app');
  });
});
