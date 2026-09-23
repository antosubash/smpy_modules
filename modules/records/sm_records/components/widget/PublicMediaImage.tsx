import { useState } from 'react';

/** A `media` value on the public page, when `publicMediaSrc` produced a URL
 *  for it. The id alone does not say whether the file is an image, and the
 *  anonymous API cannot ask the library, so a file that turns out not to be
 *  one — or a URL that refuses the visitor after all — removes itself on
 *  `onError` rather than leaving a broken-image icon on the site. */
export function PublicMediaImage({ src, alt }: { src: string; alt: string }) {
  const [failed, setFailed] = useState(false);
  if (failed) return null;
  return (
    <img
      src={src}
      alt={alt}
      loading="lazy"
      className="max-h-40 max-w-full rounded object-contain"
      data-testid="records-widget-media"
      onError={() => setFailed(true)}
    />
  );
}
