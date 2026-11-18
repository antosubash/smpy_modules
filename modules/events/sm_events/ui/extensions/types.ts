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
  calendar: Readonly<{ id: string; name: string; default_timezone: string }>;
}>;

/** What a public page hands a plugin: the occurrence or event and the type's declared public
 *  fields, never the whole `extra`. */
export type PublicDetailProps = Readonly<{
  occurrence: Occurrence | null;
  event: Readonly<{ id: string; type: string; title: string }> | null;
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
