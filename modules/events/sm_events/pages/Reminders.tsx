import { Head } from '@inertiajs/react';
import { PageShell } from '@simple-module-py/ui/components/PageShell';
import { AuthenticatedLayout } from '@simple-module-py/ui/layouts/AuthenticatedLayout';
import { DeliveryCard } from '../ui/components/reminders/DeliveryCard';
import { MyReminders } from '../ui/components/reminders/MyReminders';
import { UnavailableNotice } from '../ui/components/reminders/UnavailableNotice';
import { keys, useT } from '../ui/utils/i18n';

export default function Reminders({
  is_manager,
  settings_url,
}: {
  is_manager: boolean;
  settings_url: string;
}) {
  const { t } = useT();
  const copy = keys.events.reminders.page;
  return (
    <>
      <Head title={t(copy.title)} />
      <PageShell title={t(copy.title)} description={t(copy.subtitle)}>
        <div className="space-y-8">
          <UnavailableNotice />
          <MyReminders />
          {is_manager ? <DeliveryCard settingsUrl={settings_url} /> : null}
        </div>
      </PageShell>
    </>
  );
}
Reminders.layout = [AuthenticatedLayout];
