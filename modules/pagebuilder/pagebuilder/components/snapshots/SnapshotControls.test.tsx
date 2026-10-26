// @vitest-environment happy-dom
import * as React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';

import type { PendingImport, Snapshot, SnapshotCapabilities } from '../../utils/snapshotsApi';
import { SnapshotList } from './SnapshotList';

(globalThis as unknown as { React: unknown }).React = React;

const page = vi.hoisted(() => ({ props: {} as Record<string, unknown> }));
vi.mock('@inertiajs/react', async (original) => ({
  ...(await original<typeof import('@inertiajs/react')>()),
  usePage: () => page,
  Head: () => null,
}));

const { default: ContentSnapshots } = await import('../../pages/ContentSnapshots');

const SNAPSHOT: Snapshot = {
  id: 7,
  note: 'before the redesign',
  source: 'manual',
  format_version: 1,
  manifest: {
    format_version: 1,
    created_at: '2026-10-01T00:00:00Z',
    pages: [],
    layout: { header: 0, footer: 0 },
    counts: { pages: 1, redirects: 0, media: 0 },
    missing_media: [],
  },
  size_bytes: 1024,
  created_at: '2026-10-01T00:00:00Z',
  created_by: 'someone',
};

const PENDING = { id: 3, snapshot_id: 7, status: 'pending' } as unknown as PendingImport;

function controls(markup: string): string[] {
  const doc = new DOMParser().parseFromString(`<div>${markup}</div>`, 'text/html');
  return [...doc.querySelectorAll('button, a')].map((el) => el.textContent?.trim() ?? '');
}

function list(canPublish?: boolean): string[] {
  return controls(
    renderToStaticMarkup(
      <SnapshotList
        snapshots={[SNAPSHOT]}
        busy={false}
        canPublish={canPublish}
        hasPending={false}
        pendingSnapshotId={null}
        onRestore={async () => undefined}
        onDelete={async () => undefined}
      />,
    ),
  );
}

function screen(capabilities?: SnapshotCapabilities): string {
  page.props = { snapshots: [SNAPSHOT], pending: PENDING, sections: [], capabilities };
  return renderToStaticMarkup(<ContentSnapshots />);
}

describe('SnapshotList controls', () => {
  it('offers Download, Restore and Delete to a publisher', () => {
    expect(list(true)).toEqual(['Download', 'Restore…', 'Delete']);
  });

  it('offers no actions to a reader without publish, and defaults to none', () => {
    expect(list(false)).toEqual([]);
    expect(list()).toEqual([]);
  });
});

describe('ContentSnapshots controls', () => {
  it('gives a publisher Upload and Take beside the list', () => {
    expect(controls(screen({ publish: true, approve: false }))).toEqual(
      expect.arrayContaining(['Upload bundle…', 'Take snapshot', 'Restore…', 'Delete']),
    );
  });

  it('shows an approver the list and the pending restore, without publish actions', () => {
    const markup = screen({ publish: false, approve: true });
    expect(markup).toContain('before the redesign');
    expect(controls(markup)).toEqual(['Review it']);
  });

  it('fails closed when the server sent no capabilities', () => {
    expect(controls(screen(undefined))).toEqual(['Review it']);
  });
});
