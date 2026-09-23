import { EMPTY_CELL } from '../../utils/values';
import { useMediaApi } from './MediaApiContext';
import { MediaPreview } from './MediaPreview';

const MAX_RAW = 24;

/** A `media` value in the record list: a small thumbnail for an image, a
 *  file icon and the name otherwise, when the page has a media library to
 *  ask — and the stored id (or legacy URL) as text when it has none, which is
 *  all the value is without one. The wrapper carries the width cap and the
 *  test id wherever the column sits — any chooser column, table or cards. */
export function MediaCell({ value }: { value: unknown }) {
  return (
    <span className="block min-w-0 max-w-48" data-testid="records-media-cell">
      <MediaCellValue value={value} />
    </span>
  );
}

function MediaCellValue({ value }: { value: unknown }) {
  const api = useMediaApi();
  const text = typeof value === 'string' ? value.trim() : '';
  if (!text) return <span className="text-muted-foreground">{EMPTY_CELL}</span>;
  if (!api) {
    return (
      <span className="font-mono text-xs" title={text} data-testid="records-media-raw">
        {text.length > MAX_RAW ? `${text.slice(0, MAX_RAW)}…` : text}
      </span>
    );
  }
  return <MediaPreview api={api} value={text} variant="cell" />;
}
