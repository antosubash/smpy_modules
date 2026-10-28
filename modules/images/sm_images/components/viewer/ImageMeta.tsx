import { keys, useT } from '../../utils/i18n';
import type { ImageItem } from '../../utils/types';

function bytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KiB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MiB`;
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[8rem_1fr] gap-2 py-1.5 text-sm">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="min-w-0 break-words">{children}</dd>
    </div>
  );
}

/** Metadata, then the image's `properties` as a generic key/value view. A step's
 *  own result view arrives with the review screens (Task 14). */
export function ImageMeta({ image }: { image: ImageItem }) {
  const { t, locale } = useT();
  const when = (iso: string | null) => (iso ? new Date(iso).toLocaleString(locale) : '-');
  const camera = [image.camera_make, image.camera_model].filter(Boolean).join(' ');
  const props = Object.entries(image.properties ?? {});

  return (
    <div className="space-y-6">
      <section aria-labelledby="images-meta-title">
        <h2 id="images-meta-title" className="mb-2 text-lg font-semibold">
          {t(keys.images.viewer.metadata)}
        </h2>
        <dl className="divide-y" data-testid="images-meta">
          <Row label={t(keys.images.viewer.filename)}>{image.filename}</Row>
          <Row label={t(keys.images.viewer.dimensions)}>
            {image.width && image.height ? `${image.width} × ${image.height}` : '-'}
          </Row>
          <Row label={t(keys.images.viewer.size)}>{bytes(image.size_bytes)}</Row>
          <Row label={t(keys.images.viewer.type)}>{image.content_type}</Row>
          <Row label={t(keys.images.viewer.captured)}>{when(image.captured_at)}</Row>
          <Row label={t(keys.images.viewer.camera)}>{camera || '-'}</Row>
          <Row label={t(keys.images.viewer.location)}>
            {image.lat !== null && image.lng !== null
              ? `${image.lat.toFixed(5)}, ${image.lng.toFixed(5)}`
              : t(keys.images.viewer.location_none)}
          </Row>
          <Row label={t(keys.images.viewer.uploaded)}>{when(image.created_at)}</Row>
        </dl>
      </section>
      <section aria-labelledby="images-results-title">
        <h2 id="images-results-title" className="mb-2 text-lg font-semibold">
          {t(keys.images.viewer.results)}
        </h2>
        {props.length === 0 ? (
          <p className="text-sm text-muted-foreground">{t(keys.images.viewer.no_results)}</p>
        ) : (
          <dl className="divide-y" data-testid="images-results">
            {props.map(([name, value]) => (
              <Row key={name} label={name}>
                {typeof value === 'string' ? value : JSON.stringify(value)}
              </Row>
            ))}
          </dl>
        )}
      </section>
    </div>
  );
}
