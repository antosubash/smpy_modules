import { Label } from '@simple-module-py/ui/components/ui/label';
import { Switch } from '@simple-module-py/ui/components/ui/switch';
import { keys, useT } from '../../utils/i18n';

const ID = 'type-editor-show-in-menu';

/**
 * The "Show in sidebar" toggle (per-type sidebar entries design contract):
 * opts this type into its own admin sidebar entry, alongside the "Records"
 * hub, so an editor can reach it in one click instead of going through the
 * hub table. Off by default for a new type — the hub link always exists, so
 * nothing is unreachable while this stays off.
 *
 * Shown on multi-tenant hosts too: the entries come from a per-request menu
 * provider that reads the request's own tenant's types (framework 0.0.36,
 * upstream #340), so each organisation's sidebar lists its own. Before that
 * this was replaced by a note on such hosts, because the process-wide menu
 * registry could not be per tenant.
 *
 * Split out of `TypeMetadataForm` for the 300-line cap, mirroring
 * `PublicField` — this is the only other type-level switch with its own
 * help text naming something the backend derives from other form state
 * (there, the public URL; here, the sidebar label).
 */
export function SidebarField({
  showInMenu,
  labelPlural,
  onChange,
}: {
  showInMenu: boolean;
  /** The sidebar entry's own label, so the help text names what actually
   *  appears rather than describing it abstractly — mirrors the menu item's
   *  `label=rtype.label_plural`. */
  labelPlural: string;
  onChange: (showInMenu: boolean) => void;
}) {
  const { t } = useT();
  return (
    <>
      <div className="flex items-center gap-2 sm:col-span-2">
        <Switch
          id={ID}
          checked={showInMenu}
          onCheckedChange={(checked) => onChange(checked === true)}
        />
        <Label htmlFor={ID} className="font-normal">
          {t(keys.records.type_editor.show_in_menu)}
        </Label>
      </div>
      <p className="-mt-2 break-words text-sm text-muted-foreground sm:col-span-2">
        {t(keys.records.type_editor.show_in_menu_help, {
          label_plural: labelPlural,
        })}
      </p>
    </>
  );
}
