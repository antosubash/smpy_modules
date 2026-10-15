import type { ReactNode } from 'react';

/**
 * An image segment (`![alt](src)`, its src already vetted by `splitLinks`) →
 * `<img>` (#66). Inline, so a line of logos sits in a row and a paragraph of
 * its own stacks; `max-w-full` keeps a large one inside the column.
 */
export function renderInlineImage(image: { alt: string; src: string }, key: string): ReactNode {
  return (
    <img
      key={key}
      src={image.src}
      alt={image.alt}
      loading="lazy"
      className="inline-block h-auto max-w-full align-middle"
    />
  );
}
