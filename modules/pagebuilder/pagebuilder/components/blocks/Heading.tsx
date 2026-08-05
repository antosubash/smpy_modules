import type { ComponentConfig } from '@puckeditor/core';

interface HeadingProps {
  text: string;
  level: 'h1' | 'h2' | 'h3' | 'h4' | 'h5' | 'h6';
  align: 'left' | 'center' | 'right';
}

const sizeClass: Record<HeadingProps['level'], string> = {
  h1: 'text-5xl font-bold',
  h2: 'text-4xl font-bold',
  h3: 'text-3xl font-semibold',
  h4: 'text-2xl font-semibold',
  h5: 'text-xl font-medium',
  h6: 'text-lg font-medium',
};

export const HeadingBlock: ComponentConfig<HeadingProps> = {
  label: 'Heading',
  fields: {
    text: { type: 'text' },
    level: {
      type: 'select',
      options: [
        { label: 'H1', value: 'h1' },
        { label: 'H2', value: 'h2' },
        { label: 'H3', value: 'h3' },
        { label: 'H4', value: 'h4' },
        { label: 'H5', value: 'h5' },
        { label: 'H6', value: 'h6' },
      ],
    },
    align: {
      type: 'radio',
      options: [
        { label: 'Left', value: 'left' },
        { label: 'Center', value: 'center' },
        { label: 'Right', value: 'right' },
      ],
    },
  },
  defaultProps: { text: 'Heading', level: 'h2', align: 'left' },
  render: ({ text, level, align }) => {
    const Tag = level;
    return <Tag className={`${sizeClass[level]} text-${align} my-4`}>{text}</Tag>;
  },
};
