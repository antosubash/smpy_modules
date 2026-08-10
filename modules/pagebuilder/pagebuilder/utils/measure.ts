/** The measure shared by the root-level blocks.
 *
 * A page built from the section widgets has to set its root to `full`: those
 * widgets each bring their own `container`, and the `contained` root's
 * `max-w-4xl` column crushes them. That is the right call for a page of
 * sections, but it leaves the *primitives* — Image, Divider — with nothing
 * capping them at all, because unlike a widget they render no container of
 * their own. Dropped straight onto such a page they run the full width of the
 * viewport and sit flush against the window edge, while every widget above and
 * below them stays inside the article column.
 *
 * So the primitives carry their own measure. The scale is the prose one
 * (`max-w-3xl` and friends) rather than Container's `max-w-screen-*`: this caps
 * content *inside* an article, and the article measure everywhere else in this
 * module is `max-w-3xl`/`max-w-4xl`, not a viewport breakpoint.
 *
 * `full` is the default everywhere it is used, and is a true no-op — it is the
 * class form of the `max-width: 100%` these blocks already had — so adding the
 * field moves no page that was published before it existed.
 */

import { cn } from './widgetUtils';

export type Measure = '2xl' | '3xl' | '4xl' | '5xl' | 'full';

/** Inspector options, so two blocks cannot drift into offering different ones. */
export const MEASURE_OPTIONS: { label: string; value: Measure }[] = [
  { label: '2XL', value: '2xl' },
  { label: '3XL (article measure)', value: '3xl' },
  { label: '4XL', value: '4xl' },
  { label: '5XL', value: '5xl' },
  { label: 'Full', value: 'full' },
];

// Spelled out rather than built as `max-w-${size}`: Tailwind only emits classes
// it can see written down, and an interpolated name reaches it as nothing at
// all.
const MAX_WIDTH_CLASS: Record<Measure, string> = {
  '2xl': 'max-w-2xl',
  '3xl': 'max-w-3xl',
  '4xl': 'max-w-4xl',
  '5xl': 'max-w-5xl',
  full: 'max-w-full',
};

/** The cap, plus centring once there is room to centre in.
 *
 * `mx-auto` is withheld at `full` on purpose: a full-width image has no slack,
 * and adding it unconditionally would pull every already-published image that
 * is narrower than its column into the middle of it.
 */
export function measureClass(maxWidth: Measure): string {
  return cn(MAX_WIDTH_CLASS[maxWidth], maxWidth !== 'full' && 'mx-auto');
}
