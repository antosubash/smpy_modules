/**
 * Video and audio a publication hosts itself.
 *
 * Separate from `Embed`, which is an `<iframe>` and therefore only speaks to
 * services that publish a player. A reporter's own clip — an mp4 out of a
 * camera, an interview recording, a piece of radio — has no player to embed,
 * and until these existed there was no way to put one in an article at all.
 *
 * Both take a URL for the same reason every other picture here does: the media
 * library belongs to pagebuilder, and these have to work without it.
 */

import type { ComponentConfig } from '@puckeditor/core';

import { keys, useT } from '../../../utils/i18n';

export interface VideoProps {
  url: string;
  poster: string;
  caption: string;
}

export const VideoBlock: ComponentConfig<VideoProps> = {
  label: keys.news.blocks.video.label,
  fields: {
    url: { type: 'text', label: keys.news.blocks.video.url },
    poster: { type: 'text', label: keys.news.blocks.video.poster },
    caption: { type: 'text', label: keys.news.blocks.common.caption_optional },
  },
  defaultProps: { url: '', poster: '', caption: '' },
  render: ({ url, poster, caption }) => {
    if (!url) return <></>;
    return (
      <figure className="my-8">
        {/* `preload="metadata"`, not `auto`: an article can carry several of
            these, and a reader who scrolls past one should not have paid for
            it. A poster gives them something to see before they choose. */}
        <video
          src={url}
          poster={poster || undefined}
          controls
          preload="metadata"
          className="w-full rounded-lg"
        >
          {/* No caption track to offer, but the element must not silently
              claim otherwise; a real one belongs here when there is one. */}
          <track kind="captions" />
        </video>
        {caption && (
          <figcaption className="mt-2 text-sm text-muted-foreground">{caption}</figcaption>
        )}
      </figure>
    );
  },
};

export interface AudioProps {
  url: string;
  title: string;
  caption: string;
}

export const AudioBlock: ComponentConfig<AudioProps> = {
  label: keys.news.blocks.audio.label,
  fields: {
    url: { type: 'text', label: keys.news.blocks.audio.url },
    title: { type: 'text', label: keys.news.blocks.audio.title },
    caption: { type: 'text', label: keys.news.blocks.common.caption_optional },
  },
  defaultProps: { url: '', title: '', caption: '' },
  // A component rather than JSX inline: the fallback accessible name is
  // translated, and Puck calls `render` as a plain function.
  render: ({ url, title, caption }) => <AudioRender url={url} title={title} caption={caption} />,
};

function AudioRender({ url, title, caption }: AudioProps) {
  const { t } = useT();
  if (!url) return <></>;
  return (
    <figure className="my-8 rounded-lg border bg-muted/40 p-4">
      {title && <p className="mb-2 text-sm font-semibold">{title}</p>}
      {/* Labelled by the title where there is one: a bare player announces
          itself as "audio" and nothing else, which in an article carrying
          three of them tells a listener nothing. */}
      <audio
        src={url}
        controls
        preload="metadata"
        aria-label={title || t(keys.news.blocks.audio.fallback_label)}
        className="w-full"
      >
        <track kind="captions" />
      </audio>
      {caption && <figcaption className="mt-2 text-sm text-muted-foreground">{caption}</figcaption>}
    </figure>
  );
}
