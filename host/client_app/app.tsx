import { createInertiaApp, router } from '@inertiajs/react';
import { configureI18n, updateI18n } from '@simple-module-py/i18n';
import { createRoot } from 'react-dom/client';
import { resolvePage } from './pages';

type I18nBlock = {
  locale: string;
  supportedLocales?: string[];
  messages: Record<string, string> | null;
};

createInertiaApp({
  resolve: async (name) => {
    return await resolvePage(name);
  },
  setup({ el, App, props }) {
    const initial = (props.initialPage.props as { i18n?: I18nBlock }).i18n;
    configureI18n({
      locale: initial?.locale ?? 'en',
      messages: initial?.messages ?? {},
    });
    let activeLocale = initial?.locale ?? null;
    router.on('success', (event) => {
      const block = (event.detail.page.props as { i18n?: I18nBlock }).i18n;
      if (!block) return;
      if (block.locale !== activeLocale && block.messages) {
        updateI18n({ locale: block.locale, messages: block.messages });
        activeLocale = block.locale;
      }
    });
    createRoot(el).render(<App {...props} />);
  },
  progress: {
    color: '#4B5563',
    delay: 150,
  },
});
