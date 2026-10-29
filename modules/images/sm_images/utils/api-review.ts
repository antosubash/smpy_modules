/** `/api/images` review endpoints (`sm_images/endpoints/api/review.py`). */

import { send } from './api';
import type { JsonSchema, PromptResult } from './types-prompts';

const BASE = '/api/images';
const PAGE = 50;

export type ReviewStatus = 'unreviewed' | 'accepted' | 'corrected' | 'rejected';
export type ReviewFilter = ReviewStatus | 'all';
export type ReviewAction = 'accept' | 'correct' | 'reject';

/** One queue row: a result plus what is needed to judge it. */
export type ReviewItem = PromptResult & {
  /** Sent back with the review; another version is a 409 `review_stale`. */
  version: string;
  prompt_name: string;
  output_schema: JsonSchema | null;
  filename: string | null;
  thumb_url: string | null;
  group_key: string | null;
  output_visible: boolean;
  reviewed_data: Record<string, unknown> | null;
};

export type ReviewPage = { items: ReviewItem[]; next_cursor: number | null };

export type ReviewQuery = { status: ReviewFilter; prompt: string | null; after?: number | null };

export function listReview(collectionId: string, q: ReviewQuery): Promise<ReviewPage> {
  const params = new URLSearchParams({ status: q.status, limit: String(PAGE) });
  if (q.prompt) params.set('prompt', q.prompt);
  if (q.after != null) params.set('after', String(q.after));
  return send(`${BASE}/collections/${collectionId}/review?${params}`);
}

export async function reviewResult(
  id: number,
  action: ReviewAction,
  version: string,
  data?: Record<string, unknown>,
): Promise<ReviewItem> {
  const { item } = await send<{ item: ReviewItem }>(`${BASE}/prompt-results/${id}/review`, {
    method: 'POST',
    body: JSON.stringify({ action, version, ...(data ? { data } : {}) }),
    headers: { 'Content-Type': 'application/json' },
  });
  return item;
}
