/**
 * Prop and metadata shapes for the `RecordsList` Puck block
 * (`RecordsListBlock.tsx` / `RecordsListRender.tsx`).
 *
 * `fieldMeta` and `typeIsPublic` are not authored by hand — they are baked
 * into the stored props by `RecordsListBlock`'s `resolveData`, the same
 * pattern `_shared/image-srcset.ts`'s `resolveImageSrcset` uses: the admin
 * `GET /api/records/types` a field's type/label/choices come from requires a
 * session, which only the logged-in Puck *editor* has. `<Render>` on the
 * public page never calls `resolveData` again — it renders whatever was last
 * saved — so baking this metadata in at edit time is what lets the render
 * function format a column correctly for an anonymous visitor without ever
 * making an authenticated call itself.
 */

export type RecordsListLayout = 'list' | 'cards' | 'table';

/** One selected field's display metadata, snapshotted from the type's
 *  schema at the moment the author picked it in the editor. */
export type FieldMetaEntry = {
  key: string;
  /** The field's declared `type` (design §6.1) — `text`, `number`, `date`, … */
  type: string;
  label: string;
  /** `select`/`multiselect` only; empty otherwise. */
  choices: { value: string; label: string }[];
};

export type RecordsListProps = {
  typeKey: string;
  /** Field keys to show, in order, beyond `display_title` (always shown). */
  fields: string[];
  /** Baked by `resolveData`; not a user-editable Puck field. */
  fieldMeta: FieldMetaEntry[];
  /** Baked alongside `fieldMeta`. `null` before the author has picked a type
   *  at all — distinct from `false`, which is a real "not public" answer. */
  typeIsPublic: boolean | null;
  filter: string;
  sort: string;
  /** `?locale=` on the public request — blank means the site's default
   *  content locale, never "every locale" (design §4.4, mirroring the public
   *  API's own rule for an anonymous reader with no `?locale=` at all). */
  locale: string;
  /** Sent as the `X-Tenant-ID` header (tenancy design §J item 4) — blank on
   *  a single-tenant host does nothing (the header is simply not sent); on a
   *  multi-tenant host it picks the tenant this block reads, and a blank
   *  value there is a 404 the same way no header is (design §H). */
  tenant: string;
  limit: number;
  layout: RecordsListLayout;
  title: string;
  emptyText: string;
  /** `{slug}` / `{uuid}` placeholders; empty means "no link" (design's own
   *  wording for the prop help). */
  linkTemplate: string;
  /** Anonymous API prefix. Defaults to `RecordsSettings.public_route_prefix`'s
   *  own default — see `utils/public-api.ts`'s header for why this is a
   *  plain field rather than read from a shared prop. */
  apiPrefix: string;
};
