/** The reminders' calls: following an event, "my reminders", and the delivery status.
 *  A follow is addressed by its event, always the caller's own; there is no call that takes
 *  another user's id. */

import { send } from './api';

const API = '/api/events';
export const REMINDERS = `${API}/reminders`;

/** The lead times a reminder can have, in minutes (the server's closed set). */
export type Lead = number;

export type ReminderStatus = {
  available: boolean;
  /** Only for someone who manages events, and only while reminders are unavailable. */
  reason?: string;
  leads: Lead[];
};

export type Follow = {
  leads: Lead[];
  /** What "Remind me" preselects on the event's calendar. */
  defaults: Lead[];
  /** Per chosen lead, when its next reminder is due; `null`: too late for the next occurrence. */
  next_due: Record<string, string | null>;
  /** No uncancelled occurrence is coming: nothing is left to remind of. */
  over?: boolean;
  /** False when the worker could not verify this user's access: the follow is kept, no mail
   *  would come. */
  deliverable: boolean;
  code: string | null;
};

export type Counts = { sent: number; failed: Record<string, number>; unfinished: number };

export type MineItem = {
  /** The handle Remove takes: one of the caller's own follows on this event. */
  follow_id: string;
  /** An event the caller can no longer see: everything below is empty. */
  hidden: boolean;
  event_id: string | null;
  title: string | null;
  lang: string | null;
  calendar: { id: string; name: string; color: string } | null;
  leads: Lead[];
  next_start: string | null;
  deliverable: boolean;
};

export type MinePage = {
  items: MineItem[];
  total: number;
  hidden: number;
  page: number;
  page_size: number;
  counts: Counts;
};

export type Delivery = {
  enabled: boolean;
  available: boolean;
  reason: string | null;
  defaults: Lead[];
  window_days: number;
  counts: Counts;
};

export const reminderStatus = (signal?: AbortSignal) =>
  send<ReminderStatus>(`${REMINDERS}/status`, { signal });

let cached: Promise<ReminderStatus> | null = null;
/** The status once per page load, so a calendar full of popovers asks once. A failure is not
 *  remembered. */
export function reminderStatusOnce(): Promise<ReminderStatus> {
  cached ??= reminderStatus().catch((error) => {
    cached = null;
    throw error;
  });
  return cached;
}
export const resetReminderStatus = () => {
  cached = null;
};

const follow = (eventId: string) => `${API}/events/${eventId}/follow`;
export const getFollow = (eventId: string, signal?: AbortSignal) =>
  send<Follow>(follow(eventId), { signal });
export const setFollow = (eventId: string, leads: Lead[]) =>
  send<Follow>(follow(eventId), { method: 'PUT', json: { leads } });
export const deleteFollow = (eventId: string) => send<void>(follow(eventId), { method: 'DELETE' });

export const myReminders = (page: number, pageSize: number, signal?: AbortSignal) =>
  send<MinePage>(`${REMINDERS}/mine?page=${page}&page_size=${pageSize}`, { signal });
export const removeFollowById = (followId: string) =>
  send<void>(`${REMINDERS}/follows/${followId}`, { method: 'DELETE' });
export const deliveryStatus = (signal?: AbortSignal) =>
  send<Delivery>(`${REMINDERS}/delivery`, { signal });
