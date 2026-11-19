import type { Lead } from '../utils/api-reminders';
import { keys, type Translate } from '../utils/i18n';

const LONG: Record<number, string> = {
  15: keys.events.reminders.leads.m15,
  60: keys.events.reminders.leads.m60,
  1440: keys.events.reminders.leads.m1440,
  10080: keys.events.reminders.leads.m10080,
};
const SHORT: Record<number, string> = {
  15: keys.events.reminders.leads.s15,
  60: keys.events.reminders.leads.s60,
  1440: keys.events.reminders.leads.s1440,
  10080: keys.events.reminders.leads.s10080,
};

/** "1 hour before". A lead outside the closed set (never stored by a write) reads as minutes. */
export const leadLabel = (t: Translate, lead: Lead): string =>
  LONG[lead] ? t(LONG[lead]) : `${lead} min`;

/** "15 min, 1 day": the summary on the control. */
export const leadsSummary = (t: Translate, leads: Lead[]): string =>
  [...leads]
    .sort((a, b) => a - b)
    .map((lead) => (SHORT[lead] ? t(SHORT[lead]) : `${lead} min`))
    .join(', ');
