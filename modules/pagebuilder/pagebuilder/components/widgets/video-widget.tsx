import type { ComponentConfig } from '@puckeditor/core';
import { createCheckboxField } from '../../fields';
import { EmptyPlaceholder } from './_shared';

export type VideoWidgetProps = {
  src: string;
  autoplay: boolean;
  controls: boolean;
  loop: boolean;
  muted: boolean;
  width: 'full' | 'container' | 'narrow';
};

function isEmbeddable(url: string): {
  type: 'youtube' | 'vimeo' | 'file';
  src: string;
} {
  try {
    const u = new URL(url);
    if (u.hostname.includes('youtube.com') || u.hostname.includes('youtu.be')) {
      const id = u.hostname.includes('youtu.be') ? u.pathname.slice(1) : u.searchParams.get('v');
      return { type: 'youtube', src: `https://www.youtube.com/embed/${id}` };
    }
    if (u.hostname.includes('vimeo.com')) {
      return {
        type: 'vimeo',
        src: `https://player.vimeo.com/video/${u.pathname.replace(/\//, '')}`,
      };
    }
    return { type: 'file', src: url };
  } catch {
    return { type: 'file', src: url };
  }
}

export const VideoWidget: ComponentConfig<VideoWidgetProps> = {
  label: 'Video',
  fields: {
    src: { type: 'text', label: 'Video URL (YouTube, Vimeo, or file)' },
    autoplay: createCheckboxField('Autoplay'),
    controls: createCheckboxField('Show controls'),
    loop: createCheckboxField('Loop'),
    muted: createCheckboxField('Muted'),
    width: {
      type: 'select',
      label: 'Width',
      options: [
        { label: 'Full', value: 'full' },
        { label: 'Container', value: 'container' },
        { label: 'Narrow (centered)', value: 'narrow' },
      ],
    },
  },
  defaultProps: {
    src: '',
    autoplay: false,
    controls: true,
    loop: false,
    muted: false,
    width: 'full',
  },
  render: ({ src, autoplay, controls, loop, muted, width = 'full' }) => {
    if (!src) {
      return <EmptyPlaceholder label="Video (no source)" />;
    }
    const wrap =
      width === 'narrow' ? 'mx-auto max-w-3xl' : width === 'container' ? 'mx-auto max-w-5xl' : '';
    const { type, src: embedSrc } = isEmbeddable(src);
    if (type === 'file') {
      return (
        <div className="container mx-auto py-6">
          <div className={wrap}>
            <video
              className="w-full rounded-lg"
              src={embedSrc}
              autoPlay={autoplay}
              controls={controls}
              loop={loop}
              muted={muted}
            >
              <track kind="captions" />
            </video>
          </div>
        </div>
      );
    }
    return (
      <div className="container mx-auto py-6">
        <div className={wrap}>
          <div className="relative w-full" style={{ paddingBottom: '56.25%' }}>
            <iframe
              className="absolute inset-0 w-full h-full rounded-lg"
              src={embedSrc}
              title="Embedded video"
              allow="autoplay; encrypted-media; picture-in-picture"
              allowFullScreen
            />
          </div>
        </div>
      </div>
    );
  },
};
