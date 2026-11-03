/** Breaks between passages. */

import type { ComponentConfig } from '@puckeditor/core';

import { keys } from '../../../utils/i18n';

export interface DividerProps {
  spacing: 'small' | 'large';
  style: 'rule' | 'asterism';
}

/**
 * A break in the story.
 *
 * Two styles, because they mean different things. A rule separates the article
 * from something appended to it; an asterism — the centred `* * *` of long-form
 * — marks a change of scene or of time *within* one continuous piece, and a
 * reader who knows the convention reads straight through it.
 */
export const DividerBlock: ComponentConfig<DividerProps> = {
  label: keys.news.blocks.divider.label,
  fields: {
    style: {
      type: 'radio',
      label: keys.news.blocks.common.style,
      options: [
        { label: keys.news.blocks.divider.style_rule, value: 'rule' },
        { label: keys.news.blocks.divider.style_asterism, value: 'asterism' },
      ],
    },
    spacing: {
      type: 'select',
      label: keys.news.blocks.divider.spacing,
      options: [
        { label: keys.news.blocks.divider.spacing_small, value: 'small' },
        { label: keys.news.blocks.divider.spacing_large, value: 'large' },
      ],
    },
  },
  // `rule` is the default so every divider written before there was a choice
  // renders exactly as it did.
  defaultProps: { spacing: 'small', style: 'rule' },
  render: ({ spacing, style }) => {
    const margin = spacing === 'large' ? 'my-12' : 'my-6';
    if (style === 'asterism') {
      return (
        <p
          // Decorative: the break is carried by the spacing for anyone not
          // seeing the glyphs, and three read-out asterisks are noise.
          aria-hidden="true"
          className={`${margin} text-center text-lg tracking-[0.6em] text-muted-foreground`}
        >
          ***
        </p>
      );
    }
    return <hr className={margin} />;
  },
};
