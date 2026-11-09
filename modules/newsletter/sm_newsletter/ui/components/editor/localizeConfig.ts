/**
 * Resolve the editor's Puck config labels through the locale catalogue.
 *
 * The block configs are built outside React (`buildConfig`), so they cannot
 * call `useT()` where their labels are written. They hold the catalogue *key*
 * instead, and this turns a config full of keys into one in the viewer's
 * language, once, inside the screen that mounts Puck — pagebuilder's and
 * news' pattern.
 *
 * Only chrome is touched: palette labels, field labels (including the ones in
 * an `array` or `object` field), select and radio option labels, and category
 * titles. `defaultProps` are left alone: they are the seed *content* a block
 * is inserted with, saved into the email the moment it is.
 */

import type { Translate } from '../../utils/i18n';

/** The parts of a Puck config this walks, structurally — Puck's own generics
 *  would have to be threaded through every helper to say nothing extra. */
interface LabelledOption {
  label?: string;
}

interface LabelledField {
  label?: string;
  /** A select's or radio's choices. A `richtext` field's `options` is an
   *  object of editor extensions instead, and has no labels. */
  options?: LabelledOption[] | Record<string, unknown>;
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
  root?: LabelledComponent;
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
  // A `custom` field (the media and card pickers) has no label here: it
  // renders its own `FieldLabel` and translates there.
  const next: LabelledField = { ...field };
  if (field.label) next.label = t(field.label);
  if (Array.isArray(field.options)) {
    next.options = field.options.map((option) =>
      option.label ? { ...option, label: t(option.label) } : option,
    );
  }
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

/** The same config with every label resolved; the generic is preserved so
 *  Puck still sees the caller's component-props map. */
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
