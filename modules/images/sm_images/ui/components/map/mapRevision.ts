type Placed = { id: string; lat: number | null; lng: number | null };

/**
 * A revision of the points the loaded gallery images put on the map: their
 * ids and positions, order-free, unlocated images left out. It changes when a
 * located image appears, leaves, moves or is replaced by another - even at the
 * same counts - so the map knows to read its points again.
 */
export function mapRevision(items: Placed[]): string {
  return items
    .filter((i) => i.lat !== null && i.lng !== null)
    .map((i) => `${i.id}@${i.lat},${i.lng}`)
    .sort()
    .join(';');
}
