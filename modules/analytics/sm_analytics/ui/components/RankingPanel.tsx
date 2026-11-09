import { Button } from '@simple-module-py/ui/components/ui/button';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@simple-module-py/ui/components/ui/tabs';
import { useId, useState } from 'react';
import { keys, useT } from '../utils/i18n';
import type { Breakdown, Dimension } from '../utils/types';

export type RankingDimension = Dimension | `property:${string}`;
export function RankingPanel({
  title,
  groups,
  onFilter,
  help,
}: {
  title: string;
  groups: { dimension: RankingDimension; rows: Breakdown[] }[];
  onFilter: (dimension: RankingDimension, value: string) => void;
  help?: string;
}) {
  const { t, locale } = useT();
  const heading = useId();
  const [selected, setSelected] = useState(groups[0].dimension);
  const [expanded, setExpanded] = useState(false);
  const active = groups.find((group) => group.dimension === selected) ?? groups[0];
  const label = (dimension: RankingDimension) =>
    dimension.startsWith('property:')
      ? t(keys.analytics.event_property, { name: dimension.slice(9) })
      : t(keys.analytics.dimensions[dimension as Dimension]);
  const maximum = Math.max(1, ...active.rows.map((row) => row.count));
  const actionable = ['path', 'event', 'country', 'region', 'city'].includes(active.dimension);
  const content = (
    <>
      {active.rows.length === 0 ? (
        <p className="py-8 text-sm text-muted-foreground">{t(keys.analytics.no_data)}</p>
      ) : (
        <table className="w-full table-fixed text-sm">
          <caption className="sr-only">{label(active.dimension)}</caption>
          <thead>
            <tr className="text-left text-muted-foreground">
              <th className="pb-3 font-normal">{t(keys.analytics.value)}</th>
              <th className="w-20 pb-3 text-right font-normal">{t(keys.analytics.count)}</th>
            </tr>
          </thead>
          <tbody>
            {active.rows.slice(0, expanded ? active.rows.length : 10).map((row) => {
              const name = row.value ? row.label : t(keys.analytics.unknown);
              return (
                <tr key={row.value}>
                  <td className="py-1 pr-3">
                    <div className="relative min-w-0 rounded-sm">
                      <span
                        aria-hidden="true"
                        className="absolute inset-y-0 left-0 rounded-sm bg-blue-500/10 dark:bg-blue-400/15"
                        style={{ width: `${(row.count / maximum) * 100}%` }}
                      />
                      {actionable ? (
                        <button
                          type="button"
                          className="relative block w-full break-words rounded-sm px-2 py-2 text-left [overflow-wrap:anywhere] hover:text-blue-600 focus-visible:outline-ring dark:hover:text-blue-400"
                          onClick={() => onFilter(active.dimension, row.value || '__unknown__')}
                        >
                          {name}
                        </button>
                      ) : (
                        <span className="relative block break-words px-2 py-2 [overflow-wrap:anywhere]">
                          {name}
                        </span>
                      )}
                    </div>
                  </td>
                  <td className="text-right tabular-nums">{row.count.toLocaleString(locale)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
      {active.rows.length > 10 && (
        <Button variant="ghost" size="sm" className="mt-3" onClick={() => setExpanded(!expanded)}>
          {t(expanded ? keys.analytics.ui.show_less : keys.analytics.ui.show_more)}
        </Button>
      )}
    </>
  );
  return (
    <section aria-labelledby={heading} className="min-w-0 rounded-lg border bg-card p-4 sm:p-5">
      <h2 id={heading} className="font-semibold">
        {title}
      </h2>
      {help && <p className="mt-1 text-sm text-muted-foreground">{help}</p>}
      {groups.length === 1 ? (
        <div className="mt-4">{content}</div>
      ) : (
        <Tabs
          value={active.dimension}
          onValueChange={(value) => {
            setSelected(value as RankingDimension);
            setExpanded(false);
          }}
          className="mt-3 min-w-0 gap-4"
        >
          <div className="min-w-0 overflow-x-auto pb-1">
            <TabsList variant="line" aria-label={title}>
              {groups.map(({ dimension }) => (
                <TabsTrigger key={dimension} value={dimension}>
                  {label(dimension)}
                </TabsTrigger>
              ))}
            </TabsList>
          </div>
          {groups.map(({ dimension }) => (
            <TabsContent key={dimension} value={dimension}>
              {dimension === active.dimension ? content : null}
            </TabsContent>
          ))}
        </Tabs>
      )}
    </section>
  );
}
