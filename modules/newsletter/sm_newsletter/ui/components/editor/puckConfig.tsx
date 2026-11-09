/**
 * The Puck config a campaign's email is written with — newsletter's own, not
 * pagebuilder's: eight blocks that the server knows how to render as email
 * (`content/blocks.py`), one column, no DropZones or slots (an email is a
 * single 600 px column and the body is a flat list, ruling R8).
 *
 * Built per editor from the host's capabilities (ruling R2, ruling C9):
 * every block is always *defined*, so a card already in a campaign renders
 * and can be deleted after its integration is gone. Only the palette changes —
 * an unavailable card sits in the invisible `hidden` category instead of
 * `cards`. Labels are catalogue keys; `localizeConfig` resolves them.
 */

import type { Config } from '@puckeditor/core';
import type { ReactNode } from 'react';

import { keys } from '../../utils/i18n';
import { cardBlock } from './blocks/cards';
import { PAGE_BG } from './blocks/email';
import { ButtonBlock, DividerBlock, imageBlock, SpacerBlock } from './blocks/media';
import { HeadingBlock, RichTextBlock } from './blocks/text';

export interface Capabilities {
  news: boolean;
  pagebuilder: boolean;
}

const copy = keys.newsletter.blocks.categories;

/** The single column the email is laid out in (`styles.WIDTH`). */
const EMAIL_WIDTH = 600;

function EmailColumn({ children }: { children?: ReactNode }) {
  return (
    <div style={{ background: PAGE_BG, padding: '24px 0', minHeight: '100%' }}>
      <div
        style={{
          width: '100%',
          maxWidth: EMAIL_WIDTH,
          margin: '0 auto',
          background: '#ffffff',
          paddingTop: 16,
        }}
      >
        {children}
      </div>
    </div>
  );
}

export function buildConfig(caps: Capabilities): Config {
  const cards = { ArticleCard: caps.news, PageCard: caps.pagebuilder };
  const available = Object.keys(cards).filter((name) => cards[name as keyof typeof cards]);
  const unavailable = Object.keys(cards).filter((name) => !cards[name as keyof typeof cards]);

  return {
    root: {
      // No root fields: the subject, preheader and sender are the campaign's
      // own columns, edited in `CampaignMeta`, and `root` is not stored (R8).
      fields: {},
      render: ({ children }: { children?: ReactNode }) => <EmailColumn>{children}</EmailColumn>,
    },
    categories: {
      content: { title: copy.content, components: ['Heading', 'RichText', 'Image', 'Button'] },
      layout: { title: copy.layout, components: ['Divider', 'Spacer'] },
      cards: {
        title: copy.cards,
        components: available,
        ...(available.length === 0 ? { visible: false } : {}),
      },
      hidden: { components: unavailable, visible: false },
      other: { visible: false },
    },
    // Each block is typed against its own props; Puck's `Config` without a
    // props map takes them as one loose record.
    components: {
      Heading: HeadingBlock,
      RichText: RichTextBlock,
      Image: imageBlock(caps.pagebuilder),
      Button: ButtonBlock,
      Divider: DividerBlock,
      Spacer: SpacerBlock,
      ArticleCard: cardBlock('article', caps.news),
      PageCard: cardBlock('page', caps.pagebuilder),
    } as Config['components'],
  };
}
