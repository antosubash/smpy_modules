import { Label } from '@simple-module-py/ui/components/ui/label';
import type { ReactNode } from 'react';

export function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <fieldset className="grid gap-4 rounded-lg border p-4">
      <legend className="px-1 text-sm font-medium">{title}</legend>
      {children}
    </fieldset>
  );
}

export function Field({
  id,
  label,
  hint,
  children,
}: {
  id: string;
  label: string;
  hint?: string;
  children: ReactNode;
}) {
  return (
    <div className="grid gap-2">
      <Label htmlFor={id}>{label}</Label>
      {children}
      {hint && <p className="text-sm text-muted-foreground">{hint}</p>}
    </div>
  );
}
