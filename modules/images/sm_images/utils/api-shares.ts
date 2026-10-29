/**
 * The share dialog's calls: the framework's `/api/sharing/shares` (list, grant,
 * revoke) and images' own picker. A collection is addressed as
 * `images.collection` with its UUID string as `resource_id`, the encoding the
 * resource type's loader (`sm_images/resource_types.py`) parses.
 */

import { json, send } from './api';
import type { Share, ShareCandidate, ShareRole } from './types';

export const RESOURCE_TYPE = 'images.collection';
const SHARES = '/api/sharing/shares';

export function listShares(collectionId: string): Promise<Share[]> {
  const qs = new URLSearchParams({ resource_type: RESOURCE_TYPE, resource_id: collectionId });
  return send(`${SHARES}?${qs.toString()}`);
}

export function grantShare(
  collectionId: string,
  subjectId: string,
  role: ShareRole,
): Promise<Share> {
  return send(
    SHARES,
    json('POST', {
      resource_type: RESOURCE_TYPE,
      resource_id: collectionId,
      subject_id: subjectId,
      role,
    }),
  );
}

export function revokeShare(shareId: string): Promise<void> {
  return send(`${SHARES}/${shareId}`, { method: 'DELETE' });
}

export function shareCandidates(collectionId: string, q: string): Promise<ShareCandidate[]> {
  const qs = new URLSearchParams({ q });
  return send(`/api/images/collections/${collectionId}/share-candidates?${qs.toString()}`);
}
