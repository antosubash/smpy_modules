/** The import endpoints. Kept apart from `api.ts`, which is at its size budget. */

import { csrfHeaders } from './csrf';
import { BASE, errorFrom, read, write } from './http';
import type { ImportJob, ImportMapping, ImportSummary } from './importTypes';

const IMPORTS = '/imports';

async function must<T>(call: Promise<T | null>): Promise<T> {
  return (await call) as T;
}

export const createList = (key: string, label: string): Promise<{ key: string }> =>
  must(write<{ key: string }>('/lists', 'POST', { key, label }));

/** Multipart: the browser sets the `Content-Type` (with its boundary), so none is given. */
export async function uploadImport(list: string, files: File[]): Promise<ImportJob> {
  const form = new FormData();
  form.append('list', list);
  for (const file of files) form.append('files', file, file.name);
  const response = await fetch(`${BASE}${IMPORTS}`, {
    method: 'POST',
    credentials: 'same-origin',
    headers: { Accept: 'application/json', ...csrfHeaders('POST') },
    body: form,
  });
  if (!response.ok) throw await errorFrom(response);
  return (await response.json()) as ImportJob;
}

export const getImport = (id: number, signal?: AbortSignal): Promise<ImportJob> =>
  read<ImportJob>(`${IMPORTS}/${id}`, signal);

export const listImports = (): Promise<ImportSummary[]> => read<ImportSummary[]>(IMPORTS);

export const setMapping = (id: number, mapping: ImportMapping): Promise<ImportJob> =>
  must(write<ImportJob>(`${IMPORTS}/${id}`, 'PATCH', { mapping }));

export const applyImport = (id: number): Promise<ImportJob> =>
  must(write<ImportJob>(`${IMPORTS}/${id}/apply`, 'POST'));

export async function discardImport(id: number): Promise<void> {
  await write<null>(`${IMPORTS}/${id}`, 'DELETE');
}

export const errorsCsvUrl = (id: number): string => `${BASE}${IMPORTS}/${id}/errors.csv`;
