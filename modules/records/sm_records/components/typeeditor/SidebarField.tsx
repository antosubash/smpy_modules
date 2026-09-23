import { useT } from '@simple-module-py/i18n';
import { Label } from '@simple-module-py/ui/components/ui/label';
import { Switch } from '@simple-module-py/ui/components/ui/switch';

import type { TenancyMode } from '../../utils/types';

const ID = 'type-editor-show-in-menu';

/**
 * The "Show in sidebar" toggle (per-type sidebar entries design contract):
 * opts this type into its own admin sidebar entry, alongside the "Records"
 * hub, so an editor can reach it in one click instead of going through the
 * hub table. Off by default for a new type — the hub link always exists, so
 * nothing is unreachable while this stays off.
 *
 * **Hidden in multi-tenant mode** (tenancy design §I): `MenuRegistry` is one
 * static list per process, evaluated before the request's tenant is known, so
 * multi mode never syncs a per-type entry at all — only the "All record
 * types" hub survives. The toggle would promise something the host can't do,
 * so it is replaced by a note saying why, rather than left on to be silently
 * inert. The API still accepts and stores `show_in_menu` unchanged (a host
 * that later drops back to single mode picks its value back up), so this
 * component still receives `showInMenu`/`onChange` — it just doesn't render
 * controls for them while `tenancyMode === 'multi'`.
 *
 * Split out of `TypeMetadataForm` for the 300-line cap, mirroring
 * `PublicField` — this is the only other type-level switch with its own
 * help text naming something the backend derives from other form state
 * (there, the public URL; here, the sidebar label).
 */
export function SidebarField({
  showInMenu,
  labelPlural,
  tenancyMode,
  onChange,
}: {
  showInMenu: boolean;
  /** The sidebar entry's own label, so the help text names what actually
   *  appears rather than describing it abstractly — mirrors the menu item's
   *  `label=rtype.label_plural`. */
  labelPlural: string;
  /** From the page's own `tenancy_mode` view prop; absent (an older fixture,
   *  a screen tenancy hasn't reached) renders the toggle as before. */
  tenancyMode?: TenancyMode;
  onChange: (showInMenu: boolean) => void;
}) {
  const { t } = useT();
  if (tenancyMode === 'multi') {
    return (
      <p
        className="text-sm text-muted-foreground sm:col-span-2"
        data-testid="records-show-in-menu-multi-note"
      >
        {t('records.type_editor.show_in_menu_multi_note', {
          defaultValue:
            'Sidebar entries are per-install, not per-tenant, so this host shows only the "Records" hub. Every type stays reachable from there.',
        })}
      </p>
    );
  }
  return (
    <>
      <div className="flex items-center gap-2 sm:col-span-2">
        <Switch
          id={ID}
          checked={showInMenu}
          onCheckedChange={(checked) => onChange(checked === true)}
        />
        <Label htmlFor={ID} className="font-normal">
          {t('records.type_editor.show_in_menu', { defaultValue: 'Show in sidebar' })}
        </Label>
      </div>
      <p className="-mt-2 text-sm text-muted-foreground sm:col-span-2">
        {t('records.type_editor.show_in_menu_help', {
          label_plural: labelPlural,
          defaultValue:
            'Adds {label_plural} to the admin sidebar, in its own Records group right after Content.',
        })}
      </p>
    </>
  );
}
