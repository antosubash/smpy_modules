/**
 * `RecordsList` widget: rendering + data fetching.
 *
 * Split from `RecordsListBlock.tsx` (the `ComponentConfig`) the same way
 * `article-cards-render.tsx` is split from `article-cards-widget.tsx`, and
 * for the same 300-line-cap reason.
 *
 * **One render path for both the Puck editor and the public page.**
 * `puckConfig.tsx` feeds this exact component into both `<Puck>` (the
 * editor's live preview) and `<Render>` (`PublicPage.tsx`) — see that file's
 * own header comment — so there is nothing here that special-cases "am I in
 * the editor" for the data fetch itself: both contexts call the same
 * anonymous `fetchPublicRecords`, get the same JSON, and render the same
 * markup. The one place `puck.isEditing` (design's own hook for this,
 * `WithPuckProps`) is read at all is the non-public-type hint, which is
 * explicitly editor-only by design — a visitor gets the plain empty state,
 * an author gets the empty state *plus* the reason.
 */

import { useT } from '@simple-module-py/i18n';
import { Section } from '@simple-module-py/pagebuilder/pagebuilder/components/widgets/_shared';
import type { CSSProperties } from 'react';
import { useEffect, useState } from 'react';

import { fetchPublicRecords, type PublicRecordItem } from '../../utils/public-api';
import { FieldValues, publicValue } from './FieldValues';
import { buildRecordHref } from './format';
import type { RecordsListProps } from './types';

type FetchState =
  | { status: 'loading' }
  | { status: 'error' }
  | { status: 'ready'; items: PublicRecordItem[]; media: string | null };

export type RecordsListRenderProps = RecordsListProps & {
  puck: { isEditing: boolean };
};

const HEADING_STYLE: CSSProperties = {
  fontWeight: 'var(--pb-display-weight)' as CSSProperties['fontWeight'],
  letterSpacing: 'var(--pb-display-tracking)',
  fontFamily: 'var(--pb-display-font)',
  color: 'var(--pb-heading-color)',
  fontSize: 'var(--pb-heading-lg, clamp(1.5rem, 1.25rem + 1.5625vw, 2.25rem))',
};

const BODY_STYLE: CSSProperties = { color: 'var(--pb-body-color)' };
const MUTED_STYLE: CSSProperties = { color: 'var(--pb-body-color)', opacity: 0.7 };

function SkeletonRows({ count }: { count: number }) {
  return (
    <div className="space-y-3" aria-hidden="true">
      {Array.from({ length: count }, (_, i) => (
        // Skeleton rows have no identity of their own to key by — a fixed
        // count rendered once per fetch, never reordered or diffed against
        // real data.
        // biome-ignore lint/suspicious/noArrayIndexKey: fixed-length placeholder list
        <div key={i} className="h-6 rounded bg-[var(--pb-surface-muted)] animate-pulse" />
      ))}
    </div>
  );
}

function useLoadingLabel(): string {
  const { t } = useT();
  return t('records.widget.loading', { defaultValue: 'Loading records…' });
}

function RecordTitle({ item, linkTemplate }: { item: PublicRecordItem; linkTemplate: string }) {
  const href = buildRecordHref(linkTemplate, item);
  if (href) {
    return (
      <a
        href={href}
        className="font-medium hover:underline"
        style={{ color: 'var(--pb-heading-color)' }}
      >
        {item.display_title}
      </a>
    );
  }
  return (
    <span className="font-medium" style={{ color: 'var(--pb-heading-color)' }}>
      {item.display_title}
    </span>
  );
}

/** `media` is the page's `media_url_template` — see `FieldValues.tsx`. */
type LayoutProps = { items: PublicRecordItem[]; props: RecordsListProps; media: string | null };

function ListLayout({ items, props, media }: LayoutProps) {
  return (
    <ul className="divide-y divide-[var(--pb-surface-muted)]">
      {items.map((item) => (
        <li key={item.uuid} className="flex flex-col gap-1 py-3">
          <RecordTitle item={item} linkTemplate={props.linkTemplate} />
          <div className="flex flex-wrap gap-x-4 gap-y-1">
            <FieldValues item={item} props={props} mediaUrlTemplate={media} />
          </div>
        </li>
      ))}
    </ul>
  );
}

