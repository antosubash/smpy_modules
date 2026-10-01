import { Link } from '@inertiajs/react';
import { useT } from '@simple-module-py/i18n';
import { NavIcon } from '@simple-module-py/ui/components/NavIcon';
import { Badge } from '@simple-module-py/ui/components/ui/badge';
import type React from 'react';
import type { TypeRead } from '../utils/types';
import { RecordListPublicUrl } from './RecordListPublicUrl';
import { navIconName } from './typeeditor/navIcons';

/**
 * One type's icon, label link, "In sidebar" marker, description and public
 * URL — the hub's table row and its narrow-screen card render the same
 * parts. `card` carries the two class differences between them (the table
 * cell is already `font-medium`, and only the card's column stretches);
 * `children` lands inside the text column, where the card stacks its key,
 * counts and edit link.
 */
export function TypeIdentity({
  type,
  publicRoutePrefix,
  card = false,
  children,
}: {
  type: TypeRead;
  publicRoutePrefix?: string;
  card?: boolean;
  children?: React.ReactNode;
}) {
  const { t } = useT();
  return (
    <div className="flex items-start gap-2">
      {type.icon && (
        <span
          className="mt-0.5 shrink-0 text-muted-foreground"
          data-testid="records-type-icon"
          data-icon={navIconName(type.icon)}
        >
          {/* `NavIcon` draws from an allowlist, not from all of lucide-react,
              and answers a name outside it with an empty span — so an icon
              this row can't draw falls back to the module's own rather than
              to a hole. */}
          <NavIcon name={navIconName(type.icon)} />
        </span>
      )}
      <div className={card ? 'min-w-0 flex-1' : 'min-w-0'}>
        <Link
          href={`/admin/records/${type.key}`}
          className={card ? 'font-medium hover:underline' : 'hover:underline'}
          data-testid="records-type-link"
        >
          {type.label}
        </Link>
        {type.show_in_menu && (
          <span
            className="ml-2 text-xs font-normal text-muted-foreground"
            data-testid="records-type-in-sidebar"
          >
            {t('records.types.in_sidebar', { defaultValue: 'In sidebar' })}
          </span>
        )}
        {type.description && (
          <p
            className="text-sm font-normal text-muted-foreground"
            data-testid="records-type-description"
          >
            {type.description}
          </p>
        )}
        {type.is_public && (
          <RecordListPublicUrl typeKey={type.key} publicRoutePrefix={publicRoutePrefix} />
        )}
        {children}
      </div>
    </div>
  );
}

/** The type's key and, when it has one, its collection badge. */
export function TypeKey({ type }: { type: TypeRead }) {
  return (
    <>
      {type.key}
      {type.collection && (
        <Badge
          variant="outline"
          className="ml-2 font-sans"
          data-testid="records-type-collection-badge"
        >
          {type.collection}
        </Badge>
      )}
    </>
  );
}

/** "N records", then "(N trashed)" and the "(N invalid)" link when non-zero.
 *  The trashed part is muted by its own class in the table only: the card's
 *  enclosing paragraph is muted already. */
export function TypeCounts({ type, card = false }: { type: TypeRead; card?: boolean }) {
  const { t } = useT();
  return (
    <>
      {t('records.types.record_count', {
        count: type.record_count,
        defaultValue: '{count} record',
        defaultValue_other: '{count} records',
      })}
      {type.trashed_record_count > 0 && (
        <span className={card ? 'ml-1' : 'ml-1 text-muted-foreground'}>
          {t('records.types.trashed_record_count', {
            count: type.trashed_record_count,
            defaultValue: '({count} trashed)',
            defaultValue_other: '({count} trashed)',
          })}
        </span>
      )}
      {/* A link and not a count: the number is only useful if it is one
          click from the records it counts, which is the list filtered by the
          same flag. */}
      {type.invalid_record_count > 0 && (
        <Link
          href={`/admin/records/${type.key}?filter=invalid:eq:true`}
          className="ml-1 text-destructive hover:underline"
          data-testid="records-type-invalid-count"
        >
          {t('records.types.invalid_record_count', {
            count: type.invalid_record_count,
            defaultValue: '({count} invalid)',
            defaultValue_other: '({count} invalid)',
          })}
        </Link>
      )}
    </>
  );
}

/**
 * The Records hub below `sm` (U7): round 1 gave the record *list* stacked
 * cards at this width (`RecordCardList`); the hub's own table never got the
 * same treatment, so it stayed a 547px table in a 358px box with "Edit
 * schema" swiped off the right edge and no affordance saying more was
 * there. Same information as `Types`' table row, one card per type, with
 * "Edit schema" a visible link in the card body rather than an action
 * column.
 */
export function TypesCardList({
  types,
  publicRoutePrefix,
}: {
  types: TypeRead[];
  publicRoutePrefix?: string;
}) {
  const { t } = useT();
  return (
    <ul className="space-y-3">
      {types.map((type) => (
        <li
          key={type.key}
          data-testid="records-type-card"
          data-type-key={type.key}
          className="rounded-lg border p-3"
        >
          <TypeIdentity type={type} publicRoutePrefix={publicRoutePrefix} card>
            <p className="mt-1 font-mono text-xs text-muted-foreground">
              <TypeKey type={type} />
            </p>
            <p className="mt-1 text-sm text-muted-foreground">
              <TypeCounts type={type} card />
            </p>
            <Link
              href={`/admin/records/types/${type.key}`}
              className="mt-1 inline-block text-sm text-primary hover:underline"
              data-testid="records-type-edit-schema"
            >
              {t('records.types.edit_schema', { defaultValue: 'Edit schema' })}
            </Link>
          </TypeIdentity>
        </li>
      ))}
    </ul>
  );
}
