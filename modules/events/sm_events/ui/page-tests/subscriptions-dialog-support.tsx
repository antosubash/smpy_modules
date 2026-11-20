// Shared by the Subscriptions dialog tests (the module mocks stay in each test file).
import { calendar, flush, stubFetch } from './support';
import { click, mount } from './test-dom';

export const LIST = '/api/events/calendars/c1/subscriptions';
export const sub = (over = {}) => ({
  id: 's1',
  calendar_id: 'c1',
  url_display: 'https://feeds.example.test/…',
  label: 'Holidays',
  color: null,
  refresh_minutes: null,
  effective_refresh_minutes: 60,
  public: false,
  status: 'ok',
  error_code: null,
  last_http_status: null,
  last_fetched_at: '2026-11-19T10:00:00Z',
  last_ok_at: '2026-11-19T10:00:00Z',
  next_fetch_at: '2026-11-19T11:00:00Z',
  consecutive_failures: 0,
  item_count: 214,
  last_counts: { stored: 214, skipped: 12, reasons: { unknown_timezone: 10, unsupported_rule: 2 } },
  may_use_internal_addresses: false,
  version: 'v1',
  ...over,
});

type Props = { calendar?: Parameters<typeof calendar>[0]; canPublish?: boolean };
export async function open(routes: Record<string, unknown>, props: Props = {}) {
  const { SubscriptionsDialog } = await import('../components/subscriptions/SubscriptionsDialog');
  const calls = stubFetch(routes);
  const view = await mount(
    <SubscriptionsDialog
      calendar={calendar(props.calendar)}
      canPublish={props.canPublish ?? false}
      defaultMinutes={60}
    />,
  );
  await click(view.find('[data-testid="events-subscriptions"]'));
  await flush(50);
  return { calls, view };
}
export const dialog = () => document.querySelector('[data-testid="events-subscriptions-dialog"]');
export const text = () => dialog()?.textContent ?? '';
export const button = (label: string) =>
  [...document.querySelectorAll('button')].find((b) => b.textContent?.includes(label));
