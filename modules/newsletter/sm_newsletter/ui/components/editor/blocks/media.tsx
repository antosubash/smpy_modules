/**
 * Image, Button, Divider and Spacer.
 *
 * Fields and limits match `content/blocks.py` (Task 4). The image's address is
 * a URL (ruling R3); `MediaField` adds a picker over pagebuilder's media when
 * pagebuilder is available, which is why the image block is built per
 * capability rather than being a constant.
 */

import type { ComponentConfig } from '@puckeditor/core';

import { keys, useT } from '../../../utils/i18n';
import { mediaField } from '../MediaField';

import { ACCENT, type Align, block, FONT, MUTED, RULE } from './email';

const copy = keys.newsletter.blocks;

export interface ImageProps {
  src: string;
  alt: string;
  href?: string;
  width: number;
}

function EmptyImage() {
  const { t } = useT();
  return (
    <div
      style={{
        border: `1px dashed ${MUTED}`,
        color: MUTED,
        fontFamily: FONT,
        padding: 32,
        textAlign: 'center',
      }}
    >
      {t(copy.image.empty)}
    </div>
  );
}

export function imageBlock(canPick: boolean): ComponentConfig<ImageProps> {
  return {
    label: copy.image.label,
    fields: {
      src: mediaField(copy.image.src, canPick),
      alt: { type: 'text', label: copy.image.alt },
      href: { type: 'text', label: copy.image.href },
      // `content/blocks.py`: 1-600.
      width: { type: 'number', label: copy.image.width, min: 1, max: 600 },
    },
    defaultProps: { src: '', alt: '', width: 600 },
    render: ({ src, alt, width }) => (
      <div style={{ ...block, textAlign: 'center' }}>
        {src ? (
          <img
            src={src}
            alt={alt}
            width={width}
            style={{ display: 'inline-block', maxWidth: '100%', height: 'auto', border: 0 }}
          />
        ) : (
          <EmptyImage />
        )}
      </div>
    ),
  };
}

export interface ButtonProps {
  label: string;
  href: string;
  align: Align;
}

export const ButtonBlock: ComponentConfig<ButtonProps> = {
  label: copy.button.label,
  fields: {
    // `content/blocks.py`: 1-80 characters.
    label: { type: 'text', label: copy.button.text },
    href: { type: 'text', label: copy.common.link },
    align: {
      type: 'radio',
      label: copy.common.align,
      options: [
        { label: copy.common.align_left, value: 'left' },
        { label: copy.common.align_center, value: 'center' },
        { label: copy.common.align_right, value: 'right' },
      ],
    },
  },
  defaultProps: { label: 'Read more', href: '/', align: 'center' },
  render: ({ label, align }) => (
    <div style={{ ...block, textAlign: align }}>
      {/* Not a link on the canvas: clicking it should select the block. */}
      <span
        style={{
          display: 'inline-block',
          background: ACCENT,
          color: '#ffffff',
          borderRadius: 6,
          fontFamily: FONT,
          fontSize: 16,
          padding: '12px 24px',
          fontWeight: 700,
          textDecoration: 'none',
        }}
      >
        {label}
      </span>
    </div>
  ),
};

export type DividerProps = Record<string, never>;

export const DividerBlock: ComponentConfig<DividerProps> = {
  label: copy.divider.label,
  fields: {},
  render: () => (
    <div style={block}>
      <hr style={{ border: 0, borderTop: `1px solid ${RULE}`, margin: '8px 0' }} />
    </div>
  ),
};

export interface SpacerProps {
  size: 'sm' | 'md' | 'lg';
}

const SPACER_HEIGHT = { sm: 8, md: 16, lg: 32 } as const;

export const SpacerBlock: ComponentConfig<SpacerProps> = {
  label: copy.spacer.label,
  fields: {
    size: {
      type: 'select',
      label: copy.spacer.size,
      options: [
        { label: copy.spacer.size_sm, value: 'sm' },
        { label: copy.spacer.size_md, value: 'md' },
        { label: copy.spacer.size_lg, value: 'lg' },
      ],
    },
  },
  defaultProps: { size: 'md' },
  render: ({ size }) => <div style={{ height: SPACER_HEIGHT[size] ?? SPACER_HEIGHT.md }} />,
};
