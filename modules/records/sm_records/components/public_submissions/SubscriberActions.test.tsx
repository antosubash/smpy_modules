// @vitest-environment happy-dom
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { click, mount, settle } from '../../test-dom';
import type { RecordRead, TypeRead } from '../../utils/types';

const api = vi.hoisted(() => ({
  resendConfirmation: vi.fn(async () => ({ queued: true })),
  unsubscribeSubscriber: vi.fn(),
  resendNotification: vi.fn(),
  markSpam: vi.fn(),
  markNotSpam: vi.fn(),
}));
vi.mock('../../utils/api-submissions', () => api);
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const { SubscriberActions } = await import('./SubscriberActions');
const { SubmissionPanel } = await import('./SubmissionPanel');
const { toast } = await import('sonner');
const { ApiError } = await import('../../utils/api');

const LIST = {
  key: 'news',
  label: 'News',
  fields: [],
  public_submissions: { kind: 'subscription', enabled: true, public_fields: [], notify_to: [] },
} as unknown as TypeRead;

function record(data: Record<string, unknown>, isDeleted = false): RecordRead {
  return { uuid: 's1', is_deleted: isDeleted, data } as unknown as RecordRead;
}

describe('SubscriberActions', () => {
  beforeEach(() => {
    api.resendConfirmation.mockClear();
    api.unsubscribeSubscriber.mockReset();
  });

  it('resends a pending confirmation and says when none went out', async () => {
    const view = await mount(
      <SubscriberActions
        type={LIST}
        record={record({ sm_status: 'pending', sm_confirm_sent_at: null })}
        onChanged={vi.fn()}
      />,
    );
    expect(view.find('[data-testid="records-confirmation-not-sent"]')?.textContent).toBe(
      'Confirmation not sent',
    );
    await click(view.button('Resend confirmation'));
    await settle();
    expect(api.resendConfirmation).toHaveBeenCalledWith('news', 's1');
    expect(toast.success).toHaveBeenLastCalledWith('The confirmation email will be sent again.');
    await view.unmount();
  });

  it("says the address's budget in its own words", async () => {
    api.resendConfirmation.mockRejectedValueOnce(new ApiError(429, { detail: 'x' }, 'x'));
    const view = await mount(
      <SubscriberActions
        type={LIST}
        record={record({ sm_status: 'pending' })}
        onChanged={vi.fn()}
      />,
    );
    await click(view.button('Resend confirmation'));
    await settle();
    expect(toast.error).toHaveBeenLastCalledWith(
      'This address was sent its confirmation too often. Try again later.',
    );
    await view.unmount();
  });

  it('offers only unsubscribe to a confirmed subscriber, and nothing once gone', async () => {
    const view = await mount(
      <SubscriberActions
        type={LIST}
        record={record({ sm_status: 'confirmed' })}
        onChanged={vi.fn()}
      />,
    );
    expect(view.button('Resend confirmation')).toBeUndefined();
    expect(view.button('Unsubscribe')).toBeDefined();
    await view.render(
      <SubscriberActions
        type={LIST}
        record={record({ sm_status: 'unsubscribed' })}
        onChanged={vi.fn()}
      />,
    );
    expect(view.find('[data-testid="records-subscriber-actions"]')).toBeNull();
    await view.unmount();
  });

  it('is what the panel shows for a newsletter list', async () => {
    const view = await mount(
      <SubmissionPanel
        type={LIST}
        current={record({ sm_status: 'pending' })}
        onChanged={vi.fn()}
      />,
    );
    expect(view.find('[data-testid="records-subscriber-actions"]')).not.toBeNull();
    expect(view.find('[data-testid="records-submission-actions"]')).toBeNull();
    await view.unmount();
  });
});
