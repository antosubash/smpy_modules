import { cn, decorativeAriaProps } from '../../../utils/widgetUtils';

export type ContentMediaAspect = 'square' | 'video' | 'portrait';

export type ContentMediaProps = {
  imageUrl: string;
  imageAlt: string;
  aspect?: ContentMediaAspect;
};

const ASPECT_CLASSES: Record<ContentMediaAspect, string> = {
  square: 'aspect-square',
  video: 'aspect-video',
  portrait: 'aspect-[3/4]',
};

// Hoisted: same rationale as MESH_STYLE in background-media.tsx — keep render
// referential stability so React doesn't churn the style attribute.
const DOTTED_STYLE = {
  background:
    'radial-gradient(circle, rgba(99,102,241,0.18) 1px, transparent 1px), ' +
    'linear-gradient(135deg, #f8fafc 0%, #e2e8f0 100%)',
  backgroundSize: '16px 16px, 100% 100%',
} as const;

export function ContentMedia({ imageUrl, imageAlt, aspect = 'video' }: ContentMediaProps) {
  const wrapperCls = cn('w-full rounded-xl overflow-hidden', ASPECT_CLASSES[aspect], 'shadow-xl');
  if (imageUrl) {
    return (
      <div className={wrapperCls}>
        <img
          src={imageUrl}
          alt={imageAlt ?? ''}
          {...decorativeAriaProps(imageAlt)}
          loading="lazy"
          className="w-full h-full object-cover"
        />
      </div>
    );
  }
  // data-pb-fallback is a stable selector for tests and CMS-side analytics.
  return <div data-pb-fallback="dotted-grid" className={wrapperCls} style={DOTTED_STYLE} />;
}
