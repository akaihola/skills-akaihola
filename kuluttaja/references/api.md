# Kuluttaja.fi API / DOM Reference

Site architecture: Next.js SPA + server-rendered pages. No public REST API for content discovery — must use browser automation.

## Base URL

```
https://kuluttaja.fi
```

## Login

### Entry Point

Click header link: `KIRJAUDU` — navigates to login form.
The `/fi/kirjaudu` URL returns 404; use the header link instead.

### Form Structure

| Field          | Selector                                    |
|----------------|---------------------------------------------|
| Email          | `[role="textbox"][name*="email"]` or by label "SÄHKÖPOSTIOSOITE" |
| Password       | `input[type="password"]` or by label "SALASANA" |
| Remember me    | `[type="checkbox"]` text "PIDÄ MINUT KIRJAUTUNEENA" |
| Submit         | `[role="button"]` text "Kirjaudu sisään" |

### Success Indicators

After login: header shows "KIRJAUDU ULOS" and "Oma tili" link.

### Cookie Banner

On first visit: banner with buttons "Hyväksy kaikki" or "Vain välttämättömät".

## Search

### Search Box

```css
input[placeholder="Haku"]
```

Submit by pressing Enter key — no form POST, uses Next.js routing.

### Search Results Page

URL pattern: search happens client-side, URL may show `/?q=...` or query params.

Results are in `<article>` elements:

```html
<article>
  <a href="/path/to/article">
    <h4>Article Title</h4>
  </a>
  <span>Date (e.g. 18.06.2026)</span>
  <p>Snippet excerpt...</p>
</article>
```

### Filter Radios

| Label    | Selector |
|----------|----------|
| KAIKKI   | `[type="radio"]` + text "KAIKKI" |
| TESTIT   | `[type="radio"]` + text "TESTIT" |
| ARTIKKELIT | `[type="radio"]` + text "ARTIKKELIT" |
| MUUT     | `[type="radio"]` + text "MUUT" |

### Pagination

" LATAA LISÄÄ" button loads more results.

## Article Page

### Structure

```
<main>
  <h1>Article Title</h1>
  <span>JULKAISTU: DD.MM.YYYY</span>
  <p>KIRJOITTAJA: Author Name</p>
  <p>Intro paragraph...</p>
  <h3>Section Heading</h3>
  <p>Content...</p>
  <figure><img>...</figure>
  <h3>Section Heading</h3>
  ...
  <!-- Tags as paragraphs -->
  <p>GRILLAUS</p>
  <p>GRILLI</p>
  ...
</main>
```

### Expandable Content

Some articles have "NÄYTÄ LISÄÄ" / "Näytä lisää" buttons that load more content.
Click them to reveal hidden text.

### Paywall

Paywalled articles show "Jatka lukemista" section with:
- "Osta pääsy tähän sisältöön tai tilaa Kuluttaja."
- "Kirjaudu" link

Without login: only the intro paragraphs are visible.
With login: full article content is visible.

### Sidebar

After article body: "Saatat pitää myös näistä" section with related articles.

## Content Type Tags

At bottom of articles, tags appear as paragraph elements:
GRILLAUS, GRILLI, HIILIGRILLI, KAASUGRILLI, SÄHKÖGRILLI, RUOKA, etc.

## URL Conventions

Public articles: `https://kuluttaja.fi/fi/artikkeli/{slug}`
Some also work at: `https://kuluttaja.fi/{slug}/`
Some old URLs redirect or 404.
