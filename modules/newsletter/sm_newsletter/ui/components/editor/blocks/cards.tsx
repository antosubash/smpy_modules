/**
 * ArticleCard and PageCard: a snapshot of a news article or a pagebuilder page.
 *
 * Both are always *defined* (ruling R2): a card already in the body renders
 * from its snapshot and can be deleted even when its integration is gone. The
 * palette decides whether a new one can be inserted (`buildConfig`), and the
 * one field, `CardPicker`, is disabled with a note.
 *
 * The props are the server's snapshot (`content/blocks.py` `CardProps`); only
 * `source_id` carries a field, the picker that rewrites all of them.
 */

import type { ComponentConfig } from '@puckeditor/core';

import { keys, useT } from '../../../utils/i18n';
import type { CardKind } from '../../../utils/types';
import { cardField } from '../CardPicker';

import { ACCENT, block, FONT, MUTED } from './email';

const copy = keys.newsletter.blocks;

export interface CardProps {
  source_id: number;
  title: string;
  excerpt: string;
  image_url: string;
  url: string;
  locale: string;
  snapshot_at: string;
}

function EmptyCard() {
  const { t } = useT();
  return (
    <div
      style={{
        border: `1px dashed ${MUTED}`,
        color: MUTED,
        fontFamily: FONT,
        padding: 24,
        textAlign: 'center',
      }}
    >
      {t(copy.card_empty)}
    </div>
  );
}

function ReadMore() {
  const { t } = useT();
  return (
    <span style={{ color: ACCENT, textDecoration: 'underline' }}>
      {t(keys.newsletter.email.read_more)}
    </span>
  );
}

function CardView({ source_id, title, excerpt, image_url }: CardProps) {
  if (!source_id) {
    return (
      <div style={block}>
        <EmptyCard />
      </div>
    );
  }
  return (
    <div style={block}>
      {image_url && (
        <img
          src={image_url}
          alt={title}
          style={{ display: 'block', maxWidth: '100%', height: 'auto', border: 0 }}
        />
      )}
      <h3 style={{ margin: '12px 0 8px', fontFamily: FONT, fontSize: 18, lineHeight: 1.3 }}>
        {title}
      </h3>
      {excerpt && (
        <p style={{ margin: '0 0 8px', fontFamily: FONT, fontSize: 15, lineHeight: 1.5 }}>
          {excerpt}
        </p>
      )}
      <ReadMore />
    </div>
  );
}

const EMPTY: CardProps = {
  source_id: 0,
  title: '',
  excerpt: '',
  image_url: '',
  url: '',
  locale: '',
  snapshot_at: '',
};

/** A card block for `kind`; `available` is that integration's capability. */
export function cardBlock(
  kind: CardKind,
  available: boolean,
): ComponentConfig<CardProps, Pick<CardProps, 'source_id'>> {
  return {
    label: kind === 'article' ? copy.article_card.label : copy.page_card.label,
    fields: { source_id: cardField(kind, available) },
    defaultProps: EMPTY,
    render: (props) => <CardView {...props} />,
  };
}
