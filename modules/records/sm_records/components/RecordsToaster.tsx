import { Toaster } from '@simple-module-py/ui/components/ui/sonner';

/** `AdminLayout` (unlike `AuthenticatedLayout`) mounts no `<Toaster>`, so every
 *  `toast.success`/`toast.error` call in this module — including the error
 *  paths that have no other surface — was silently swallowed. `RecordsLayout`
 *  renders this once, inside `AdminLayout`, instead of patching the shared
 *  layout package. */
export function RecordsToaster() {
  return <Toaster richColors position="top-right" />;
}
