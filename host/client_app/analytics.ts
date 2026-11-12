import { router } from '@inertiajs/react';
import { startHostAnalytics } from '@simple-module-py/analytics';

export function startAnalytics(): () => void {
  return startHostAnalytics((navigate) =>
    router.on('navigate', (event) => {
      if (event.detail.type !== 'initial') navigate(event.detail.page.url);
    }),
  );
}
