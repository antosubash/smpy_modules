import { Label } from '@simple-module-py/ui/components/ui/label';
import { Textarea } from '@simple-module-py/ui/components/ui/textarea';

/**
 * A raw-JSON textarea with a label, help text, and an inline parse error.
 *
 * Deliberately dumb: it holds the *text* the person is typing, not the
 * parsed value, so an in-progress edit that is momentarily invalid JSON
 * (an open brace, a trailing comma) never gets clobbered mid-keystroke. The
 * caller owns parsing — on save, not on every change — and passes back the
 * error message to show.
 */
export function JsonField({
  id,
  label,
  helpText,
  value,
  onChange,
  error,
  rows = 12,
  disabled = false,
}: {
  id: string;
  label: string;
  helpText?: string;
  value: string;
  onChange: (next: string) => void;
  error?: string | null;
  rows?: number;
  disabled?: boolean;
}) {
  return (
    <div className="grid gap-2">
      <Label htmlFor={id}>{label}</Label>
      {helpText && <p className="text-sm text-muted-foreground">{helpText}</p>}
      <Textarea
        id={id}
        value={value}
        rows={rows}
        disabled={disabled}
        aria-invalid={!!error}
        className="font-mono text-sm"
        spellCheck={false}
        onChange={(e) => onChange(e.target.value)}
      />
      {error && (
        <p className="text-sm text-destructive" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}
