import { cn } from '../../../utils/widgetUtils';

/**
 * Right-arrow icon for inline text links ("Learn more", "View all", …).
 * The fill reads `--pb-link-arrow-color` so a tenant can tint every link
 * arrow (Mowing → orange #fa6e25); the `currentColor` fallback keeps the
 * arrow matching the link text for tenants that don't set the token.
 */
export function LinkArrow({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className={cn('size-6 shrink-0 fill-[var(--pb-link-arrow-color,currentColor)]', className)}
      aria-hidden="true"
    >
      {/* No <title>: the svg is aria-hidden (decorative) and a title pops a
			    stray native "Arrow" tooltip on every link hover. */}
      <path d="M21.7061 12.7083L14.707 19.7073C14.512 19.9023 14.256 20.0003 14 20.0003C13.744 20.0003 13.488 19.9023 13.293 19.7073C12.902 19.3163 12.902 18.6842 13.293 18.2933L18.5859 13.0003H3C2.447 13.0003 2 12.5523 2 12.0003C2 11.4483 2.447 11.0003 3 11.0003H18.5859L13.293 5.70731C12.902 5.31631 12.902 4.68425 13.293 4.29325C13.684 3.90225 14.316 3.90225 14.707 4.29325L21.7061 11.2923C21.7991 11.3853 21.8721 11.4952 21.9231 11.6182C22.0241 11.8622 22.0241 12.1384 21.9231 12.3824C21.8721 12.5054 21.7991 12.6153 21.7061 12.7083Z" />
    </svg>
  );
}
