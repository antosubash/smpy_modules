import { AdminLayout } from '@simple-module-py/ui/layouts/AdminLayout';
import type { ReactNode } from 'react';

/** Persistent layout for the four Records pages (`Page.layout = [RecordsLayout]`,
 *  the Inertia v3 array form). `AdminLayout` mounts the `<Toaster>` itself
 *  since ui 0.0.36; a second one here would show every toast twice. */
export function RecordsLayout({ children }: { children?: ReactNode }) {
  return <AdminLayout>{children}</AdminLayout>;
}
