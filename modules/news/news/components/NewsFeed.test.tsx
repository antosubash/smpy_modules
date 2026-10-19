import { describe, expect, it } from 'vitest';

import { NewsFeedBlock, type NewsFeedProps } from './NewsFeed';

const props: NewsFeedProps = {
  title: 'Latest',
  category: '',
  limit: 4,
  columns: '4',
  viewAllLabel: '',
  viewAllHref: '',
};

type ResolveData = (
  data: { props: Record<string, unknown> },
  params: { trigger: string },
) => Promise<{ props: Record<string, unknown> }> | { props: Record<string, unknown> };

async function resolve(trigger: string, limit: unknown): Promise<unknown> {
  const resolveData = NewsFeedBlock.resolveData as unknown as ResolveData;
  const out = await resolveData({ props: { ...props, limit } }, { trigger });
  return out.props.limit;
}

describe('NewsFeedBlock.resolveData', () => {
  it('clamps a stored limit when the page loads', async () => {
    expect(await resolve('load', 4.5)).toBe(4);
    expect(await resolve('load', 50)).toBe(12);
    expect(await resolve('load', -3)).toBe(1);
    expect(await resolve('load', '')).toBe(4);
  });

  it('leaves the field alone while the author edits it', async () => {
    expect(await resolve('replace', '')).toBe('');
  });
});
