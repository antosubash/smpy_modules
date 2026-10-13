import { keys, translate } from './i18n';

/** "1 member" / "3 members" on an unlimited plan, "2 of 5 seats used" otherwise. */
export function seatsLabel(used: number, limit: number | null): string {
  if (limit === null) return translate(keys.billing.seats.members, { count: used });
  return translate(keys.billing.seats.used, { used, count: limit });
}
