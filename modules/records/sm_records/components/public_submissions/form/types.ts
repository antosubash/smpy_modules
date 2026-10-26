/**
 * The `RecordForm` block's props (#101, design §8) — presentation only.
 *
 * Page JSON ships to every visitor, so nothing the server trusts lives here:
 * which fields a visitor may fill, their validation, the consent text and who
 * is notified all live on the record type. The block names the type and words
 * the form for this page — a German page over an English-labelled type gives
 * its fields German labels through `labels`.
 */

/** A per-page label (and help) for one of the type's public fields. A list
 *  rather than a map because that is what Puck can edit. */
export type LabelOverride = { field: string; label: string; help: string };

export type RecordFormProps = {
  typeKey: string;
  title: string;
  intro: string;
  submitLabel: string;
  successTitle: string;
  successBody: string;
  labels: LabelOverride[];
  /** `form` or `subscription`, written by the editor's `resolveData` — a
   *  hint for the editor only; the live definition is what renders. */
  kindHint: string;
};