function CardsLayout({ items, props, media }: LayoutProps) {
  return (
    <div className="grid gap-6 grid-cols-1 sm:grid-cols-2 lg:grid-cols-3">
      {items.map((item) => (
        <div
          key={item.uuid}
          className="rounded-xl p-4 bg-[var(--pb-surface-muted)] flex flex-col gap-2"
        >
          <RecordTitle item={item} linkTemplate={props.linkTemplate} />
          <div className="flex flex-col gap-1">
            <FieldValues item={item} props={props} mediaUrlTemplate={media} />
          </div>
        </div>
      ))}
    </div>
  );
}

function TableLayout({ items, props, media }: LayoutProps) {
  const { t } = useT();
  return (
    <table className="w-full text-left text-sm">
      <thead>
        <tr className="border-b" style={{ borderColor: 'var(--pb-surface-muted)' }}>
          <th className="py-2 pr-4 font-medium" style={BODY_STYLE}>
            {t('records.widget.title_column', { defaultValue: 'Title' })}
          </th>
          {props.fieldMeta.map((meta) => (
            <th key={meta.key} className="py-2 pr-4 font-medium" style={BODY_STYLE}>
              {meta.label}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {items.map((item) => (
          <tr
            key={item.uuid}
            className="border-b"
            style={{ borderColor: 'var(--pb-surface-muted)' }}
          >
            <td className="py-2 pr-4">
              <RecordTitle item={item} linkTemplate={props.linkTemplate} />
            </td>
            {props.fieldMeta.map((meta) => (
              <td key={meta.key} className="py-2 pr-4" style={BODY_STYLE}>
                {publicValue(meta, item, media)}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function RecordsListRender(props: RecordsListRenderProps) {
  const { t } = useT();
  const loadingLabel = useLoadingLabel();
  const isEditing = props.puck?.isEditing ?? false;
  const [state, setState] = useState<FetchState>({ status: 'loading' });

  // Baked at edit time (`RecordsListBlock`'s `resolveData`) — an explicit
  // `false` skips the network call entirely on the public page, since the
  // anonymous API would just 404 it (design §10: a private type is a 404,
  // identical to an unknown one). The editor still fetches, so an author who
  // just flipped the type public sees it work without re-saving.
  const skipFetch = props.typeIsPublic === false && !isEditing;

  useEffect(() => {
    if (!props.typeKey || skipFetch) {
      setState({ status: 'ready', items: [], media: null });
      return;
    }
    const controller = new AbortController();
    setState({ status: 'loading' });
    fetchPublicRecords(
      {
        prefix: props.apiPrefix,
        typeKey: props.typeKey,
        limit: props.limit,
        filter: props.filter,
        sort: props.sort,
        locale: props.locale,
        tenant: props.tenant,
      },
      controller.signal,
    )
      .then((page) =>
        setState({ status: 'ready', items: page.items, media: page.media_url_template ?? null }),
      )
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === 'AbortError') return;
        setState({ status: 'error' });
      });
    return () => controller.abort();
  }, [
    props.typeKey,
    props.apiPrefix,
    props.limit,
    props.filter,
    props.sort,
    props.locale,
    props.tenant,
    skipFetch,
  ]);

  const showHint = isEditing && props.typeIsPublic === false;

  return (
    <Section variant="default" spacing="default">
      {props.title && (
        <h2 className="mb-4 leading-[var(--pb-heading-leading,1.15)]" style={HEADING_STYLE}>
          {props.title}
        </h2>
      )}
      {state.status === 'loading' && (
        <div role="status" aria-label={loadingLabel}>
          <SkeletonRows count={Math.min(props.limit, 5) || 3} />
        </div>
      )}
      {state.status === 'error' && (
        <p className="text-sm" style={MUTED_STYLE}>
          {t('records.widget.error', {
            defaultValue: "Couldn't load records right now.",
          })}
        </p>
      )}
      {state.status === 'ready' && state.items.length === 0 && (
        <div>
          <p className="text-sm" style={MUTED_STYLE}>
            {props.emptyText || t('records.widget.empty', { defaultValue: 'No records to show.' })}
          </p>
          {showHint && (
            <p className="mt-1 text-xs" style={MUTED_STYLE}>
              {t('records.widget.hint_not_public', {
                defaultValue: 'Only public types render on the site.',
              })}
            </p>
          )}
        </div>
      )}
      {state.status === 'ready' &&
        state.items.length > 0 &&
        (props.layout === 'cards' ? (
          <CardsLayout items={state.items} props={props} media={state.media} />
        ) : props.layout === 'table' ? (
          <TableLayout items={state.items} props={props} media={state.media} />
        ) : (
          <ListLayout items={state.items} props={props} media={state.media} />
        ))}
    </Section>
  );
}
