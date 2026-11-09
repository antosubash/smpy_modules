import { router } from '@inertiajs/react';
import { useEffect, useRef, useState } from 'react';
import { geoStatus, listProperties, loadReport } from './api';
import type { Filters, GeoStatus, Property, Report } from './types';

const today = () => new Date().toISOString().slice(0, 10);
export function useAnalytics() {
  const [properties, setProperties] = useState<Property[]>([]);
  const [selected, setSelected] = useState('');
  const [filters, setFilters] = useState<Filters>(() => ({
    start: new Date(Date.now() - 6 * 86400000).toISOString().slice(0, 10),
    end: today(),
    path: '',
    event: '',
    country: '',
    region: '',
    city: '',
  }));
  const scope = JSON.stringify([selected, filters]);
  const [snapshot, setSnapshot] = useState<{ scope: string; data: Report } | null>(null);
  const report = snapshot?.scope === scope ? snapshot.data : null;
  const [geo, setGeo] = useState<GeoStatus | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [refresh, setRefresh] = useState(0);
  const [listRefresh, setListRefresh] = useState(0);
  const reportPending = useRef(false);
  const reload = () => {
    setListRefresh((n) => n + 1);
    setRefresh((n) => n + 1);
  };
  // biome-ignore lint/correctness/useExhaustiveDependencies: listRefresh triggers a fresh property list.
  useEffect(() => {
    const controller = new AbortController();
    setError('');
    Promise.all([listProperties(controller.signal), geoStatus(controller.signal)])
      .then(([items, status]) => {
        if (controller.signal.aborted) return;
        setProperties(items);
        setGeo(status.geo);
        setSelected((current) =>
          items.some((item) => item.id === current) ? current : (items[0]?.id ?? ''),
        );
        setLoading(false);
      })
      .catch((reason: Error) => {
        if (!controller.signal.aborted) {
          setError(reason.message);
          setLoading(false);
        }
      });
    return () => {
      controller.abort();
    };
  }, [listRefresh]);
  // biome-ignore lint/correctness/useExhaustiveDependencies: scope includes selected and filters; refresh triggers polling.
  useEffect(() => {
    if (!selected) return;
    const controller = new AbortController();
    setLoading(true);
    setError('');
    reportPending.current = true;
    loadReport(selected, filters, controller.signal)
      .then((next) => {
        if (!controller.signal.aborted) setSnapshot({ scope, data: next });
      })
      .catch((reason: Error) => {
        if (!controller.signal.aborted) setError(reason.message);
      })
      .finally(() => {
        if (!controller.signal.aborted) {
          reportPending.current = false;
          setLoading(false);
        }
      });
    return () => {
      controller.abort();
      reportPending.current = false;
    };
  }, [scope, refresh]);
  useEffect(
    () =>
      router.on('navigate', () => {
        setSelected('');
        setProperties([]);
        setSnapshot(null);
        setLoading(true);
        setListRefresh((n) => n + 1);
      }),
    [],
  );
  useEffect(() => {
    const timer = setInterval(() => {
      if (document.visibilityState === 'visible' && !reportPending.current)
        setRefresh((n) => n + 1);
    }, 30000);
    return () => clearInterval(timer);
  }, []);
  return {
    properties,
    selected,
    setSelected,
    filters,
    setFilters,
    report,
    geo,
    error,
    loading,
    reload,
  };
}
