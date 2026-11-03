import { useEffect, useState } from 'react';
import type { PageRead } from '../utils/api';
import { listPages, listTemplates } from '../utils/pagesApi';

export function usePageChoices(open: boolean) {
  const [templates, setTemplates] = useState<PageRead[]>([]);
  const [pages, setPages] = useState<PageRead[]>([]);
  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    // The signal is threaded into the requests, not just checked afterwards:
    // without it, closing the dialog left both fetches running to completion.
    void Promise.all([listTemplates(controller.signal), listPages(controller.signal)])
      .then(([t, p]) => {
        if (controller.signal.aborted) return;
        setTemplates(t.items);
        setPages(p.items);
      })
      // Not worth a banner: without these the dialog still creates a blank
      // page, which is the common case anyway.
      .catch(() => {});
    return () => controller.abort();
  }, [open]);

  return { templates, pages };
}
