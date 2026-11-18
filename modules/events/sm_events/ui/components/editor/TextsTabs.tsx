import { Button } from '@simple-module-py/ui/components/ui/button';
import { Checkbox } from '@simple-module-py/ui/components/ui/checkbox';
import { FieldError } from '@simple-module-py/ui/components/ui/field';
import { Input } from '@simple-module-py/ui/components/ui/input';
import { Label } from '@simple-module-py/ui/components/ui/label';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@simple-module-py/ui/components/ui/tabs';
import { Textarea } from '@simple-module-py/ui/components/ui/textarea';
import type { TextForm } from '../../utils/event-form';
import { fieldErrorId, invalidProps } from '../../utils/field-errors';
import { keys, useT } from '../../utils/i18n';
import { languageName } from '../../utils/language';
import { RichTextField } from './RichTextField';

type Errors = Record<string, string>;

function Line({
  id,
  label,
  value,
  error,
  disabled,
  placeholder,
  maxLength,
  multiline,
  onChange,
}: {
  id: string;
  label: string;
  value: string;
  error?: string;
  disabled: boolean;
  placeholder?: string;
  maxLength: number;
  multiline?: boolean;
  onChange: (value: string) => void;
}) {
  const Control = multiline ? Textarea : Input;
  return (
    <div className="grid gap-2">
      <Label htmlFor={id}>{label}</Label>
      <Control
        id={id}
        disabled={disabled}
        maxLength={maxLength}
        placeholder={placeholder}
        value={value}
        {...invalidProps(id, error)}
        onChange={(e) => onChange(e.target.value)}
      />
      <FieldError id={fieldErrorId(id)}>{error}</FieldError>
    </div>
  );
}

/** One tab per content language. The default language always has a text; another
 *  one is added or removed (removing sends `null`, which deletes it). */
export function TextsTabs({
  locales,
  defaultLocale,
  texts,
  tab,
  errors,
  disabled,
  onTab,
  onText,
  onEdit,
}: {
  locales: readonly string[];
  defaultLocale: string;
  texts: Record<string, TextForm>;
  tab: string;
  errors: Errors;
  disabled: boolean;
  onTab: (locale: string) => void;
  onText: (locale: string, patch: Partial<TextForm>) => void;
  onEdit: (path: string) => void;
}) {
  const { t, locale: ui } = useT();
  const copy = keys.events.texts;
  return (
    <Tabs value={tab} onValueChange={onTab}>
      <TabsList aria-label={t(copy.legend)} className="h-auto flex-wrap">
        {locales.map((code) => (
          <TabsTrigger key={code} value={code}>
            {texts[code]?.present
              ? languageName(code, ui)
              : t(copy.tab_missing, { language: languageName(code, ui) })}
          </TabsTrigger>
        ))}
      </TabsList>
      {/* One panel for the selected language: its content changes in the commit that
          changes the tab, so focus can move to a field in a language that was hidden. */}
      {[tab].map((code) => {
        const text = texts[code];
        if (!text) return null;
        const at = (name: string) => `texts.${code}.${name}`;
        const id = (name: string) => `text-${code}-${name}`;
        const set = (patch: Partial<TextForm>, name?: string) => {
          onText(code, patch);
          if (name) onEdit(at(name));
        };
        const seoError = Boolean(errors[at('seo_title')] || errors[at('seo_description')]);
        const line = (
          name: 'title' | 'slug' | 'summary' | 'seo_title' | 'seo_description',
          label: string,
          max: number,
          extra = {},
        ) => (
          <Line
            id={id(name)}
            label={label}
            value={text[name]}
            error={errors[at(name)]}
            disabled={disabled}
            maxLength={max}
            onChange={(value) => set({ [name]: value }, name)}
            {...extra}
          />
        );
        return (
          <TabsContent key={code} value={code} lang={code} className="grid gap-4 pt-2">
            {!text.present ? (
              <div className="grid gap-2">
                <p className="text-sm text-muted-foreground">{t(copy.missing_hint)}</p>
                <div>
                  <Button
                    type="button"
                    variant="outline"
                    disabled={disabled}
                    onClick={() => set({ present: true })}
                  >
                    {t(copy.add_language, { language: languageName(code, ui) })}
                  </Button>
                </div>
              </div>
            ) : (
              <>
                {line('title', t(copy.title), 300)}
                {line('slug', t(copy.slug), 200, { placeholder: t(copy.slug_placeholder) })}
                {line('summary', t(copy.summary), 1000, { multiline: true })}
                <RichTextField
                  id={id('description')}
                  label={t(copy.description)}
                  value={text.description}
                  readOnly={disabled}
                  lang={code}
                  error={errors[at('description')]}
                  onChange={(html) => set({ description: html })}
                />
                <details className="grid gap-3" open={seoError ? true : undefined}>
                  <summary className="cursor-pointer text-sm font-medium">{t(copy.seo)}</summary>
                  <div className="mt-3 grid gap-4">
                    {line('seo_title', t(copy.seo_title), 300)}
                    {line('seo_description', t(copy.seo_description), 500, { multiline: true })}
                    <div className="flex items-center gap-2">
                      <Checkbox
                        id={id('noindex')}
                        disabled={disabled}
                        checked={text.noindex}
                        onCheckedChange={(on) => set({ noindex: on === true })}
                      />
                      <Label htmlFor={id('noindex')}>{t(copy.noindex)}</Label>
                    </div>
                  </div>
                </details>
                {code !== defaultLocale && (
                  <div>
                    <Button
                      type="button"
                      variant="outline"
                      disabled={disabled}
                      onClick={() => set({ ...blank(), present: false })}
                    >
                      {t(copy.remove_language)}
                    </Button>
                  </div>
                )}
              </>
            )}
          </TabsContent>
        );
      })}
    </Tabs>
  );
}

const blank = (): Partial<TextForm> => ({
  title: '',
  slug: '',
  summary: '',
  description: '',
  seo_title: '',
  seo_description: '',
  noindex: false,
});
