/**
 * Public entry point for the pagebuilder admin API client.
 *
 * The implementation is split across `types`, `request`, `pagesApi`, and
 * `mediaApi`; this barrel keeps `import { savePage } from '../utils/api'`
 * working for every consumer.
 */

export * from './mediaApi';
export * from './pagesApi';
export { BASE, CSRF_COOKIE, readCookie, request } from './request';
export * from './types';
