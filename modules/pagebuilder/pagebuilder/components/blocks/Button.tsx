import type { ComponentConfig } from '@puckeditor/core';

interface ButtonProps {
  label: string;
  href: string;
  variant: 'primary' | 'secondary' | 'ghost';
  target: '_self' | '_blank';
}

const variantClass: Record<ButtonProps['variant'], string> = {
  primary: 'bg-blue-600 hover:bg-blue-700 text-white',
  secondary: 'bg-gray-200 hover:bg-gray-300 text-gray-900',
  ghost: 'bg-transparent hover:bg-gray-100 text-gray-900 border border-gray-300',
};

export const ButtonBlock: ComponentConfig<ButtonProps> = {
  fields: {
    label: { type: 'text' },
    href: { type: 'text' },
    variant: {
      type: 'select',
      options: [
        { label: 'Primary', value: 'primary' },
        { label: 'Secondary', value: 'secondary' },
        { label: 'Ghost', value: 'ghost' },
      ],
    },
    target: {
      type: 'radio',
      options: [
        { label: 'Same tab', value: '_self' },
        { label: 'New tab', value: '_blank' },
      ],
    },
  },
  defaultProps: { label: 'Click me', href: '#', variant: 'primary', target: '_self' },
  render: ({ label, href, variant, target }) => (
    <a
      href={href}
      target={target}
      rel={target === '_blank' ? 'noopener noreferrer' : undefined}
      className={`inline-block px-4 py-2 rounded font-medium transition-colors ${variantClass[variant]}`}
    >
      {label}
    </a>
  ),
};
