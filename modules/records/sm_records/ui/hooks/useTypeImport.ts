import { useCallback } from 'react';
import { importTypeDefinition, type TypeDefinition } from '../utils/type-io';
import type { TypeRead } from '../utils/types';
import type { SchemaApplyBody } from './useSchemaApply';

/**
 * Applying an imported definition (missing-UI M3), which is two different
 * writes wearing one button.
 *
 * A definition whose `key` is the type being edited is an **update**, and it
 * goes through `useSchemaApply` — the schema editor's own 409 machinery — so
 * a change that would break records comes back as the same dry-run report,
 * with the same "Apply anyway" and the same orphaned-value prompts, as the
 * equivalent edit made by hand. That is not a convenience: `POST
 * /types/import` with `mode=update` *is* `update_type` server-side, so those
 * are the responses it produces.
 *
 * A definition naming any other key is a **create**, which has no version to
 * check and nothing on this page to refuse it; the caller navigates to the
 * type it made.
 */
export function useTypeImport({
  current,
  run,
  reset,
  onCreated,
}: {
  current: TypeRead | null;
  run: (
    attempt: (body: SchemaApplyBody) => Promise<TypeRead>,
    body: SchemaApplyBody,
  ) => Promise<TypeRead | null>;
  reset: () => void;
  onCreated: (created: TypeRead) => void;
}): { importDefinition: (definition: TypeDefinition) => Promise<unknown> } {
  const importDefinition = useCallback(
    async (definition: TypeDefinition) => {
      if (!current || definition.key !== current.key) {
        onCreated(await importTypeDefinition({ ...definition, mode: 'create' }));
        return null;
      }
      reset();
      return run((body) => importTypeDefinition({ ...definition, ...body, mode: 'update' }), {
        expected_version: current.version,
      });
    },
    [current, run, reset, onCreated],
  );
  return { importDefinition };
}
