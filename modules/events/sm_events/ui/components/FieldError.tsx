/** The message under a form field; the input points at it with `aria-describedby`. */
export const fieldErrorId = (id: string) => `${id}-error`;

export function FieldError({ id, message }: { id: string; message?: string }) {
  if (!message) return null;
  return (
    <p id={fieldErrorId(id)} className="text-sm text-destructive">
      {message}
    </p>
  );
}

/** The `aria-*` pair an input with a message needs. */
export const invalidProps = (id: string, message?: string) =>
  message ? { 'aria-invalid': true as const, 'aria-describedby': fieldErrorId(id) } : {};
