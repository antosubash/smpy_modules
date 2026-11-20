/** What a plugin may register and receive. Everything here is re-exported by the package's
 *  `index.ts` (the only path a plugin imports); every props type is `Readonly`, and none carries
 *  the session, the CSRF token or an internal API helper. */
import type { ComponentType } from 'react';
import type { DetailProps, EventChipProps, ToolbarSlotProps } from '../calendar/types';
import type { Occurrence } from '../utils/types-events';

export type LazyComponent<P> = () => Promise<{ default: ComponentType<P> }>;

export type ExtraValues = Readonly<Record<string, unknown>>;

/** A plugin's section of the event editor: the event's `extra`, edited as a whole. */
export type EditorSectionProps = Readonly<{
  extra: ExtraValues;
  onChange: (next: Record<string, unknown>) => void;
  /** The server's message per path under `extra` (`speaker.name`). */
  errors: Readonly<Record<string, string>>;
  readOnly: boolean;
  locale: string;
  eventId: string | null;
}>;

/** A plugin's settings form for a source enabled on a calendar. Never a secret: settings are
 *  stored in the clear. */
export type SourceSettingsProps = Readonly<{
  settings: ExtraValues;
  onChange: (next: Record<string, unknown>) => void;
  errors: Readonly<Record<string, string>>;
  /** The plugin's own short code per path, when it gave one (a section words it in the
   *  reader's language instead of showing the English `errors` message). */
  codes: Readonly<Record<string, string>>;
  calendar: Readonly<{ id: string; name: string; default_timezone: string }>;
}>;

/** What a public page hands a plugin: the occurrence or event and the type's declared public
 *  fields, never the whole `extra`. */
export type PublicDetailProps = Readonly<{
  occurrence: Occurrence | null;
  /** The event's own identity is withheld on the public site: its type and title only. */
  event: Readonly<{ type: string; title: string }> | null;
  publicExtra: ExtraValues;
  locale: string;
}>;

export type EventTypeRegistration = {
  id: string;
  Chip?: LazyComponent<EventChipProps>;
  Detail?: LazyComponent<DetailProps>;
  EditorSection?: LazyComponent<EditorSectionProps>;
  PublicDetail?: LazyComponent<PublicDetailProps>;
};
export type SourceRegistration = {
  id: string;
  Chip?: LazyComponent<EventChipProps>;
  Detail?: LazyComponent<DetailProps>;
  SettingsSection?: LazyComponent<SourceSettingsProps>;
  PublicDetail?: LazyComponent<PublicDetailProps>;
};
/** A registration provider's section of the event editor: it picks the provider's own target (a
 *  form's key) and is shown only for an event whose mode is built-in. `capacity` is the event's
 *  seat limit as typed (`null`: unlimited), so the provider can warn about a form that cannot
 *  guard it. */
export type RegistrationEditorProps = Readonly<{
  target: string | null;
  onChange: (target: string | null) => void;
  eventId: string | null;
  capacity: number | null;
  readOnly: boolean;
  /** The server's messages under `registration.` (`target`). */
  errors: Readonly<Record<string, string>>;
}>;
/** What a public event page hands a provider's panel: the target it registered, the event and
 *  the occurrence (never a request header or a viewer), and the page's language. */
export type RegistrationPanelProps = Readonly<{
  typeKey: string;
  eventId: string;
  occurrenceKey: string;
  locale: string;
}>;
export type RegistrationRegistration = {
  id: string;
  EditorSection?: LazyComponent<RegistrationEditorProps>;
  PublicPanel?: LazyComponent<RegistrationPanelProps>;
};
export type ToolbarSurface = 'console' | 'public';
export type ToolbarItemRegistration = {
  id: string;
  placement: 'start' | 'end';
  surfaces: ToolbarSurface[];
  Component: LazyComponent<ToolbarSlotProps>;
};

/** How one plugin source answered a read (the built-in source is never listed). */
export type SourceStatus = Readonly<{
  id: string;
  calendar_id: string;
  status: 'ok' | 'truncated' | 'failed' | 'timeout' | 'skipped' | 'not_installed';
  code: string | null;
}>;
