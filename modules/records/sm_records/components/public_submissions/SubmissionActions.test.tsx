// @vitest-environment happy-dom
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { click, mount, settle } from '../../test-dom';
import type { RecordRead, TypeRead } from '../../utils/types';

const api = vi.hoisted(() => ({
  resendNotification: vi.fn(async () => ({ queued: true })),
  markSpam: vi.fn(),
  markNotSpam: vi.fn(),
}));
vi.mock('../../utils/api-submissions', () => api);
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const { SubmissionActions } = await import('./SubmissionActions');
const { SubmissionPanel } = await import('./SubmissionPanel');
const { toast } = await import('sonner');
const { ApiError } = await import('../../utils/api');

function type(notifyTo: string[] = ['ops@example.org'], kind = 'form'): TypeRead {
  return {
    key: 'contact',
    label: 'Contact',
    fields: [],
    public_submissions: {
      kind,
      enabled: true,
      public_fields: [],
      notify_to: notifyTo,
      consent: { required: false, text: {} },
      double_opt_in: true,
      retention_days: 365,
      pending_purge_days: 30,
    },
  } as unknown as TypeRead;
}

function record(data: Record<string, unknown>, isDeleted = false): RecordRead {
  return { uuid: 'r1', is_deleted: isDeleted, data } as unknown as RecordRead;
}

describe("SubmissionActions — refusals in the admin's language", () => {
  it("says the resend limit and a stale record in its own words, not the server's", async () => {
    api.resendNotification.mockRejectedValueOnce(
      new ApiError(429, { detail: 'too many submissions' }, 'too many submissions'),
    );
    api.markNotSpam.mockRejectedValueOnce(new ApiError(404, { detail: 'no record' }, 'no record'));
    const view = await mount(
      <SubmissionActions type={type()} record={record({})} onChanged={vi.fn()} />,
    );
    await click(view.button('Resend notification'));
    await settle();
    expect(toast.error).toHaveBeenLastCalledWith(
      'The notification was just sent again. Try again in a minute.',
    );
    await view.render(
      <SubmissionActions
        type={type()}
        record={record({ sm_spam: 'manual' }, true)}
        onChanged={vi.fn()}
      />,
    );
    await click(view.button('Not spam'));
    await settle();
    expect(String(vi.mocked(toast.error).mock.lastCall?.[0])).toContain('Reload the page');
    await view.unmount();
  });
});

describe('SubmissionActions', () => {
  beforeEach(() => {
    api.resendNotification.mockClear();
    api.markNotSpam.mockReset();
  });

  it('says a notification was not sent and resends it', async () => {
    const view = await mount(
      <SubmissionActions
        type={type()}
        record={record({ sm_notified_at: null })}
        onChanged={vi.fn()}
      />,
    );
    expect(view.find('[data-testid="records-submission-not-sent"]')?.textContent).toBe(
      'Notification not sent',
    );
    await click(view.button('Resend notification'));
    await settle();
    expect(api.resendNotification).toHaveBeenCalledWith('contact', 'r1');
    expect(view.button('Mark as spam')).toBeDefined();
    await view.unmount();
  });

  it('offers no resend when the type notifies nobody, and no badge once sent', async () => {
    const view = await mount(
      <SubmissionActions type={type([])} record={record({})} onChanged={vi.fn()} />,
    );
    expect(view.button('Resend notification')).toBeUndefined();
    expect(view.find('[data-testid="records-submission-not-sent"]')).toBeNull();
    await view.render(
      <SubmissionActions
        type={type()}
        record={record({ sm_notified_at: '2026-10-25T10:00:00Z' })}
        onChanged={vi.fn()}
      />,
    );
    expect(view.find('[data-testid="records-submission-not-sent"]')).toBeNull();
    await view.unmount();
  });

  it('brings a spam submission back from the trash', async () => {
    const restored = record({ sm_spam: null });
    api.markNotSpam.mockResolvedValue(restored);
    const onChanged = vi.fn();
    const view = await mount(
      <SubmissionActions
        type={type()}
        record={record({ sm_spam: 'links' }, true)}
        onChanged={onChanged}
      />,
    );
    expect(view.host.textContent).toContain('Kept as spam (too many links)');
    await click(view.button('Not spam'));
    await settle();
    expect(api.markNotSpam).toHaveBeenCalledWith('contact', 'r1');
    expect(onChanged).toHaveBeenCalledWith(restored);
    await view.unmount();
  });

  it('leaves an ordinary trashed record to the restore button', async () => {
    const view = await mount(
      <SubmissionActions type={type()} record={record({}, true)} onChanged={vi.fn()} />,
    );
    expect(view.find('[data-testid="records-submission-actions"]')).toBeNull();
    await view.unmount();
  });
});

describe('SubmissionPanel', () => {
  it('shows the actions for a saved contact-form record only', async () => {
    const view = await mount(
      <SubmissionPanel type={type()} current={record({})} onChanged={vi.fn()} />,
    );
    expect(view.find('[data-testid="records-submission-actions"]')).not.toBeNull();
    await view.render(<SubmissionPanel type={type()} current={null} onChanged={vi.fn()} />);
    expect(view.find('[data-testid="records-submission-actions"]')).toBeNull();
    await view.render(
      <SubmissionPanel type={type([], 'subscription')} current={record({})} onChanged={vi.fn()} />,
    );
    expect(view.find('[data-testid="records-submission-actions"]')).toBeNull();
    await view.unmount();
  });
});
