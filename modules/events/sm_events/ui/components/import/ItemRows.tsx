import { Badge } from '@simple-module-py/ui/components/ui/badge';
import { Button } from '@simple-module-py/ui/components/ui/button';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@simple-module-py/ui/components/ui/table';
import type { Filter } from '../../hooks/useImport';
import { type ImportItem, type ItemPage, reasonText } from '../../utils/api-import';
import { keys, useT } from '../../utils/i18n';
import { Name } from '../../utils/isolate';

const WRAP = 'max-w-xs whitespace-normal [overflow-wrap:anywhere]';

/** An item's start as its own wall clock, with its zone: what the file meant. */
function when(item: ImportItem): string {
  if (!item.local_start) return '';
  const text = item.all_day ? item.local_start : item.local_start.replace('T', ' ');
  return item.all_day || !item.timezone ? text : `${text} (${item.timezone})`;
}

/** The items of a preview or a result, as a table. Titles and identifiers come from a file: they
 *  are rendered as text, isolated, never interpreted. A column carries the verdict (before) or
 *  the outcome (after), and the reasons in words. */
export function ItemRows({
  page,
  filter,
  setFilter,
  after,
}: {
  page: ItemPage | null;
  filter: Filter;
  setFilter: (next: Filter) => void;
  /** Show the outcome of each item (a finished import) rather than its verdict. */
  after: boolean;
}) {
  const { t } = useT();
  const copy = keys.events.import.preview;
  const outcome = keys.events.import.outcome;
  const lookup = (table: object, code: string) => (table as Record<string, string>)[code];
  if (!page || page.items.length === 0) {
    return <p className="text-sm text-muted-foreground dark:text-zinc-400">{t(copy.empty)}</p>;
  }
  const current = filter.page ?? 1;
  const last = Math.max(1, Math.ceil(page.total / page.page_size));
  return (
    <div className="space-y-2">
      <div className="max-w-full overflow-x-auto">
        <Table aria-label={t(copy.title)}>
          <TableHeader>
            <TableRow>
              <TableHead>{t(copy.col_title)}</TableHead>
              <TableHead>{t(copy.col_start)}</TableHead>
              <TableHead>{t(copy.col_what)}</TableHead>
              <TableHead>{t(copy.col_why)}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {page.items.map((item) => {
              const reasons = [
                ...(item.outcome_code ? [item.outcome_code] : item.reason ? [item.reason] : []),
                ...item.notes,
              ];
              const label =
                after && item.outcome
                  ? t(lookup(outcome, item.outcome) ?? outcome.failed)
                  : t(lookup(copy.verdict, item.verdict) ?? copy.verdict.skip);
              return (
                <TableRow key={item.seq} data-testid="events-import-row">
                  <TableCell className={`min-w-48 ${WRAP}`}>
                    <Name>{item.title}</Name>
                    {after && item.event_id && (
                      <a
                        href={`/admin/events/edit/${item.event_id}`}
                        className="ml-2 text-sm underline"
                      >
                        {t(keys.events.import.result.open)}
                      </a>
                    )}
                  </TableCell>
                  <TableCell className="whitespace-nowrap">
                    {when(item)}
                    {item.recurring && <Badge variant="outline">{t(copy.repeats)}</Badge>}
                    {item.all_day && <Badge variant="outline">{t(copy.all_day)}</Badge>}
                  </TableCell>
                  <TableCell>
                    <Badge
                      variant={
                        item.verdict === 'skip' || item.verdict === 'unchanged'
                          ? 'secondary'
                          : 'default'
                      }
                    >
                      {label}
                    </Badge>
                  </TableCell>
                  <TableCell className={WRAP}>
                    {reasons.map((code) => (
                      <p key={code} className="text-sm">
                        {reasonText(code)}
                      </p>
                    ))}
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </div>
      <div className="flex items-center gap-2 text-sm text-muted-foreground dark:text-zinc-400">
        <span>{t(copy.more, { shown: page.items.length, total: page.total })}</span>
        {last > 1 && (
          <>
            <Button
              type="button"
              size="sm"
              variant="outline"
              disabled={current <= 1}
              onClick={() => setFilter({ ...filter, page: current - 1 })}
            >
              ‹
            </Button>
            <Button
              type="button"
              size="sm"
              variant="outline"
              disabled={current >= last}
              onClick={() => setFilter({ ...filter, page: current + 1 })}
            >
              {t(copy.next)}
            </Button>
          </>
        )}
      </div>
    </div>
  );
}
