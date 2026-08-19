import { Button } from '@simple-module-py/ui/components/ui/button';
import { Checkbox } from '@simple-module-py/ui/components/ui/checkbox';
import { Input } from '@simple-module-py/ui/components/ui/input';
import { Label } from '@simple-module-py/ui/components/ui/label';
import { NativeSelect } from '@simple-module-py/ui/components/ui/native-select';
import type { ReactNode } from 'react';

import type { PageRead } from '../../utils/api';

const TITLE_ID = 'page-settings-title';
const SLUG_ID = 'page-settings-slug';
const PARENT_ID = 'page-settings-parent';
const HEADER_ID = 'page-settings-header-nav';
const FOOTER_ID = 'page-settings-footer';
const INDEX_ID = 'page-settings-index';

interface Props {
  title: string;
  onTitleChange: (value: string) => void;
  slug: string;
  onSlugChange: (value: string) => void;
  /** The slug this page was loaded with. A redirect is only promised when the
   *  page already exists at an address someone could have linked to. */
  savedSlug: string | null;
  parentId: number | null;
  onParentChange: (value: number | null) => void;
  /** Every other page, for the parent select. */
  pages: PageRead[];
  showInHeaderNav: boolean;
  onShowInHeaderNavChange: (value: boolean) => void;
  showInFooter: boolean;
  onShowInFooterChange: (value: boolean) => void;
  indexInSearch: boolean;
  onIndexInSearchChange: (value: boolean) => void;
  publicPrefix: string;
  /** Duplicate / save-as-template / delete, supplied by the editor. */
  actions?: ReactNode;
}

/** The Page tab — what the page *is*, as opposed to what it contains.
 *
 * Nav membership lives here but nav *order* does not: the order belongs to the
 * layout editor, and a page choosing where it sits in someone else's list is
 * how navigation ordering becomes impossible to explain.
 */
export function PageSettingsPanel({
  title,
  onTitleChange,
  slug,
  onSlugChange,
  savedSlug,
  parentId,
  onParentChange,
  pages,
  showInHeaderNav,
  onShowInHeaderNavChange,
  showInFooter,
  onShowInFooterChange,
  indexInSearch,
  onIndexInSearchChange,
  publicPrefix,
  actions,
}: Props) {
  const slugMoved = savedSlug !== null && savedSlug !== slug;

  return (
    <div className="grid gap-5 text-sm md:grid-cols-2">
      <div className="grid gap-2">
        <Label htmlFor={TITLE_ID}>Title</Label>
        <Input id={TITLE_ID} value={title} onChange={(e) => onTitleChange(e.target.value)} />
      </div>

      <div className="grid gap-2">
        <Label htmlFor={SLUG_ID}>URL</Label>
        <div className="flex items-center gap-1">
          <span className="text-muted-foreground">{publicPrefix}/</span>
          <Input id={SLUG_ID} value={slug} onChange={(e) => onSlugChange(e.target.value)} />
        </div>
        <p className="text-xs text-muted-foreground">
          {slugMoved
            ? `Saving leaves a permanent redirect from ${publicPrefix}/${savedSlug}, so existing links keep working.`
            : 'Changing this leaves a redirect from the old URL.'}
        </p>
      </div>

      <div className="grid gap-2">
        <Label htmlFor={PARENT_ID}>Parent page</Label>
        <NativeSelect
          id={PARENT_ID}
          value={parentId === null ? '' : String(parentId)}
          onChange={(e) => onParentChange(e.target.value ? Number(e.target.value) : null)}
        >
          <option value="">None</option>
          {pages.map((page) => (
            <option key={page.id} value={String(page.id)}>
              {page.title}
            </option>
          ))}
        </NativeSelect>
        <p className="text-xs text-muted-foreground">Affects the breadcrumb, not the URL.</p>
      </div>

      <fieldset className="m-0 grid content-start gap-3 border-0 p-0">
        <legend className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          Navigation
        </legend>
        <div className="flex items-center gap-2">
          <Checkbox
            id={HEADER_ID}
            checked={showInHeaderNav}
            onCheckedChange={(checked) => onShowInHeaderNavChange(checked === true)}
          />
          <Label htmlFor={HEADER_ID}>Show in header nav</Label>
        </div>
        <div className="flex items-center gap-2">
          <Checkbox
            id={FOOTER_ID}
            checked={showInFooter}
            onCheckedChange={(checked) => onShowInFooterChange(checked === true)}
          />
          <Label htmlFor={FOOTER_ID}>Show in footer</Label>
        </div>
        <p className="text-xs text-muted-foreground">Order is set in the site layout editor.</p>
      </fieldset>

      <fieldset className="m-0 grid content-start gap-3 border-0 p-0">
        <legend className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          Visibility
        </legend>
        <div className="flex items-center gap-2">
          <Checkbox
            id={INDEX_ID}
            checked={indexInSearch}
            onCheckedChange={(checked) => onIndexInSearchChange(checked === true)}
          />
          <Label htmlFor={INDEX_ID}>Allow indexing</Label>
        </div>
        <p className="text-xs text-muted-foreground">
          Off emits <code>noindex</code> and drops the page from the sitemap. Whether it is public
          at all is the publish state, set from the toolbar.
        </p>
      </fieldset>

      {actions && <div className="flex flex-wrap gap-2 md:col-span-2">{actions}</div>}
    </div>
  );
}
