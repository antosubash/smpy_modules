import { Button } from '@simple-module-py/ui/components/ui/button';

/** A row of mutually exclusive filter chips. `aria-pressed` carries the
 *  selection, so it reads the same to a screen reader as to the eye. */
export function ChipGroup<T extends string>({
  label,
  options,
  value,
  onChange,
  testId,
}: {
  label: string;
  options: { value: T; label: string }[];
  value: T;
  onChange: (next: T) => void;
  testId: string;
}) {
  return (
    <fieldset
      aria-label={label}
      className="m-0 flex min-w-0 flex-wrap gap-2 border-0 p-0"
      data-testid={testId}
    >
      {options.map((option) => (
        <Button
          key={option.value}
          type="button"
          size="sm"
          variant={option.value === value ? 'default' : 'outline'}
          aria-pressed={option.value === value}
          data-testid={`${testId}-${option.value}`}
          onClick={() => onChange(option.value)}
        >
          {option.label}
        </Button>
      ))}
    </fieldset>
  );
}
