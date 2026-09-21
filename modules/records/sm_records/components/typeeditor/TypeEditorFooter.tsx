import type { DryRunReport, TypeRead } from '../../utils/types';
import { DeleteTypeSection } from './DeleteTypeSection';
import { SchemaConflictPanel } from './SchemaConflictPanel';
import { TypeRevisions } from './TypeRevisions';

/**
 * Everything below the schema editor's Save button: the two 409 shapes a
 * schema write can come back as, the type's schema history, and the danger
 * zone. All three exist only for a type that has been created, and none of
 * them is part of the form above — which is why they live together here,
 * out of `TypeEditor`'s 300-line budget.
 */
export function TypeEditorFooter({
  current,
  report,
  conflicts,
  pending,
  onForce,
  onOrphaned,
  onRestored,
  onDeleted,
}: {
  current: TypeRead | null;
  report: DryRunReport | null;
  conflicts: Record<string, number> | null;
  pending: boolean;
  onForce: () => Promise<unknown>;
  onOrphaned: (choice: 'restore' | 'discard') => Promise<unknown>;
  onRestored: (saved: TypeRead) => void;
  onDeleted: () => void;
}) {
  return (
    <>
      <SchemaConflictPanel
        report={report}
        conflicts={conflicts}
        pending={pending}
        onForce={onForce}
        onOrphaned={onOrphaned}
      />
      {current && <TypeRevisions type={current} onRestored={onRestored} />}
      {current && <DeleteTypeSection type={current} onDeleted={onDeleted} />}
    </>
  );
}
