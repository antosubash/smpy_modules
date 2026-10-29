/** `/api/images` import endpoints: start (GeoJSON or ZIP), list and control jobs. */

import { send } from './api';
import { putParts, type Started } from './direct-upload';
import type { ImportControl, ImportJob, ImportKind, ImportMapping } from './types';

const BASE = '/api/images';

export function listImports(collectionId: string): Promise<{ items: ImportJob[] }> {
  return send(`${BASE}/collections/${collectionId}/imports`);
}

export type GeoJsonStart = {
  kind: Exclude<ImportKind, 'zip'>;
  mapping: ImportMapping;
  autoRunPrompts: boolean;
  /** The local file (base64 always; a URL import may send it instead of a URL). */
  file?: File;
  sourceUrl?: string;
};

export function startGeoJsonImport(collectionId: string, start: GeoJsonStart): Promise<ImportJob> {
  const form = new FormData();
  form.append('kind', start.kind);
  form.append('mapping', JSON.stringify(start.mapping));
  form.append('auto_run_prompts', String(start.autoRunPrompts));
  if (start.sourceUrl) form.append('source_url', start.sourceUrl);
  if (start.file) form.append('file', start.file, start.file.name);
  return send(`${BASE}/collections/${collectionId}/imports`, { method: 'POST', body: form });
}

type ZipCreated = { job_id: string; upload: Started };

const jsonPost = (body: unknown): RequestInit => ({
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
});

/** A ZIP goes up like a direct upload through the ZIP endpoints: `create` opens
 *  the job and the upload, the parts follow, `extract` seals the archive. */
export async function startZipImport(
  collectionId: string,
  file: File,
  options: { mapping?: ImportMapping; autoRunPrompts: boolean },
): Promise<ImportJob> {
  const created = await send<ZipCreated>(
    `${BASE}/collections/${collectionId}/imports/zip`,
    jsonPost({
      filename: file.name,
      size: file.size,
      mapping: options.mapping ?? null,
      auto_run_prompts: options.autoRunPrompts,
    }),
  );
  const parts = await putParts(created.upload, file);
  return send(`${BASE}/imports/${created.job_id}/extract`, jsonPost({ parts }));
}

export function controlImport(jobId: string, control: ImportControl): Promise<ImportJob> {
  return send(`${BASE}/imports/${jobId}/${control}`, { method: 'POST' });
}

export function deleteImport(jobId: string): Promise<void> {
  return send(`${BASE}/imports/${jobId}`, { method: 'DELETE' });
}
