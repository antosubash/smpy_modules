import { AdminLayout } from '@simple-module-py/ui/layouts/AdminLayout';
import type { ReactNode } from 'react';

import { RecordsToaster } from './RecordsToaster';

/** Persistent layout for the four Records pages (`Page.layout = [RecordsLayout]`,
 *  the Inertia v3 array form): `AdminLayout` plus the `<Toaster>` it lacks. */
export function RecordsLayout({ children }: { children?: ReactNode }) {
  return (
    <AdminLayout>
      {children}
      <RecordsToaster />
    </AdminLayout>
  );
}
