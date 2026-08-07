/** Responsive-image support for picker-backed widgets (issue #15).
 *
 * The media library generates WebP variants at upload, but widgets that
 * store a bare `imageUrl` string shipped the full-size original to every
 * viewport. These helpers let a widget persist the variant srcset next to
 * the URL the same way the Image block does: `resolveImageSrcset` runs as
 * Puck's `resolveData` when the picked URL changes, and the value lands in
 * block data so the public render needs no lookup at all. Old content
 * without the prop renders exactly as before.
 */

import { buildSrcset, lookupAsset } from '../../../utils/mediaApi';

/** Full-bleed imagery (background heroes, banners). */
export const SIZES_FULL = '100vw';

/** Half-width split layouts (side hero, media object) — full width stacked. */
export const SIZES_HALF = '(min-width: 1024px) 50vw, 100vw';

/** Field for the persisted srcset — visible so an author can override it. */
export const imageSrcsetField = {
  type: 'textarea',
  label: 'Image srcset (auto-filled from the media library)',
} as const;

/** Spreadable `<img>` attributes; nothing when no srcset is recorded. */
export function srcsetAttrs(
  srcset: string | undefined,
  sizes: string,
): { srcSet: string; sizes: string } | Record<string, never> {
  return srcset ? { srcSet: srcset, sizes } : {};
}

type SrcsetProps = { imageUrl: string; imageSrcset?: string };

/** `resolveData` for any widget with `imageUrl` + `imageSrcset` props.
 *  `changed` is typed to just the key read here — Puck's own param type
 *  (which also carries `id: string`) stays assignable. */
export async function resolveImageSrcset<P extends SrcsetProps>(
  { props }: { props: P },
  { changed }: { changed: { imageUrl?: unknown } },
): Promise<{ props: P }> {
  if (!changed.imageUrl) return { props };
  if (!props.imageUrl) return { props: { ...props, imageSrcset: '' } };
  let asset: Awaited<ReturnType<typeof lookupAsset>>;
  try {
    asset = await lookupAsset(props.imageUrl);
  } catch {
    // Network failure mid-edit shouldn't break the editor — keep the picked
    // URL and let the image serve without variants.
    return { props };
  }
  if (!asset) return { props };
  return { props: { ...props, imageSrcset: buildSrcset(asset) } };
}
