import type { ComponentConfig } from '@puckeditor/core';
import { EyebrowSplitSection } from './_internal/eyebrow-split-section';
import { RichTextBlock, renderRichText } from './_internal/rich-text';

export type DefinitionSection = {
  subheading: string;
  body: string;
  image1: string;
  image1Alt: string;
  image2: string;
  image2Alt: string;
};

export type DefinitionItem = {
  title: string;
  sections: DefinitionSection[];
};

export type DefinitionListWidgetProps = {
  eyebrow: string;
  heading: string;
  items: DefinitionItem[];
};

function SectionImages({ section }: { section: DefinitionSection }) {
  const imgs = [
    section.image1 ? { src: section.image1, alt: section.image1Alt } : null,
    section.image2 ? { src: section.image2, alt: section.image2Alt } : null,
  ].filter((x): x is { src: string; alt: string } => x !== null);
  if (imgs.length === 0) return null;
  return (
    <div className={imgs.length === 2 ? 'grid grid-cols-2 gap-4' : ''}>
      {imgs.map((img, i) => (
        <img
          // biome-ignore lint/suspicious/noArrayIndexKey: author-ordered array with no stable id; content repeats, so a content key collides
          key={i}
          src={img.src}
          alt={img.alt}
          loading="lazy"
          className="aspect-[3/2] w-full rounded-lg object-cover"
        />
      ))}
    </div>
  );
}

export const DefinitionListWidget: ComponentConfig<DefinitionListWidgetProps> = {
  label: 'Definition list (rich accordion)',
  fields: {
    eyebrow: { type: 'text', label: 'Eyebrow' },
    heading: { type: 'text', label: 'Heading' },
    items: {
      type: 'array',
      label: 'Definitions',
      arrayFields: {
        title: { type: 'text', label: 'Title' },
        sections: {
          type: 'array',
          label: 'Sections',
          arrayFields: {
            subheading: { type: 'text', label: 'Sub-heading' },
            body: { type: 'textarea', label: 'Body' },
            image1: { type: 'text', label: 'Image 1 URL' },
            image1Alt: { type: 'text', label: 'Image 1 alt' },
            image2: { type: 'text', label: 'Image 2 URL (optional)' },
            image2Alt: { type: 'text', label: 'Image 2 alt' },
          },
          defaultItemProps: {
            subheading: '',
            body: '',
            image1: '',
            image1Alt: '',
            image2: '',
            image2Alt: '',
          },
        },
      },
      defaultItemProps: { title: 'New definition', sections: [] },
      min: 1,
      max: 20,
    },
  },
  defaultProps: {
    eyebrow: 'Definitions',
    heading: 'Definitions',
    items: [{ title: 'Definition', sections: [] }],
  },
  render: ({ eyebrow, heading, items }) => (
    <EyebrowSplitSection eyebrow={eyebrow} heading={heading}>
      <div className="border-t border-[#1a353e]/15">
        {items?.map((item, idx) => (
          <details
            // Index key: items have no stable id, and keying by title would
            // collide on duplicate titles (defaultItemProps.title is fixed).
            // Reordering in the editor can rebind open-state to a slot — an
            // accepted editor-only edge until items carry an id.
            // biome-ignore lint/suspicious/noArrayIndexKey: author-ordered array with no stable id; content repeats, so a content key collides
            key={idx}
            className="group border-b border-[#1a353e]/15"
            // `open` set at mount only (widget has no state → no re-render
            // re-asserts it), so the first row starts open but stays toggleable.
            {...(idx === 0 ? { open: true } : {})}
          >
            <summary
              className="flex cursor-pointer list-none items-center justify-between gap-4 py-4 text-lg font-semibold"
              style={{ color: 'var(--pb-heading-color)' }}
            >
              {/* Inside <summary>: emphasis only — a nested anchor here
								    would be invalid HTML and hijack the toggle. */}
              {renderRichText(item.title || '', { allowLinks: false })}
              <span
                aria-hidden="true"
                className="shrink-0 text-2xl font-light leading-none text-[#1a353e]"
              >
                <span className="group-open:hidden">+</span>
                <span className="hidden group-open:inline">−</span>
              </span>
            </summary>
            <div className="flex flex-col gap-5 pb-6">
              {item.sections?.map((section, si) => (
                // biome-ignore lint/suspicious/noArrayIndexKey: author-ordered array with no stable id; content repeats, so a content key collides
                <div key={si} className="flex flex-col gap-3">
                  {section.subheading && (
                    <p className="font-semibold" style={{ color: 'var(--pb-heading-color)' }}>
                      {renderRichText(section.subheading)}
                    </p>
                  )}
                  {section.body && (
                    <RichTextBlock
                      text={section.body}
                      className="leading-[var(--pb-body-leading,1.625)]"
                      style={{ color: 'var(--pb-body-color)' }}
                    />
                  )}
                  <SectionImages section={section} />
                </div>
              ))}
            </div>
          </details>
        ))}
      </div>
    </EyebrowSplitSection>
  ),
};
