/** Shared view-model types for the media library. */

export interface ListFilters {
  search: string;
  contentType: string;
  folder: string | null; // null = Any; "" = Unfiled; "x" = exact folder.
  minKB: string;
  maxKB: string;
}

export type UploadStatus = 'pending' | 'uploading' | 'done' | 'error';

export interface UploadItem {
  id: string;
  file: File;
  status: UploadStatus;
  loaded: number;
  total: number;
  error: string | null;
}
