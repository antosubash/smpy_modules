import { describe, expect, it } from 'vitest';

import type { ArticleRead } from '../../../utils/api';
import { pickRelated, RelatedBlock } from './related';

function article(slug: string): ArticleRead {
  return {
    id: slug.length,
    slug,
    title: slug,
    excerpt: '',
    cover_image_url: '',
    category: '',
    tags: [],
    pinned: false,
    show_in_feed: true,
    author: '',
    published_at: null,
    updated_at: null,
    locale: 'en',
    translation_group: '',
    status: 'published',
    has_unpublished_changes: false,
    url: `/news/${slug}`,
    edit_url: '',
  } as ArticleRead;
}

const ARCHIVE = ['a', 'b', 'c', 'd'].map(article);

describe('pickRelated', () => {
  it('leaves out the article the reader is already on', () => {
    // The whole reason the viewer hands the block its slug: a "read next" list
    // offering the current article is visibly broken.
    expect(pickRelated(ARCHIVE, 'b', 3).map((a) => a.slug)).toEqual(['a', 'c', 'd']);
  });

  it('still fills the list when the current article is excluded', () => {
    // The fetch asks for one more than needed precisely so this holds.
    expect(pickRelated(ARCHIVE, 'a', 3)).toHaveLength(3);
  });

  it('lists everything when the current slug is unknown', () => {
    // On the canvas there is no current article, and a writer should see the
    // list a reader would rather than a short one.
    expect(pickRelated(ARCHIVE, undefined, 4).map((a) => a.slug)).toEqual(['a', 'b', 'c', 'd']);
  });

  it('never returns more than the cap, whatever the stored limit says', () => {
    // A document hand-edited past the field's max must not turn the foot of an
    // article into a second front page.
    const many = Array.from({ length: 20 }, (_, i) => article(`x${i}`));
    expect(pickRelated(many, undefined, 99)).toHaveLength(6);
  });

  it('returns at least one for a nonsensical limit', () => {
    expect(pickRelated(ARCHIVE, undefined, 0)).toHaveLength(1);
    expect(pickRelated(ARCHIVE, undefined, -3)).toHaveLength(1);
  });

  it('copes with an archive holding only the current article', () => {
    expect(pickRelated([article('only')], 'only', 3)).toEqual([]);
  });

  it('excludes translations of the current story and keeps the content locale', () => {
    const articles = [
      { ...article('story'), translation_group: 'current' },
      { ...article('geschichte'), locale: 'de', translation_group: 'current' },
      { ...article('other'), translation_group: 'other' },
      { ...article('fremd'), locale: 'de', translation_group: 'foreign' },
    ];
    expect(pickRelated(articles, 'story', 3, 'current', 'en').map((a) => a.slug)).toEqual([
      'other',
    ]);
    // Check the two exclusions independently: locale filtering must not hide a missing group filter.
    expect(pickRelated(articles, 'story', 3, 'current').map((a) => a.slug)).toEqual([
      'other',
      'fremd',
    ]);
    expect(pickRelated(articles, 'story', 3, undefined, 'en').map((a) => a.slug)).toEqual([
      'other',
    ]);
  });
});

describe('Read next', () => {
  it('offers a limit field bounded by the same cap the filter enforces', () => {
    // Two places agreeing by accident is how the cap stops meaning anything.
    const field = RelatedBlock.fields?.limit as { max?: number };
    expect(field?.max).toBe(6);
    expect(
      pickRelated(
        Array.from({ length: 10 }, (_, i) => article(`y${i}`)),
        undefined,
        6,
      ),
    ).toHaveLength(6);
  });
});
