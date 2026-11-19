/**
 * EventCard: a snapshot of a published event of a public calendar.
 *
 * Always *defined* (ruling R2), like the article and page cards: a card already in the body
 * renders from its snapshot and can be deleted even when events is gone. The palette decides
 * whether a new one can be inserted (`buildConfig`). The canvas is only a preview: its when-line
 * is formatted with `Intl` (`utils/eventWhen.ts`), the email's by the server.
 *
 * The event's id (`source_id`) is a field's value, never shown.
 */

import type { ComponentConfig } from '@puckeditor/core';

import { formatEventWhen } from '../../../utils/eventWhen';
import { keys, useT } from '../../../utils/i18n';
import type { EventCardSnapshot } from '../../../utils/types';
import { cardField } from '../CardPicker';

import { ACCENT, block, FONT, MUTED } from './email';

const copy = keys.newsletter.blocks;
const META = { margin: '0 0 4px', fontFamily: FONT, fontSize: 14, color: MUTED };

export type EventCardProps = Omit<EventCardSnapshot, 'id'>;

function placeLine(p: EventCardProps, online: string): string {
  if (p.attendance_mode === 'online') return online;
  if (p.attendance_mode === 'hybrid') return [p.place, online].filter(Boolean).join(' · ');
  return p.place;
}

function EventCardView(p: EventCardProps) {
  const { t, locale } = useT();
  if (!p.source_id) {
    return (
      <div style={block}>
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
      </div>
    );
  }
  const place = placeLine(p, t(keys.newsletter.email.online));
  return (
    <div style={block}>
      {p.image_url && (
        <img
          src={p.image_url}
          alt={p.title}
          style={{ display: 'block', maxWidth: '100%', height: 'auto', border: 0 }}
        />
      )}
      {p.cancelled && (
        <p style={{ ...META, color: '#b91c1c', fontWeight: 'bold' }}>
          {t(keys.newsletter.email.cancelled)}
        </p>
      )}
      <h3 style={{ margin: '12px 0 8px', fontFamily: FONT, fontSize: 18, lineHeight: 1.3 }}>
        {p.title}
      </h3>
      <p style={META}>{formatEventWhen(p, locale || 'en')}</p>
      {place && <p style={META}>{place}</p>}
      {p.excerpt && (
        <p style={{ margin: '0 0 8px', fontFamily: FONT, fontSize: 15, lineHeight: 1.5 }}>
          {p.excerpt}
        </p>
      )}
      <span style={{ color: ACCENT, textDecoration: 'underline' }}>
        {t(keys.newsletter.email.read_more)}
      </span>
      {!p.cancelled && (
        <span style={{ color: ACCENT, textDecoration: 'underline', marginLeft: 8 }}>
          {t(keys.newsletter.email.add_to_calendar)}
        </span>
      )}
    </div>
  );
}

const EMPTY: EventCardProps = {
  source_id: '',
  title: '',
  excerpt: '',
  image_url: '',
  url: '',
  ics_url: '',
  locale: '',
  starts_at: '1970-01-01T00:00:00Z',
  ends_at: '1970-01-01T00:00:00Z',
  all_day: false,
  start_date: null,
  end_date: null,
  timezone: 'UTC',
  attendance_mode: 'in_person',
  place: '',
  cancelled: false,
  snapshot_at: '',
};

/** The event card block; `available` is the integration's capability. */
export function eventCardBlock(
  available: boolean,
): ComponentConfig<EventCardProps, Pick<EventCardProps, 'source_id'>> {
  return {
    label: copy.event_card.label,
    fields: { source_id: cardField('event', available) },
    defaultProps: EMPTY,
    render: (props) => <EventCardView {...props} />,
  };
}
