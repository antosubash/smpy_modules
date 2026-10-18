/** Locale switcher and auth-aware CTA for the SiteHeader widget. */

import { usePage } from '@inertiajs/react';
import {
  LocaleSwitcher,
  useHasMultipleLocales,
} from '@simple-module-py/ui/components/LocaleSwitcher';

type AuthSharedProps = {
  auth?: { isAuthenticated?: boolean } | null;
};

/**
 * Whether the visitor has a session, from the `auth` shared prop the framework
 * layouts read. The header only mounts inside an Inertia page; the guard keeps
 * a bare render (a unit test, a static preview) on the anonymous branch rather
 * than throwing, so a header that never set the new props renders as before.
 */
export function useIsSignedIn(): boolean {
  try {
    // biome-ignore lint/correctness/useHookAtTopLevel: usePage throws outside Inertia, after reading its context, so the hook order is unchanged
    return Boolean(usePage<AuthSharedProps>().props.auth?.isAuthenticated);
  } catch {
    return false;
  }
}

/** The CTA the visitor should see: the signed-in variant only when it is filled in. */
export function resolveCta(
  signedIn: boolean,
  cta: { label: string; href: string },
  signedInCta: { label?: string; href?: string },
): { label: string; href: string } {
  if (signedIn && signedInCta.label) {
    return { label: signedInCta.label, href: signedInCta.href || cta.href };
  }
  return cta;
}

/**
 * The shared switcher, hidden on a single-locale install where it would be an
 * inert pill. It switches the UI locale; it does not jump to a translated
 * page, because the shared control has no hook for a per-page target.
 */
export function HeaderLocaleSwitcher({ show }: { show: boolean }) {
  const multiple = useHasMultipleLocales();
  if (!show || !multiple) return null;
  return (
    <div className="flex items-center">
      <LocaleSwitcher className="min-h-11 min-w-11" />
    </div>
  );
}
