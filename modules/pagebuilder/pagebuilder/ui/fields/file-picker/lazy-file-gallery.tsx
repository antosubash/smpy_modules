import { type ComponentProps, lazy, Suspense } from 'react';

const Gallery = lazy(() => import('./file-gallery').then((m) => ({ default: m.FileGallery })));

/** Keep the optional picker out of eagerly registered blocks' entry chunks. */
export function FileGallery(props: ComponentProps<typeof Gallery>) {
  // Pickers stay mounted while closed; wait for an open before requesting the chunk.
  if (!props.open) return null;
  return (
    <Suspense fallback={null}>
      <Gallery {...props} />
    </Suspense>
  );
}
