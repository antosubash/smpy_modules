# Multilingual content — what it looks like

Captured against the real host booted with two content locales:

```bash
SM_PAGEBUILDER_CONTENT_LOCALES='["en","de"]'
SM_PAGEBUILDER_DEFAULT_CONTENT_LOCALE=en
```

The seed is one English page with a published German translation, one
English-only page, and one news article with a German translation left as a
draft — enough for each screen to show a mix rather than a uniform list.

| File | Shows |
|---|---|
| `01-public-en.png` | The English page at `/p/about` — the default locale keeps the unprefixed address |
| `02-public-de.png` | The same document in German at `/de/p/about` |
| `03-page-list.png` | The page list: a Language column, the language filter pills, and `about` existing as a slug in *both* languages |
| `04-editor-languages.png` | The editor's Languages tab — which languages the page exists in, where each serves, and whether it is live |
| `05-article-languages.png` | The article editor's Languages panel, with the German translation sitting at `/de/news/…` as a draft |
| `06-news-list.png` | The article list, locale-prefixed URLs and the language filter |

The `hreflang` set the German page emits, read out of the live DOM:

```
de        → http://localhost:8000/de/p/about
en        → http://localhost:8000/p/about
x-default → http://localhost:8000/p/about
```

And the sitemap, with `xhtml:link` alternates on both entries:

```xml
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"
        xmlns:xhtml="http://www.w3.org/1999/xhtml">
  <url><loc>http://localhost:8000/de/p/about</loc>
    <xhtml:link rel="alternate" hreflang="de" href="http://localhost:8000/de/p/about"/>
    <xhtml:link rel="alternate" hreflang="en" href="http://localhost:8000/p/about"/>
    <xhtml:link rel="alternate" hreflang="x-default" href="http://localhost:8000/p/about"/></url>
  <url><loc>http://localhost:8000/p/about</loc>
    <xhtml:link rel="alternate" hreflang="de" href="http://localhost:8000/de/p/about"/>
    <xhtml:link rel="alternate" hreflang="en" href="http://localhost:8000/p/about"/>
    <xhtml:link rel="alternate" hreflang="x-default" href="http://localhost:8000/p/about"/></url>
</urlset>
```
