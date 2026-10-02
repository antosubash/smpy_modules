import type { ComponentConfig } from '@puckeditor/core';
import { createCheckboxField } from '../../fields';
import { keys, translate } from '../../utils/i18n';
import { EmptyPlaceholder } from './_shared';

export type IframeWidgetProps = {
  src: string;
  title: string;
  height: string;
  sandboxed: boolean;
};

export const IframeWidget: ComponentConfig<IframeWidgetProps> = {
  label: keys.pagebuilder.blocks.iframe.label,
  fields: {
    src: { type: 'text', label: keys.pagebuilder.blocks.iframe.src },
    title: { type: 'text', label: keys.pagebuilder.blocks.iframe.title },
    height: { type: 'text', label: keys.pagebuilder.blocks.iframe.height },
    sandboxed: createCheckboxField(keys.pagebuilder.blocks.iframe.sandboxed),
  },
  defaultProps: {
    src: '',
    title: 'Embedded content',
    height: '600px',
    sandboxed: true,
  },
  render: ({ src, title, height, sandboxed }) =>
    src ? (
      <div className="container mx-auto py-6">
        <iframe
          src={src}
          title={title || translate(keys.pagebuilder.blocks.iframe.fallback_title)}
          className="w-full rounded-lg border"
          style={{ height }}
          // NOTE: allow-scripts + allow-same-origin lets a SAME-ORIGIN embedded
          // document remove its own sandbox; the protection is meaningful for
          // cross-origin embeds (the primary use). Do not "simplify" this set
          // or the label without revisiting that trade-off.
          sandbox={sandboxed ? 'allow-scripts allow-same-origin allow-forms' : undefined}
        />
      </div>
    ) : (
      <EmptyPlaceholder label={translate(keys.pagebuilder.blocks.iframe.empty)} />
    ),
};
