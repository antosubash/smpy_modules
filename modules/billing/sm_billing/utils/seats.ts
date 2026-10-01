/** "1 member" / "3 members" on an unlimited plan, "2 of 5 seats used" otherwise. */
export function seatsLabel(used: number, limit: number | null): string {
  if (limit === null) return `${used} ${used === 1 ? 'member' : 'members'}`;
  return `${used} of ${limit} ${limit === 1 ? 'seat' : 'seats'} used`;
}
