import { Head, usePage } from '@inertiajs/react';
import { PageShell } from '@simple-module-py/ui/components/PageShell';
import { Skeleton } from '@simple-module-py/ui/components/ui/skeleton';
import { AuthenticatedLayout } from '@simple-module-py/ui/layouts/AuthenticatedLayout';
import type { SharedProps } from '@simple-module-py/ui/types';
import { useEffect, useState } from 'react';

import { SettingsForm } from '../ui/components/settings/SettingsForm';
import { api, errorMessage } from '../ui/utils/api';
import { keys, useT } from '../ui/utils/i18n';
import type { SettingsOut } from '../ui/utils/types';

interface SettingsProps {
  can_write?: boolean;
}

/** The newsletter settings screen. Reads need `newsletter.manage`; `can_write` is
 *  whether the viewer also holds `settings.edit`. */
export default function Settings() {
  const { t } = useT();
  const copy = keys.newsletter.settings;
  const props = usePage<{ props: SharedProps & SettingsProps }>().props as unknown as SharedProps &
    SettingsProps;
  const [settings, setSettings] = useState<SettingsOut | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let current = true;
    api
      .getSettings()
      .then((s) => current && setSettings(s))
      .catch((e) => current && setError(errorMessage(e, t)));
    return () => {
      current = false;
    };
  }, [t]);

  return (
    <PageShell title={t(copy.title)} description={t(copy.description)}>
      <Head title={t(copy.title)} />
      {error && <p className="text-sm text-destructive">{error}</p>}
      {!error && !settings && (
        <div role="status" aria-label={t(copy.loading)}>
          <Skeleton className="h-64 w-full max-w-3xl" />
        </div>
      )}
      {settings && <SettingsForm initial={settings} canWrite={props.can_write === true} />}
    </PageShell>
  );
}

Settings.layout = [AuthenticatedLayout];
