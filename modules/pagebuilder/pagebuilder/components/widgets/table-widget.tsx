import type { ComponentConfig } from '@puckeditor/core';
import { renderRichText } from './_internal/rich-text';

export type TableWidgetProps = {
  caption: string;
  headers: string;
  rows: string;
};

function parseDelimited(value: string): string[] {
  return value
    .split('|')
    .map((cell) => cell.trim())
    .filter((cell) => cell.length > 0);
}

export const TableWidget: ComponentConfig<TableWidgetProps> = {
  label: 'Table',
  fields: {
    caption: { type: 'text', label: 'Caption (accessibility)' },
    headers: { type: 'text', label: 'Headers (pipe-separated)' },
    rows: {
      type: 'textarea',
      label: 'Rows (one per line, columns pipe-separated)',
    },
  },
  defaultProps: {
    caption: '',
    headers: 'Name | Role | Email',
    rows: 'Jane Doe | Director | jane@example.com\nJohn Smith | Manager | john@example.com',
  },
  render: ({ caption, headers, rows }) => {
    const headerList = parseDelimited(headers);
    const rowList = rows
      .split(/\r?\n/)
      .map((line) => line.trim())
      .filter(Boolean)
      .map(parseDelimited);

    if (headerList.length === 0 && rowList.length === 0) {
      return (
        <div className="text-gray-500 text-center py-4">Add headers and rows in the editor.</div>
      );
    }

    return (
      <div className="container mx-auto py-6 overflow-x-auto">
        <table className="w-full border-collapse text-sm">
          {caption && (
            <caption className="text-sm text-gray-600 dark:text-gray-400 pb-3">
              {renderRichText(caption)}
            </caption>
          )}
          {headerList.length > 0 && (
            <thead>
              <tr className="bg-gray-50 dark:bg-gray-800">
                {headerList.map((header, idx) => (
                  // biome-ignore lint/suspicious/noArrayIndexKey: author-ordered array with no stable id; content repeats, so a content key collides
                  <th key={idx} scope="col" className="text-left font-semibold px-4 py-3 border-b">
                    {renderRichText(header)}
                  </th>
                ))}
              </tr>
            </thead>
          )}
          <tbody>
            {rowList.map((row, ridx) => (
              <tr
                // biome-ignore lint/suspicious/noArrayIndexKey: author-ordered array with no stable id; content repeats, so a content key collides
                key={ridx}
                className="border-b last:border-b-0 hover:bg-gray-50 dark:hover:bg-gray-900"
              >
                {row.map((cell, cidx) => (
                  // biome-ignore lint/suspicious/noArrayIndexKey: author-ordered array with no stable id; content repeats, so a content key collides
                  <td key={cidx} className="px-4 py-3">
                    {renderRichText(cell)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  },
};
