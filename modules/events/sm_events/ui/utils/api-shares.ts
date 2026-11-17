/**
 * The share dialog's calls: the framework's `/api/sharing/shares` (list, grant,
 * revoke) and events' own picker. A calendar is addressed as
 * `events.calendar` with its UUID string as `resource_id`, the encoding the
 * resource type's loader (`sm_events/access/resource_types.py`) parses.
 */

import { json, send } from './api';
import type { Share, ShareCandidate, ShareRole } from './types';

const RESOURCE_TYPE = 'events.calendar';
const SHARES = '/api/sharing/shares';

export function listShares(calendarId: string): Promise<Share[]> {
  const qs = new URLSearchParams({ resource_type: RESOURCE_TYPE, resource_id: calendarId });
  return send(`${SHARES}?${qs.toString()}`);
}

export function grantShare(calendarId: string, subjectId: string, role: ShareRole): Promise<Share> {
  return send(
    SHARES,
    json('POST', {
      resource_type: RESOURCE_TYPE,
      resource_id: calendarId,
      subject_id: subjectId,
      role,
    }),
  );
}

export function revokeShare(shareId: string): Promise<void> {
  return send(`${SHARES}/${shareId}`, { method: 'DELETE' });
}

export function shareCandidates(calendarId: string, q: string): Promise<ShareCandidate[]> {
  const qs = new URLSearchParams({ q });
  return send(`/api/events/calendars/${calendarId}/share-candidates?${qs.toString()}`);
}
