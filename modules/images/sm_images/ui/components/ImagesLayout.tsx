import { AdminLayout } from '@simple-module-py/ui/layouts/AdminLayout';
import type { ReactNode } from 'react';

/** Persistent layout for the Images pages (`Page.layout = [ImagesLayout]`).
 *  `AdminLayout` mounts the `<Toaster>` itself; a second one would show every
 *  toast twice. */
export function ImagesLayout({ children }: { children?: ReactNode }) {
  return <AdminLayout>{children}</AdminLayout>;
}
