/**
 * The share dialog's calls: the framework's `/api/sharing/shares` (list, grant,
 * revoke) and events' own picker. A calendar is addressed as
 * `events.calendar` with its UUID string as `resource_id`, the encoding the
 * resource type's loader (`sm_events/core/access/resource_types.py`) parses.
 */

import { CALENDARS, send } from './api';
import type { Share, ShareCandidate, ShareRole } from './types';

const RESOURCE_TYPE = 'events.calendar';
const SHARES = '/api/sharing/shares';

export function listShares(calendarId: string, signal?: AbortSignal): Promise<Share[]> {
  const qs = new URLSearchParams({ resource_type: RESOURCE_TYPE, resource_id: calendarId });
  return send(`${SHARES}?${qs.toString()}`, { signal });
}

export function grantShare(calendarId: string, subjectId: string, role: ShareRole): Promise<Share> {
  return send(SHARES, {
    method: 'POST',
    json: {
      resource_type: RESOURCE_TYPE,
      resource_id: calendarId,
      subject_id: subjectId,
      role,
    },
  });
}

export function revokeShare(shareId: string): Promise<void> {
  return send(`${SHARES}/${shareId}`, { method: 'DELETE' });
}

export function shareCandidates(
  calendarId: string,
  q: string,
  signal?: AbortSignal,
): Promise<ShareCandidate[]> {
  const qs = new URLSearchParams({ q });
  return send(`${CALENDARS}/${calendarId}/share-candidates?${qs.toString()}`, { signal });
}
