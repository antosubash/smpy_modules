import { keys, translate } from './i18n';

const MESSAGES: Record<string, string> = {
  'Route patterns must start with /': keys.analytics.validation.route_prefix,
  'Route patterns must be at most 500 characters': keys.analytics.validation.route_length,
  'Use literal path segments or :name placeholders': keys.analytics.validation.route_segments,
  'Expected an exact http(s) origin without a path': keys.analytics.validation.origin,
  'Invalid event or property name (max 50 characters, 20 properties)':
    keys.analytics.validation.event_names,
  'Unsupported UTM parameter': keys.analytics.validation.utm,
};

export function validationMessage(item: {
  msg: string;
  type?: string;
  ctx?: { min_length?: number; max_length?: number };
}): string {
  const message = item.msg.replace(/^Value error, /, '');
  if (MESSAGES[message]) return translate(MESSAGES[message]);
  if (item.type === 'string_too_short')
    return translate(keys.analytics.validation.text_short, { count: item.ctx?.min_length });
  if (item.type === 'string_too_long')
    return translate(keys.analytics.validation.text_long, { count: item.ctx?.max_length });
  if (item.type === 'too_long')
    return translate(keys.analytics.validation.items_long, { count: item.ctx?.max_length });
  if (item.type === 'too_short')
    return translate(keys.analytics.validation.items_short, { count: item.ctx?.min_length });
  return message;
}
