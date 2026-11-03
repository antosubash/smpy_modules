export type EmptyPlaceholderProps = {
  label: string;
};

/**
 * Dashed-border placeholder shown when a media/embed widget has no content
 * to render (no source, no slides, …).
 */
export function EmptyPlaceholder({ label }: EmptyPlaceholderProps) {
  return (
    <div className="border-2 border-dashed border-gray-300 rounded-lg p-8 text-center text-gray-500">
      {label}
    </div>
  );
}
