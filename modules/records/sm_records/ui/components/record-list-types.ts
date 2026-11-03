import type { MediaApi } from '../utils/media-api';
import type { RecordListPage, TenancyMode, TypeRead } from '../utils/types';

export type Props = {
  type: TypeRead;
  records: RecordListPage;
  /** Every content locale the module runs (`views.py::record_list`); absent
   *  degrades to "no language UI", same as the editor's own prop. */
  content_locales?: string[];
  /** `RecordsSettings.max_import_bytes` — the import menu refuses a bigger
   *  file client-side and says the limit (R9/M13). Absent falls back to the
   *  setting's own default. */
  max_import_bytes?: number;
  /** `RecordsSettings.public_route_prefix` (U14/Missing-15) — shown, with a
   *  copy button, next to the type's label when `type.is_public` is on.
   *  Absent falls back to the same default the type editor's own
   *  `PublicField` uses. */
  public_route_prefix?: string;
  /** Where a `media` column resolves its thumbnails; `null` shows the id. */
  media_api?: MediaApi | null;
  /** Tenancy design §J — read-only; drives `TenantBadge` in `actions`. */
  tenant?: string;
  tenancy_mode?: TenancyMode;
};
