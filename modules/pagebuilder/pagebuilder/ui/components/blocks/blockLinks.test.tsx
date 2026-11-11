// @vitest-environment happy-dom
import type { ComponentType } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { CTAButton } from '../widgets/_shared/cta-button';
import { TextLink } from '../widgets/_shared/text-link';
import { IframeWidget } from '../widgets/iframe-widget';
import { TagsWidget } from '../widgets/tags-widget';
import { VideoWidget } from '../widgets/video-widget';
import { ButtonBlock } from './Button';

/**
 * A link stored before the server refused unsafe ones (#354) renders as `#`,
 * whatever block it sits in: every block's href goes through `safeHref`.
 */

const UNSAFE = ['javascript:alert(1)', ' javascript:alert(1)', 'data:text/html,x', 'vbscript:x'];

const hrefs = (html: string) => [...html.matchAll(/href="([^"]*)"/g)].map((m) => m[1]);

function renderBlock(config: { render: unknown }, props: Record<string, unknown>): string {
  const Render = config.render as ComponentType<Record<string, unknown>>;
  return renderToStaticMarkup(<Render {...props} />);
}

describe('block links', () => {
  it.each(UNSAFE)('the Button block renders %j as #', (href) => {
    const html = renderBlock(ButtonBlock, { label: 'Go', href, variant: 'primary', size: 'md' });
    expect(hrefs(html)).toEqual(['#']);
  });

  it.each(UNSAFE)('the shared CTA button and text link render %j as #', (href) => {
    expect(
      hrefs(renderToStaticMarkup(<CTAButton label="Go" href={href} variant="primary" />)),
    ).toEqual(['#']);
    expect(hrefs(renderToStaticMarkup(<TextLink label="All" href={href} />))).toEqual(['#']);
  });

  it('an array item link goes through it too', () => {
    const html = renderBlock(TagsWidget, {
      label: 'Tags',
      items: [
        { label: 'Bad', href: 'javascript:alert(1)', active: false },
        { label: 'Good', href: '/news/tag/x', active: false },
      ],
    });
    expect(hrefs(html)).toEqual(['#', '/news/tag/x']);
  });

  it('a safe link is left exactly as written', () => {
    const html = renderBlock(ButtonBlock, {
      label: 'Mail',
      href: 'mailto:team@example.org',
      variant: 'primary',
      size: 'md',
    });
    expect(hrefs(html)).toEqual(['mailto:team@example.org']);
  });
});

describe('frame sources', () => {
  const srcs = (html: string) => [...html.matchAll(/ src="([^"]*)"/g)].map((m) => m[1]);

  it.each([...UNSAFE, 'mailto:a@b.org'])('the Iframe and Video blocks refuse %j', (src) => {
    const iframe = renderBlock(IframeWidget, { src, title: 't', height: '1px', sandboxed: true });
    expect(iframe).not.toContain('<iframe');
    const video = renderBlock(VideoWidget, { src, controls: true });
    expect(video).not.toContain('<video');
    expect(srcs(iframe + video)).toEqual([]);
  });

  it('an http(s) or relative source still loads', () => {
    const iframe = renderBlock(IframeWidget, { src: 'https://maps.example/x', title: 't' });
    expect(srcs(iframe)).toEqual(['https://maps.example/x']);
    const video = renderBlock(VideoWidget, { src: '/media/clip.mp4', controls: true });
    expect(srcs(video)).toEqual(['/media/clip.mp4']);
  });
});
