/**
 * Resolve a Puck config's labels through the locale catalogue.
 *
 * The block configs are module-scope constants — Puck reads them, and
 * `blockRegistry.ts` takes one from a neighbouring module before the app has
 * rendered anything — so they cannot call `useT()` where their labels are
 * written. What they hold instead is the *key*, and this turns a config full
 * of keys into a config full of the viewer's language, once, inside the screen
 * that mounts Puck.
 *
 * Only chrome is touched: a component's palette label, its field labels
 * (including the ones nested in an `array` or `object` field) and a select's
 * option labels, plus the category titles. `defaultProps` are deliberately
 * left alone — they are the seed *content* a block is inserted with and are
 * then saved into the document, so translating them at render would rewrite
 * what a visitor is being served in whatever language the *author* happened to
 * be working in.
 */

import type { Translate } from '../utils/i18n';

/** The parts of a Puck config this walks. Structural, because Puck's own
 *  generics are keyed on the component-props map and would have to be
 *  threaded through every helper here to say nothing extra. */
interface LabelledOption {
  label?: string;
}

interface LabelledField {
  label?: string;
  options?: LabelledOption[];
  arrayFields?: Record<string, LabelledField>;
  objectFields?: Record<string, LabelledField>;
}

interface LabelledComponent {
  label?: string;
  fields?: Record<string, LabelledField>;
}

interface LabelledConfig {
  categories?: Record<string, { title?: string }>;
  components?: Record<string, LabelledComponent>;
  /** The page's own fields — width, title — which Puck shows under "Page". */
  root?: LabelledComponent;
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
  // An `array` or `object` field carries a second level of labels, which the
  // editor shows once a row is expanded. Missing them left half of every
  // repeater's chrome untranslated.
  if (field.arrayFields) {
    next.arrayFields = mapValues(field.arrayFields, (inner) => localizeField(inner, t));
  }
  if (field.objectFields) {
    next.objectFields = mapValues(field.objectFields, (inner) => localizeField(inner, t));
  }
  return next;
}

function localizeComponent(component: LabelledComponent, t: Translate): LabelledComponent {
  return {
    ...component,
    ...(component.label ? { label: t(component.label) } : {}),
    fields: mapValues(component.fields, (field) => localizeField(field, t)),
  };
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
    components: mapValues(source.components, (component) => localizeComponent(component, t)),
    ...(source.root ? { root: localizeComponent(source.root, t) } : {}),
  };
  return localized as T;
}

/** The viewport switcher's labels, resolved the same way. */
export function localizeViewports<T extends LabelledViewport>(viewports: T[], t: Translate): T[] {
  return viewports.map((viewport) =>
    viewport.label ? { ...viewport, label: t(viewport.label) } : viewport,
  );
}
