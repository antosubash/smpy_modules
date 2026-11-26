import { router } from '@inertiajs/react';
import { type HostAnalyticsPage, startHostAnalytics } from '@simple-module-py/analytics';

type Page = { url: string; component?: string; props?: Record<string, unknown> };

// The tenant goes with every page: a switch on the same origin (the tenants
// module reloads the same URL) must not reuse the previous tenant's properties.
function trackingPage(page: Page): HostAnalyticsPage {
  const tenant = (page.props as { tenant?: { active?: { id?: string | null } | null } } | undefined)
    ?.tenant;
  return { url: page.url, component: page.component, tenantId: tenant?.active?.id ?? null };
}

export function startAnalytics(initialPage: Page): () => void {
  return startHostAnalytics(
    (navigate) =>
      router.on('navigate', (event) => {
        if (event.detail.type !== 'initial') navigate(trackingPage(event.detail.page));
      }),
    trackingPage(initialPage),
  );
}
