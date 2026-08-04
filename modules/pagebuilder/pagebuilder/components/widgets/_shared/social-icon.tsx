import { Mail } from 'lucide-react';

/**
 * Icons the site header's utility bar can show in place of a link label.
 *
 * Deliberately small: lucide 1.x removed its brand glyphs, so anything here
 * has to be vendored below with its licence. Adding one means finding a
 * correctly-licensed path, not approximating it.
 */
export const SOCIAL_ICON_NAMES = ['bluesky', 'linkedin', 'email'] as const;

export type SocialIconName = (typeof SOCIAL_ICON_NAMES)[number];

export const SOCIAL_ICON_OPTIONS = [
  { label: 'BlueSky', value: 'bluesky' },
  { label: 'LinkedIn', value: 'linkedin' },
  { label: 'Email', value: 'email' },
];

/**
 * BlueSky butterfly. Glyph: Font Awesome Free 6.7.2 `brands/bluesky`
 * (https://fontawesome.com — CC BY 4.0), path data unmodified.
 */
function BlueskyIcon({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 512 512"
      xmlns="http://www.w3.org/2000/svg"
      fill="currentColor"
      className={className}
      aria-hidden="true"
    >
      {/* No <title>: the svg is aria-hidden (the link carries the label), and a
          title would pop a stray native tooltip on hover. */}
      <path d="M111.8 62.2C170.2 105.9 233 194.7 256 242.4c23-47.6 85.8-136.4 144.2-180.2c42.1-31.6 110.3-56 110.3 21.8c0 15.5-8.9 130.5-14.1 149.2C478.2 298 412 314.6 353.1 304.5c102.9 17.5 129.1 75.5 72.5 133.5c-107.4 110.2-154.3-27.6-166.3-62.9l0 0c-1.7-4.9-2.6-7.8-3.3-7.8s-1.6 3-3.3 7.8l0 0c-12 35.3-59 173.1-166.3 62.9c-56.5-58-30.4-116 72.5-133.5C100 314.6 33.8 298 15.7 233.1C10.4 214.4 1.5 99.4 1.5 83.9c0-77.8 68.2-53.4 110.3-21.8z" />
    </svg>
  );
}

/**
 * LinkedIn mark. Geometry: lucide `linkedin` (ISC), which lucide 1.x dropped
 * along with the rest of its brand set — vendored rather than pinned back, so
 * the module keeps up with lucide. Filled rather than stroked, matching the
 * design system's solid social strip.
 */
function LinkedinIcon({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      xmlns="http://www.w3.org/2000/svg"
      fill="currentColor"
      className={className}
      aria-hidden="true"
    >
      <path d="M16 8a6 6 0 0 1 6 6v7h-4v-7a2 2 0 0 0-2-2 2 2 0 0 0-2 2v7h-4v-7a6 6 0 0 1 6-6z" />
      <rect width="4" height="12" x="2" y="9" />
      <circle cx="4" cy="4" r="2" />
    </svg>
  );
}

export function SocialIcon({ name, className }: { name: SocialIconName; className?: string }) {
  switch (name) {
    case 'bluesky':
      return <BlueskyIcon className={className} />;
    case 'linkedin':
      return <LinkedinIcon className={className} />;
    default:
      return <Mail className={className} aria-hidden="true" />;
  }
}
