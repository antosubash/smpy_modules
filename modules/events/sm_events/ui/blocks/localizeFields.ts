/** Resolve a block's catalogue keys to text, through nested fields.
 *
 *  Pagebuilder's `localizeConfig` resolves a block's *static* fields when the editor mounts Puck.
 *  The fields a block builds in `resolveFields` (the calendar and category selects, filled once the
 *  anonymous route answers) are made after that, so events resolves them itself, with the same
 *  reach: every `label`, every `options[].label`, and into `arrayFields` and `objectFields`.
 *
 *  A pure deep copy. A label that is already text (a calendar's name) is not a key, and the
 *  translator hands an unknown key back as it came. */

import type { Translate } from '../utils/i18n';

type Node = Record<string, unknown>;

function field(value: unknown, tr: Translate): unknown {
  if (!value || typeof value !== 'object') return value;
  const source = value as Node;
  const out: Node = { ...source };
  if (typeof source.label === 'string') out.label = tr(source.label);
  if (Array.isArray(source.options)) {
    out.options = source.options.map((option) =>
      option && typeof option === 'object' && typeof (option as Node).label === 'string'
        ? { ...(option as Node), label: tr((option as Node).label as string) }
        : option,
    );
  }
  for (const nested of ['arrayFields', 'objectFields'] as const) {
    const children = source[nested];
    if (children && typeof children === 'object')
      out[nested] = localizeFields(children as Node, tr);
  }
  return out;
}

export function localizeFields<F extends Node>(fields: F, tr: Translate): F {
  const out: Node = {};
  for (const [name, value] of Object.entries(fields)) out[name] = field(value, tr);
  return out as F;
}
