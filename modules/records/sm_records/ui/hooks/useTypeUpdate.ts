import { useCallback } from 'react';
import { updateType } from '../utils/api';
import type { TypeRead } from '../utils/types';
import type { SchemaApplyBody } from './useSchemaApply';

export function useTypeUpdate(current: TypeRead | null) {
  const attemptUpdate = useCallback(
    (body: SchemaApplyBody) => {
      if (!current) return Promise.reject(new Error('No type loaded to update'));
      const { expected_version, ...rest } = body;
      return updateType(current.key, expected_version, rest);
    },
    [current],
  );

  return attemptUpdate;
}
