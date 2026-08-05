import type { ComponentConfig } from '@puckeditor/core';
import { useState } from 'react';
import { createImageField, mediaLibraryAdapter } from '../../fields';
import { renderRichText } from './_internal/rich-text';
import { EmptyPlaceholder } from './_shared';

export type CarouselSlide = {
  imageUrl: string;
  caption: string;
};

export type CarouselWidgetProps = {
  slides: CarouselSlide[];
};

function CarouselRenderer({ slides }: CarouselWidgetProps) {
  const [index, setIndex] = useState(0);
  if (!slides || slides.length === 0) {
    return <EmptyPlaceholder label="Carousel (no slides)" />;
  }
  const slide = slides[Math.min(index, slides.length - 1)];
  return (
    <div className="container mx-auto py-6">
      <div className="relative aspect-video w-full overflow-hidden rounded-xl">
        {slide.imageUrl ? (
          <img
            src={slide.imageUrl}
            alt={slide.caption || ''}
            className="w-full h-full object-cover"
          />
        ) : (
          <div className="w-full h-full bg-gradient-to-br from-gray-200 to-gray-300" />
        )}
        {slide.caption && (
          <div className="absolute inset-x-0 bottom-0 bg-black/60 text-white p-4 text-center">
            {renderRichText(slide.caption)}
          </div>
        )}
        <button
          type="button"
          onClick={() => setIndex((i) => (i === 0 ? slides.length - 1 : i - 1))}
          className="absolute left-3 top-1/2 -translate-y-1/2 size-10 rounded-full bg-white/80 hover:bg-white text-gray-900 grid place-items-center"
          aria-label="Previous slide"
        >
          ‹
        </button>
        <button
          type="button"
          onClick={() => setIndex((i) => (i === slides.length - 1 ? 0 : i + 1))}
          className="absolute right-3 top-1/2 -translate-y-1/2 size-10 rounded-full bg-white/80 hover:bg-white text-gray-900 grid place-items-center"
          aria-label="Next slide"
        >
          ›
        </button>
        <div className="absolute inset-x-0 bottom-2 flex justify-center gap-2">
          {slides.map((_, i) => (
            <button
              // biome-ignore lint/suspicious/noArrayIndexKey: author-ordered array with no stable id; content repeats, so a content key collides
              key={i}
              type="button"
              onClick={() => {
                if (i !== index) setIndex(i);
              }}
              className={`size-2 rounded-full ${i === index ? 'bg-white' : 'bg-white/40'}`}
              aria-label={`Go to slide ${i + 1}`}
            />
          ))}
        </div>
      </div>
    </div>
  );
}

export const CarouselWidget: ComponentConfig<CarouselWidgetProps> = {
  label: 'Carousel',
  fields: {
    slides: {
      type: 'array',
      label: 'Slides',
      arrayFields: {
        imageUrl: createImageField(mediaLibraryAdapter, 'Image URL'),
        caption: { type: 'text', label: 'Caption' },
      },
      defaultItemProps: { imageUrl: '', caption: '' },
      min: 1,
      max: 12,
    },
  },
  defaultProps: {
    slides: [
      { imageUrl: '', caption: 'Slide one' },
      { imageUrl: '', caption: 'Slide two' },
      { imageUrl: '', caption: 'Slide three' },
    ],
  },
  render: ({ slides }) => <CarouselRenderer slides={slides || []} />,
};
