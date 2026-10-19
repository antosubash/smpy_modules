import { NavIcon } from '@simple-module-py/ui/components/NavIcon';
import { Input } from '@simple-module-py/ui/components/ui/input';
import { Label } from '@simple-module-py/ui/components/ui/label';
import { keys, useT } from '../../utils/i18n';

import { DEFAULT_TYPE_ICON, isKnownNavIcon, NAV_ICON_EXAMPLES, navIconName } from './navIcons';

const ID = 'type-editor-icon';

/**
 * The type's icon, with the icon itself next to the box.
 *
 * Split out of `TypeMetadataForm` for the 300-line cap, mirroring
 * `PublicField`/`SidebarField`. It earns its own file for the same reason
 * they do: the help text has to name something the browser can't derive —
 * here, that `NavIcon` draws from a fixed allowlist and not from all of
 * lucide-react. The old help promised any lucide name, so `flask-conical`
 * was typed, accepted, saved, and then drew nothing at all in the hub row
 * and the sidebar (UX verification, rough edge 6). The preview answers that
 * before the save: it shows exactly what those places will draw, which for
 * an unknown name is this module's default icon.
 */
export function IconField({
  value,
  error,
  onChange,
}: {
  value: string;
  error?: string;
  onChange: (icon: string) => void;
}) {
  const { t } = useT();
  const unknown = !!value && !isKnownNavIcon(value);

  return (
    <div className="grid gap-1.5">
      <Label htmlFor={ID}>{t(keys.records.type_editor.icon)}</Label>
      <div className="flex items-center gap-2">
        <Input
          id={ID}
          className="min-w-0 flex-1"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={t(keys.records.type_editor.icon_placeholder)}
          aria-invalid={!!error}
        />
        <span
          role="img"
          aria-label={t(keys.records.type_editor.icon_preview)}
          data-testid="records-type-icon-preview"
          data-icon={navIconName(value)}
          className="flex size-9 shrink-0 items-center justify-center rounded-md border text-muted-foreground"
        >
          <NavIcon name={navIconName(value)} />
        </span>
      </div>
      <p className="text-sm text-muted-foreground">
        {t(keys.records.type_editor.icon_help, {
          examples: NAV_ICON_EXAMPLES.join(', '),
        })}
      </p>
      {unknown && (
        <p className="text-sm text-muted-foreground" data-testid="records-type-icon-unknown">
          {t(keys.records.type_editor.icon_unknown, {
            name: value,
            fallback: DEFAULT_TYPE_ICON,
          })}
        </p>
      )}
      {error && <p className="text-sm text-destructive">{error}</p>}
    </div>
  );
}
