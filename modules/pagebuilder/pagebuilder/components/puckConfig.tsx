/**
 * Shared Puck configuration consumed by both `<Puck>` (editor) and
 * `<Render>` (public viewer). The same component definitions are used
 * in both places so what authors see in the editor matches what
 * visitors see on the published page.
 */

import type { Config } from '@measured/puck';

import { ButtonBlock } from './blocks/Button';
import { ColumnsBlock } from './blocks/Columns';
import { HeadingBlock } from './blocks/Heading';
import { ImageBlock } from './blocks/Image';
import { SpacerBlock } from './blocks/Spacer';
import { TextBlock } from './blocks/Text';

export interface PageRootProps {
  title: string;
}

export const puckConfig: Config<
  {
    Heading: Parameters<typeof HeadingBlock.render>[0];
    Text: Parameters<typeof TextBlock.render>[0];
    Image: Parameters<typeof ImageBlock.render>[0];
    Button: Parameters<typeof ButtonBlock.render>[0];
    Columns: Parameters<typeof ColumnsBlock.render>[0];
    Spacer: Parameters<typeof SpacerBlock.render>[0];
  },
  PageRootProps
> = {
  root: {
    fields: {
      title: { type: 'text' },
    },
    defaultProps: { title: 'Untitled page' },
    render: ({ children }) => <div className="max-w-4xl mx-auto p-6">{children}</div>,
  },
  categories: {
    typography: { components: ['Heading', 'Text'] },
    media: { components: ['Image'] },
    actions: { components: ['Button'] },
    layout: { components: ['Columns', 'Spacer'] },
  },
  components: {
    Heading: HeadingBlock,
    Text: TextBlock,
    Image: ImageBlock,
    Button: ButtonBlock,
    Columns: ColumnsBlock,
    Spacer: SpacerBlock,
  },
};

export const emptyData = { content: [], root: { props: { title: 'Untitled page' } } };

/**
 * Editor preview viewports surfaced as a switcher in the Puck toolbar.
 * The pixel widths match common mobile/tablet/desktop breakpoints rather
 * than specific devices so the preview reflects what visitors see.
 */
export const editorViewports = [
  { width: 360, height: 640, label: 'Mobile', icon: 'Smartphone' },
  { width: 768, height: 1024, label: 'Tablet', icon: 'Tablet' },
  { width: 1280, height: 800, label: 'Desktop', icon: 'Monitor' },
] as const;
