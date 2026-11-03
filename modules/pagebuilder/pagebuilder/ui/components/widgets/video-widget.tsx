import type { ComponentConfig } from '@puckeditor/core';
import { createCheckboxField } from '../../fields';
import { keys, translate } from '../../utils/i18n';
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
  label: keys.pagebuilder.blocks.video.label,
  fields: {
    src: { type: 'text', label: keys.pagebuilder.blocks.video.src },
    autoplay: createCheckboxField(keys.pagebuilder.blocks.video.autoplay),
    controls: createCheckboxField(keys.pagebuilder.blocks.video.controls),
    loop: createCheckboxField(keys.pagebuilder.blocks.video.loop),
    muted: createCheckboxField(keys.pagebuilder.blocks.video.muted),
    width: {
      type: 'select',
      label: keys.pagebuilder.blocks.video.width,
      options: [
        { label: keys.pagebuilder.blocks.video.width_full, value: 'full' },
        { label: keys.pagebuilder.blocks.video.width_container, value: 'container' },
        { label: keys.pagebuilder.blocks.video.width_narrow, value: 'narrow' },
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
      return <EmptyPlaceholder label={translate(keys.pagebuilder.blocks.video.empty)} />;
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
              title={translate(keys.pagebuilder.blocks.video.frame_title)}
              allow="autoplay; encrypted-media; picture-in-picture"
              allowFullScreen
            />
          </div>
        </div>
      </div>
    );
  },
};
