/**
 * Which icon names actually draw something.
 *
 * `ModuleMeta`-style help used to promise "the name of a lucide-react icon",
 * but the framework's `NavIcon` (`@simple-module-py/ui/components/NavIcon`)
 * is not a lucide passthrough — it is a fixed allowlist, and a name outside
 * it renders an empty `<span>` of the same size. So `flask-conical` is a
 * perfectly real lucide icon that showed as a blank gap in the hub row and
 * in this type's sidebar entry, with nothing on the editor saying why (UX
 * verification, rough edge 6).
 *
 * The list below mirrors that component's `ICON_MAP` keys by hand: the
 * package exports the `NavIconName` *type* but not the map, so there is no
 * runtime set to import. Nothing breaks if the framework adds a name we
 * don't list — the editor then calls it unknown and offers the default,
 * while `NavIcon` still draws whatever the operator typed. Verified against
 * `node_modules/@simple-module-py/ui/src/components/NavIcon.tsx`.
 */

/** This module's own icon, and the one the menu falls back to server-side
 *  (`sm_records.constants.MENU_ICON`). */
export const DEFAULT_TYPE_ICON = 'database';

export const NAV_ICON_NAMES: readonly string[] = [
  'activity',
  'alert-circle',
  'archive',
  'bar-chart-3',
  'bell',
  'bookmark',
  'briefcase',
  'calendar',
  'camera',
  'check',
  'chevron-down',
  'chevron-right',
  'clock',
  'cloud',
  'code',
  'cog',
  'copy',
  'cpu',
  'credit-card',
  'database',
  'download',
  'edit',
  'eye',
  'eye-off',
  'file',
  'file-text',
  'files',
  'filter',
  'flag',
  'folder',
  'gift',
  'globe',
  'heart',
  'home',
  'image',
  'inbox',
  'info',
  'key',
  'layers',
  'layout',
  'link',
  'list',
  'lock',
  'log-out',
  'mail',
  'map',
  'menu',
  'message-square',
  'package',
  'pencil',
  'plus',
  'refresh-cw',
  'save',
  'search',
  'send',
  'server',
  'settings',
  'share',
  'shield',
  'shield-check',
  'shopping-bag',
  'shopping-cart',
  'sparkles',
  'star',
  'tag',
  'terminal',
  'trash',
  'upload',
  'user',
  'users',
  'x',
  'zap',
];

const KNOWN = new Set(NAV_ICON_NAMES);

/** A handful of the allowlist, named in the Icon field's help text so the
 *  reader has somewhere to start instead of a list of seventy. */
export const NAV_ICON_EXAMPLES = ['database', 'folder', 'users', 'tag', 'package', 'file-text'];

export function isKnownNavIcon(name: string | null | undefined): boolean {
  return !!name && KNOWN.has(name);
}

/** The name to hand `NavIcon`: what was asked for when it draws, and this
 *  module's default when it doesn't — so an unknown name is a wrong icon
 *  rather than a hole where an icon should be. */
export function navIconName(name: string | null | undefined): string {
  return isKnownNavIcon(name) ? (name as string) : DEFAULT_TYPE_ICON;
}
