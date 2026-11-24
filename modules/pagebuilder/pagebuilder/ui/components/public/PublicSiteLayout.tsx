import { lazy, Suspense } from 'react';
import type { PublicShellProps } from './PublicShell';

// The shell's layout palette shares editor definitions. Keep that graph out
// of the package-root entry chunk; load it only when a sibling draws a site page.
const Shell = lazy(() =>
  import('./PublicShell').then(({ PublicShell }) => ({ default: PublicShell })),
);

export type PublicSiteLayoutProps = PublicShellProps;

export function PublicSiteLayout(props: PublicSiteLayoutProps) {
  return (
    <Suspense fallback={props.children}>
      <Shell {...props} />
    </Suspense>
  );
}
