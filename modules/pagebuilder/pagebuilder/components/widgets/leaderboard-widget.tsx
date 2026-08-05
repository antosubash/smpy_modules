import type { ComponentConfig } from '@puckeditor/core';
import { createImageField, mediaLibraryAdapter } from '../../fields';
import { cn } from '../../utils/widgetUtils';
import { AccentText } from './_internal/accent-text';
import { renderRichText } from './_internal/rich-text';

export type LeaderboardRow = {
  rank: string;
  name: string;
  score: string;
  avatarUrl?: string;
};

export type LeaderboardWidgetProps = {
  eyebrow: string;
  title: string;
  surface: 'default' | 'navy';
  top: { name: string; score: string; avatarUrl: string }[];
  rows: LeaderboardRow[];
};

// Inline icons keep the shared widget dependency-free.
function CrownIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="#f5b40a" className="size-6 shrink-0" aria-hidden="true">
      <title>Top rank</title>
      <path d="M5 16 3 6l5 4 4-6 4 6 5-4-2 10H5Zm0 2h14v2H5v-2Z" />
    </svg>
  );
}

function UserGlyph() {
  return (
    <svg viewBox="0 0 24 24" fill="#ffffff" className="size-1/2" aria-hidden="true">
      <title>User</title>
      <path d="M12 12a5 5 0 1 0 0-10 5 5 0 0 0 0 10Zm0 2c-4 0-7 2.2-7 5v1h14v-1c0-2.8-3-5-7-5Z" />
    </svg>
  );
}

// Avatar: photo when supplied, else a pink disc with a white user glyph
// (matches the Figma's #f1708a fallback avatars).
function Avatar({ src, size }: { src?: string; size: string }) {
  if (src) {
    return <img src={src} alt="" className={cn('shrink-0 rounded-full object-cover', size)} />;
  }
  return (
    <span
      className={cn('flex shrink-0 items-center justify-center rounded-full bg-[#f1708a]', size)}
    >
      <UserGlyph />
    </span>
  );
}

export const LeaderboardWidget: ComponentConfig<LeaderboardWidgetProps> = {
  label: 'Leaderboard',
  fields: {
    eyebrow: { type: 'text', label: 'Eyebrow' },
    title: { type: 'text', label: 'Title' },
    surface: {
      type: 'select',
      label: 'Surface',
      options: [
        { label: 'Default', value: 'default' },
        { label: 'Navy band', value: 'navy' },
      ],
    },
    top: {
      type: 'array',
      label: 'Podium (top 3)',
      arrayFields: {
        name: { type: 'text', label: 'Name' },
        score: { type: 'text', label: 'Score' },
        avatarUrl: createImageField(mediaLibraryAdapter, 'Avatar image'),
      },
      defaultItemProps: { name: 'Player', score: '0', avatarUrl: '' },
      min: 1,
      max: 3,
    },
    rows: {
      type: 'array',
      label: 'Ranked rows',
      arrayFields: {
        rank: { type: 'text', label: 'Rank' },
        name: { type: 'text', label: 'Name' },
        score: { type: 'text', label: 'Score' },
        avatarUrl: createImageField(mediaLibraryAdapter, 'Avatar image'),
      },
      defaultItemProps: {
        rank: '1',
        name: 'Player',
        score: '0',
        avatarUrl: '',
      },
      min: 1,
      max: 20,
    },
  },
  defaultProps: {
    eyebrow: '',
    title: 'Leaderboard',
    surface: 'navy',
    top: [
      { name: 'username', score: '1737', avatarUrl: '' },
      { name: 'username', score: '1706', avatarUrl: '' },
      { name: 'username', score: '924', avatarUrl: '' },
    ],
    rows: Array.from({ length: 7 }, (_, i) => ({
      rank: String(i + 4),
      name: 'username',
      score: '—',
    })),
  },
  render: (props) => <LeaderboardView {...props} />,
};

// Presentational leaderboard — shared by the static base widget (above) and the
// app's live, data-driven override, so both render pixel-for-pixel identically.
export function LeaderboardView({ eyebrow, title, surface, top, rows }: LeaderboardWidgetProps) {
  const navy = surface === 'navy';
  return (
    <section className="py-[var(--pb-section-py,3rem)]">
      <div
        className={cn(
          'container mx-auto rounded-[12px] px-6 py-10 sm:px-10 sm:py-12',
          navy
            ? 'bg-[var(--secondary,#42547e)] text-white'
            : 'bg-[var(--pb-surface-muted,#f3f3f4)]',
        )}
      >
        {eyebrow && (
          <p className="text-sm font-semibold uppercase tracking-wider opacity-80">
            {renderRichText(eyebrow)}
          </p>
        )}
        {/* AccentText, not bare renderRichText: this is a display heading on
				    `--pb-display-weight`, where a plain <strong>'s relative `bolder`
				    can compute to no visible change. */}
        {title && (
          <h2
            className="leading-tight"
            style={{
              fontWeight: 'var(--pb-display-weight)',
              fontFamily: 'var(--pb-display-font)',
              fontSize: 'var(--pb-heading-md, clamp(1.875rem, 1.3rem + 1.4vw, 2.5rem))',
              color: navy ? '#ffffff' : 'var(--pb-heading-color)',
            }}
          >
            <AccentText text={title} />
          </h2>
        )}
        <div className="mt-8 grid items-start gap-6 lg:grid-cols-[minmax(0,5fr)_7fr]">
          {/* Podium — three stacked cards */}
          <ol className="flex flex-col gap-4">
            {top.map((p, idx) => (
              <li
                // biome-ignore lint/suspicious/noArrayIndexKey: author-ordered array with no stable id; content repeats, so a content key collides
                key={idx}
                className="flex items-center gap-4 rounded-[12px] border border-[#dcdcdf]/40 px-4 py-3"
              >
                <Avatar src={p.avatarUrl || undefined} size="size-16" />
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-semibold">{p.name}</p>
                  <p className="flex items-center gap-2 text-3xl font-semibold leading-tight">
                    {p.score}
                    {idx === 0 && <CrownIcon />}
                  </p>
                </div>
                <span className="grid size-12 shrink-0 place-items-center rounded-full border-2 border-white text-xl font-semibold">
                  {idx + 1}
                </span>
              </li>
            ))}
          </ol>

          {/* Ranked table */}
          <div className="overflow-hidden rounded-[12px]">
            <div className="grid grid-cols-[1fr_auto_auto] gap-x-6 bg-white px-6 py-4 text-sm text-[#161728] sm:gap-x-10">
              <span>User</span>
              <span className="w-16 text-center">Rank</span>
              <span className="w-16 text-right">Score</span>
            </div>
            {rows.map((r, i) => (
              <div
                // biome-ignore lint/suspicious/noArrayIndexKey: author-ordered array with no stable id; content repeats, so a content key collides
                key={i}
                className="grid grid-cols-[1fr_auto_auto] items-center gap-x-6 bg-[#f3f3f4] px-6 py-3 text-[#161728] sm:gap-x-10"
              >
                <div className="flex min-w-0 items-center gap-3">
                  <Avatar src={r.avatarUrl || undefined} size="size-10" />
                  <span className="truncate text-sm font-medium">{r.name}</span>
                </div>
                <span className="w-16 text-center text-sm font-medium">{r.rank}</span>
                <span className="w-16 text-right text-sm font-semibold">{r.score}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}
