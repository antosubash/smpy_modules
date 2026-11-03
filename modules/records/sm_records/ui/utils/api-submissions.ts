/**
 * The admin actions on a website submission (#101):
 * `POST /api/records/types/{key}/records/{uuid}/submission/{resend|spam|not-spam}`.
 * Split from `api-records.ts` for the 300-line cap; same `request` plumbing,
 * so the CSRF header and the 401 handling come with it.
 */

import { request } from './api';
import type { RecordRead } from './types';

function path(typeKey: string, uuid: string, action: string): string {
  return `/types/${encodeURIComponent(typeKey)}/records/${encodeURIComponent(uuid)}/submission/${action}`;
}

/** Queue the notification again. At most once a minute per record (429). */
export function resendNotification(typeKey: string, uuid: string): Promise<{ queued: boolean }> {
  return request(path(typeKey, uuid, 'resend'), { method: 'POST' });
}

/** Mark as spam: `sm_spam = "manual"`, and into the trash. */
export function markSpam(typeKey: string, uuid: string): Promise<RecordRead> {
  return request(path(typeKey, uuid, 'spam'), { method: 'POST' });
}

/** Out of the trash, `sm_spam` cleared, and the notification sent. */
export function markNotSpam(typeKey: string, uuid: string): Promise<RecordRead> {
  return request(path(typeKey, uuid, 'not-spam'), { method: 'POST' });
}

/** A newsletter subscriber still pending: send the confirmation again (the
 *  same `resend` route; 409 when not pending, 429 past the address's budget). */
export function resendConfirmation(typeKey: string, uuid: string): Promise<{ queued: boolean }> {
  return request(path(typeKey, uuid, 'resend'), { method: 'POST' });
}

/** Unsubscribe a newsletter subscriber, as their own link would. */
export function unsubscribeSubscriber(typeKey: string, uuid: string): Promise<RecordRead> {
  return request(path(typeKey, uuid, 'unsubscribe'), { method: 'POST' });
}
