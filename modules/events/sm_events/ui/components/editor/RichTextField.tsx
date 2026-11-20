import { Button } from '@simple-module-py/ui/components/ui/button';
import { FieldError } from '@simple-module-py/ui/components/ui/field';
import { Input } from '@simple-module-py/ui/components/ui/input';
import { Label } from '@simple-module-py/ui/components/ui/label';
import { type ClipboardEvent, useLayoutEffect, useRef, useState } from 'react';
import { fieldErrorId, invalidProps } from '../../utils/field-errors';
import { keys, useT } from '../../utils/i18n';
import { cleanFragment, cleanHtml, normalHtml, safeHref } from '../../utils/richtext';

const BOX =
  'min-h-40 rounded-md border bg-background p-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring ' +
  '[&_p]:my-2 [&_h2]:text-xl [&_h2]:font-semibold [&_h3]:text-lg [&_h3]:font-semibold ' +
  '[&_ul]:list-disc [&_ul]:pl-6 [&_ol]:list-decimal [&_ol]:pl-6 [&_a]:underline ' +
  '[&_blockquote]:border-l-4 [&_blockquote]:pl-3';

/** `document.execCommand` is deprecated but is still how every browser edits a
 *  contentEditable; the result is re-cleaned on every change, so a browser's own
 *  markup (`<div>`, `<span style>`) never reaches the form. */
function exec(command: string, argument?: string): void {
  if (typeof document.execCommand !== 'function') return;
  if (argument === undefined) document.execCommand(command);
  else document.execCommand(command, false, argument);
}

const headingCommand = (): string => {
  const block =
    typeof document.queryCommandValue === 'function'
      ? document.queryCommandValue('formatBlock')
      : '';
  return /^h2$/i.test(String(block)) ? 'p' : 'h2';
};

/** A small rich-text field with no dependency. The value is the allowed HTML
 *  the server already cleaned; it is cleaned again before it enters the page
 *  and before it leaves the field, and pasted content is cleaned before it is
 *  inserted. A read-only description is shown in a sandboxed frame, the way
 *  the console shows other sanitised HTML. */
export function RichTextField({
  id,
  label,
  value,
  onChange,
  readOnly = false,
  error,
  lang,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (html: string) => void;
  readOnly?: boolean;
  error?: string;
  lang?: string;
}) {
  const { t } = useT();
  const copy = keys.events.richtext;
  const editor = useRef<HTMLDivElement>(null);
  const shown = useRef<string | null>(null);
  /** What the parent last held, in the normal form: the baseline an unedited blur matches. */
  const sent = useRef(normalHtml(value));
  const saved = useRef<Range | null>(null);
  const [linking, setLinking] = useState(false);
  const [href, setHref] = useState('');
  const [linkError, setLinkError] = useState(false);

  // Load what the parent holds, unless it is what the field itself just emitted:
  // replacing the content while someone types would move their caret.
  useLayoutEffect(() => {
    const el = editor.current;
    if (readOnly || !el) {
      shown.current = null;
      return;
    }
    if (shown.current === value) return;
    el.replaceChildren(cleanFragment(value));
    shown.current = value;
    sent.current = normalHtml(value);
  }, [value, readOnly]);

  function emit() {
    const el = editor.current;
    if (!el) return;
    const html = normalHtml(el.innerHTML);
    shown.current = html;
    // Focusing and leaving without an edit serialises the same content a
    // different way: that is not a change.
    if (html === sent.current) return;
    sent.current = html;
    onChange(html);
  }
  function run(command: string, argument?: string) {
    editor.current?.focus();
    exec(command, argument);
    emit();
  }
  function paste(e: ClipboardEvent<HTMLDivElement>) {
    e.preventDefault();
    const html = e.clipboardData.getData('text/html');
    if (html) run('insertHTML', cleanHtml(html));
    else run('insertText', e.clipboardData.getData('text/plain'));
  }
  function openLink() {
    const selection = window.getSelection();
    saved.current =
      selection && selection.rangeCount > 0 ? selection.getRangeAt(0).cloneRange() : null;
    setHref('');
    setLinkError(false);
    setLinking(true);
  }
  function applyLink() {
    const safe = safeHref(href);
    if (!safe) {
      setLinkError(true);
      return;
    }
    editor.current?.focus();
    const selection = window.getSelection();
    if (saved.current && selection) {
      selection.removeAllRanges();
      selection.addRange(saved.current);
    }
    setLinking(false);
    run('createLink', safe);
  }

  const tools: [string, () => void][] = [
    [copy.bold, () => run('bold')],
    [copy.italic, () => run('italic')],
    [copy.heading, () => run('formatBlock', headingCommand())],
    [copy.bullet_list, () => run('insertUnorderedList')],
    [copy.numbered_list, () => run('insertOrderedList')],
    [copy.link, openLink],
  ];
  const labelId = `${id}-label`;
  return (
    <div className="grid gap-2" lang={lang}>
      <Label id={labelId} htmlFor={readOnly ? undefined : id}>
        {label}
      </Label>
      {readOnly ? (
        <iframe
          sandbox=""
          srcDoc={cleanHtml(value)}
          title={t(copy.readonly_frame)}
          className="min-h-32 w-full rounded-md border bg-white"
        />
      ) : (
        <>
          <div role="toolbar" aria-label={t(copy.toolbar)} className="flex flex-wrap gap-1">
            {tools.map(([key, action]) => (
              <Button
                key={key}
                type="button"
                variant="outline"
                size="sm"
                onMouseDown={(e) => e.preventDefault()}
                onClick={action}
              >
                {t(key)}
              </Button>
            ))}
          </div>
          {linking && (
            <div className="flex flex-wrap items-center gap-2">
              <Input
                type="url"
                aria-label={t(copy.link_url)}
                value={href}
                placeholder="https://"
                className="max-w-sm"
                onChange={(e) => {
                  setHref(e.target.value);
                  setLinkError(false);
                }}
              />
              <Button type="button" size="sm" onClick={applyLink}>
                {t(copy.link_apply)}
              </Button>
              <Button type="button" size="sm" variant="outline" onClick={() => setLinking(false)}>
                {t(copy.link_cancel)}
              </Button>
              {linkError && (
                <p role="alert" className="basis-full text-sm text-destructive dark:text-red-400">
                  {t(copy.link_invalid)}
                </p>
              )}
            </div>
          )}
          {/* biome-ignore lint/a11y/useSemanticElements: a rich-text field is a contentEditable region; a textarea cannot hold markup */}
          <div
            ref={editor}
            id={id}
            role="textbox"
            aria-multiline="true"
            aria-labelledby={labelId}
            contentEditable
            suppressContentEditableWarning
            tabIndex={0}
            className={BOX}
            {...invalidProps(id, error)}
            onInput={emit}
            onBlur={emit}
            onPaste={paste}
            onDrop={(e) => e.preventDefault()}
          />
        </>
      )}
      <FieldError id={fieldErrorId(id)}>{error}</FieldError>
    </div>
  );
}
