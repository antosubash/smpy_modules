import { Link } from '@inertiajs/react';

/** The type's label, as a link back to its record list (U14) — the editor
 *  used to show this as plain text, so the only way back was "Cancel" or
 *  browser Back. Split into its own file so `RecordEditor.tsx` calls it in
 *  one line (300-line cap). */
export function RecordEditorTypeLink({ label, backHref }: { label: string; backHref: string }) {
  return (
    <p className="-mt-3 mb-4 text-sm">
      <Link
        href={backHref}
        className="text-primary hover:underline"
        data-testid="records-editor-type-link"
      >
        {label}
      </Link>
    </p>
  );
}
