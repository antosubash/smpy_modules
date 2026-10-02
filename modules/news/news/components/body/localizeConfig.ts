/**
 * Resolve a Puck config's labels through the locale catalogue.
 *
 * The block configs are module-scope constants — Puck reads them, and
 * `puck-blocks.ts` hands one to a neighbouring module before the app has
 * rendered anything — so they cannot call `useT()` where their labels are
 * written. What they hold instead is the *key*, and this turns a config full
 * of keys into a config full of the viewer's language, once, inside the screen
 * that mounts Puck.
 *
 * Only chrome is touched: a component's palette label, its field labels and a
 * select's option labels, plus the category titles. `defaultProps` are
 * deliberately left alone — they are the seed *content* a block is inserted
 * with and are then saved into the document, so translating them at render
 * would rewrite what a reader is being served in whatever language the reader
 * happens to be browsing in.
 */

import type { Translate } from '../../utils/i18n';

/** The parts of a Puck config this walks. Structural, because Puck's own
 *  generics are keyed on the component-props map and would have to be
 *  threaded through every helper here to say nothing extra. */
interface LabelledOption {
  label?: string;
}

interface LabelledField {
  label?: string;
  options?: LabelledOption[];
}

interface LabelledComponent {
  label?: string;
  fields?: Record<string, LabelledField>;
}

interface LabelledConfig {
  categories?: Record<string, { title?: string }>;
  components?: Record<string, LabelledComponent>;
}

/** An editor viewport switcher entry — `label` is what the toolbar shows. */
interface LabelledViewport {
  label?: string;
}

function mapValues<V, R>(
  source: Record<string, V> | undefined,
  fn: (value: V) => R,
): Record<string, R> | undefined {
  if (!source) return source;
  const out: Record<string, R> = {};
  for (const [name, value] of Object.entries(source)) out[name] = fn(value);
  return out;
}

function localizeField(field: LabelledField, t: Translate): LabelledField {
  // A `custom` field has no label of its own — it renders its own
  // `FieldLabel`, and translates there.
  const next: LabelledField = { ...field };
  if (field.label) next.label = t(field.label);
  if (field.options) {
    next.options = field.options.map((option) =>
      option.label ? { ...option, label: t(option.label) } : option,
    );
  }
  return next;
}

/** The same config with every label resolved. The generic is the caller's own
 *  config type, preserved so Puck still sees its component-props map. */
export function localizeConfig<T>(config: T, t: Translate): T {
  const source = config as LabelledConfig;
  const localized: LabelledConfig = {
    ...source,
    categories: mapValues(source.categories, (category) =>
      category.title ? { ...category, title: t(category.title) } : category,
    ),
    components: mapValues(source.components, (component) => ({
      ...component,
      ...(component.label ? { label: t(component.label) } : {}),
      fields: mapValues(component.fields, (field) => localizeField(field, t)),
    })),
  };
  return localized as T;
}

/** The viewport switcher's labels, resolved the same way. */
export function localizeViewports<T extends LabelledViewport>(viewports: T[], t: Translate): T[] {
  return viewports.map((viewport) =>
    viewport.label ? { ...viewport, label: t(viewport.label) } : viewport,
  );
}
