import { InlineBanner } from '@simple-module-py/ui/components/InlineBanner';
import { AlertTriangle } from 'lucide-react';
import { keys, useT } from '../utils/i18n';

/**
 * Why a chosen ``stripe`` is running as ``manual`` (#200). The connection
 * screen says so too, but an operator on the subscriptions screen only saw
 * "Provider: manual" and had no reason to look there.
 */
export function ProviderFallbackBanner({ error }: { error: string }) {
  const { t } = useT();
  if (!error) return null;
  const c = keys.billing.subscriptions;
  return (
    <InlineBanner
      icon={AlertTriangle}
      tone="warning"
      title={t(c.fallback_title)}
      description={t(c.fallback_description, { error })}
    />
  );
}
