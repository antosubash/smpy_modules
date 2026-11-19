/** How to register, on the public event page. `external` is a link; `builtin` hands the page's
 *  event and occurrence to the registration provider's own panel (lazy, in a boundary, public
 *  code only). A series' bare page has no occurrence to register for, so it lists a few dates to
 *  choose from instead. A provider with no panel registered renders nothing: the page around it
 *  is unaffected. The page's props are cached and the same for everyone, so this holds nothing
 *  about seats: the panel asks the provider's route, live. */
import { useEventExtensions } from '../extensions/load';
import { PluginBoundary } from '../extensions/PluginBoundary';
import { registrationFor } from '../extensions/registry';
import { localSpan } from '../utils/datetime';
import { keys, useT } from '../utils/i18n';
import type { PublicRegistration } from './types';

type Props = { registration: PublicRegistration; locale: string };

export function RegistrationSlot({ registration, locale }: Props) {
  const { t } = useT();
  const copy = keys.events.public.event;
  useEventExtensions(); // starts the lazy load; the registry is read after it
  const Panel =
    registration.mode === 'builtin'
      ? registrationFor(registration.provider ?? '')?.PublicPanel
      : undefined;
  if (registration.mode === 'external' && registration.url) {
    return (
      <a href={registration.url} rel="noopener nofollow" className="font-medium underline">
        {t(copy.register)}
      </a>
    );
  }
  if (registration.mode !== 'builtin' || !registration.target || !Panel) return null;
  const key = registration.occurrence_key;
  if (key === null) {
    if (registration.upcoming.length === 0) return null;
    return (
      <section
        aria-labelledby="register-pick"
        className="space-y-2"
        data-testid="registration-dates"
      >
        <h2 id="register-pick" className="font-semibold">
          {t(copy.register_pick)}
        </h2>
        <ul className="space-y-1">
          {registration.upcoming.map((n) => (
            <li key={n.url}>
              <a href={n.url} className="underline">
                {localSpan(n.start_local, n.end_local, locale)}
              </a>
            </li>
          ))}
        </ul>
      </section>
    );
  }
  return (
    <PluginBoundary name={`${registration.provider}/public-registration`} fallback={null}>
      <Panel
        typeKey={registration.target}
        eventId={key.split(':')[0] ?? ''}
        occurrenceKey={key}
        locale={locale}
      />
    </PluginBoundary>
  );
}
