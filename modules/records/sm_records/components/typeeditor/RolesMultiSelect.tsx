import { Checkbox } from '@simple-module-py/ui/components/ui/checkbox';
import { Label } from '@simple-module-py/ui/components/ui/label';

/**
 * `allowed_roles` as a checkbox list over `props.roles` — the role names the
 * framework's permission registry knows about (`views.py::_editor_context`).
 * A `<select multiple>` was considered and rejected: it hides how many are
 * selected without scrolling and offers no way to see the empty-selection
 * state read as "anyone" rather than "nobody its own eyes see" (§10).
 */
export function RolesMultiSelect({
  idPrefix,
  roles,
  selected,
  onChange,
  disabled = false,
}: {
  idPrefix: string;
  roles: string[];
  selected: string[];
  onChange: (next: string[]) => void;
  disabled?: boolean;
}) {
  const toggle = (role: string, checked: boolean) => {
    onChange(checked ? [...selected, role] : selected.filter((r) => r !== role));
  };

  if (roles.length === 0) return null;

  return (
    <div className="flex flex-wrap gap-x-4 gap-y-2 rounded-md border p-3">
      {roles.map((role) => {
        const id = `${idPrefix}-${role}`;
        return (
          <div key={role} className="flex items-center gap-2">
            <Checkbox
              id={id}
              checked={selected.includes(role)}
              disabled={disabled}
              onCheckedChange={(checked) => toggle(role, checked === true)}
            />
            <Label htmlFor={id} className="font-normal">
              {role}
            </Label>
          </div>
        );
      })}
    </div>
  );
}
