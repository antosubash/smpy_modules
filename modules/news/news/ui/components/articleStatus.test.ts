import { describe, expect, it } from 'vitest';

import { keys } from '../utils/i18n';
import type { ArticleRead } from '../utils/types';
import { statusLine } from './articleStatus';

const t = (key: string, params?: Record<string, unknown>) =>
  `${key}${params ? JSON.stringify(params) : ''}`;
const draft = (over: Partial<ArticleRead>) =>
  ({ status: 'draft', published_at: null, ...over }) as ArticleRead;

describe('statusLine', () => {
  it('says a draft with a go-live time is scheduled, with the time', () => {
    const line = statusLine(
      draft({ published_at: '2026-03-01T00:00:00Z', scheduled_at: '2026-03-02T09:30:00Z' }),
      t,
      'en',
    );
    expect(line.startsWith(keys.news.row.status_draft_scheduled)).toBe(true);
    expect(line).toContain('Mar 2, 2026');
  });

  it('keeps the dated and undated wording for an unscheduled draft', () => {
    expect(statusLine(draft({}), t)).toBe(keys.news.row.status_draft_undated);
    expect(statusLine(draft({ scheduled_at: null }), t)).toBe(keys.news.row.status_draft_undated);
  });
});
