// @vitest-environment happy-dom
import { act } from 'react';
import { expect, it, vi } from 'vitest';

import { form, schedule, server } from './pageEditor-test-support';

it.each(['save', 'clear'])('a refused schedule %s preserves the accepted dates', async (action) => {
  await act(async () => {
    schedule.setPublishAt('2099-01-01T09:00:00Z');
    schedule.setUnpublishAt('2099-01-02T09:00:00Z');
  });
  await act(async () => schedule.handleSaveSchedule());
  expect(form.publishAt).toBe('2099-01-01T09:00:00.000Z');
  const stored = { publish: server.publish_at, unpublish: server.unpublish_at };
  await act(async () => schedule.setPublishAt('2099-01-01T10:00:00Z'));
  vi.mocked(fetch).mockResolvedValueOnce(new Response('', { status: 503 }));
  await act(async () =>
    action === 'save' ? schedule.handleSaveSchedule() : schedule.handleClearSchedule(),
  );
  expect(schedule.scheduleError).not.toBeNull();
  expect(form.publishAt).toBe(stored.publish);
  expect(form.unpublishAt).toBe(stored.unpublish);
  expect(schedule.publishAt).toBe('2099-01-01T10:00:00Z');
  expect(server.publish_at).toBe(stored.publish);
  expect(server.unpublish_at).toBe(stored.unpublish);
});
