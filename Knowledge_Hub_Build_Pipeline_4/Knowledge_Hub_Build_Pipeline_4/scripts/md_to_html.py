#!/usr/bin/env python3
"""Converts a markdown deliverable into a clean, standalone, readable HTML
file - proper typography, a table of contents, syntax-highlighted code
blocks, and light/dark mode support. No external dependencies at view time
(everything inlined)."""
import argparse
import re
import sys
from pathlib import Path

import markdown
from pygments.formatters import HtmlFormatter

TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
:root {{
  --bg: #ffffff;
  --bg-alt: #f6f8fa;
  --text: #1b1f24;
  --text-muted: #57606a;
  --border: #d8dee4;
  --accent: #0b3d66;
  --accent-2: #0e7c86;
  --code-bg: #f6f8fa;
  --blocking: #b42318;
  --blocking-bg: #fdecea;
  --advisory: #9a6700;
  --advisory-bg: #fff8e6;
  --info: #0b3d66;
  --info-bg: #eaf2fb;
}}
@media (prefers-color-scheme: dark) {{
  :root:not([data-theme="light"]) {{
    --bg: #14181f;
    --bg-alt: #1b212b;
    --text: #e6edf3;
    --text-muted: #9aa7b2;
    --border: #2d3540;
    --accent: #7db2e8;
    --accent-2: #5fc3cf;
    --code-bg: #1b212b;
    --blocking: #ff8c82;
    --blocking-bg: #3a1b18;
    --advisory: #e3b341;
    --advisory-bg: #3a2f10;
    --info: #7db2e8;
    --info-bg: #142433;
  }}
}}
* {{ box-sizing: border-box; }}
body {{
  margin: 0;
  background: var(--bg);
  color: var(--text);
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
  line-height: 1.6;
}}
.page {{
  max-width: 880px;
  margin: 0 auto;
  padding: 48px 24px 96px;
}}
.masthead {{
  border-bottom: 1px solid var(--border);
  padding-bottom: 20px;
  margin-bottom: 32px;
}}
.masthead .kicker {{
  color: var(--accent-2);
  font-weight: 600;
  font-size: 0.8rem;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}}
.masthead h1 {{
  margin: 6px 0 4px;
  font-size: 1.9rem;
  color: var(--accent);
}}
.masthead .meta {{
  color: var(--text-muted);
  font-size: 0.9rem;
}}
h1, h2, h3, h4 {{ color: var(--accent); scroll-margin-top: 20px; }}
h2 {{
  margin-top: 2.4em;
  padding-top: 0.4em;
  border-top: 1px solid var(--border);
  font-size: 1.35rem;
}}
h3 {{ font-size: 1.1rem; color: var(--accent-2); }}
p, li {{ font-size: 0.98rem; }}
a {{ color: var(--accent-2); }}
code {{
  background: var(--code-bg);
  border: 1px solid var(--border);
  border-radius: 4px;
  padding: 0.1em 0.4em;
  font-size: 0.88em;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
}}
pre {{
  background: var(--code-bg);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 14px 16px;
  overflow-x: auto;
}}
pre code {{ background: none; border: none; padding: 0; }}
table {{ border-collapse: collapse; width: 100%; margin: 1em 0; }}
th, td {{ border: 1px solid var(--border); padding: 8px 10px; text-align: left; font-size: 0.92rem; }}
th {{ background: var(--bg-alt); }}
blockquote {{
  margin: 1em 0;
  padding: 0.2em 1em;
  border-left: 3px solid var(--accent-2);
  color: var(--text-muted);
  background: var(--bg-alt);
  border-radius: 0 6px 6px 0;
}}
hr {{ border: none; border-top: 1px solid var(--border); margin: 2.5em 0; }}
.toc {{
  background: var(--bg-alt);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 16px 20px;
  margin: 24px 0 36px;
}}
.toc > strong {{ display: block; margin-bottom: 8px; font-size: 0.85rem; letter-spacing: 0.04em; text-transform: uppercase; color: var(--text-muted); }}
.toc ul {{ margin: 0; padding-left: 1.2em; columns: 1; }}
.toc li {{ font-size: 0.92rem; margin: 4px 0; }}
.badge {{
  display: inline-block;
  font-size: 0.72rem;
  font-weight: 700;
  letter-spacing: 0.03em;
  text-transform: uppercase;
  padding: 2px 9px;
  border-radius: 999px;
  margin-left: 6px;
  vertical-align: middle;
}}
.badge-blocking {{ color: var(--blocking); background: var(--blocking-bg); }}
.badge-advisory {{ color: var(--advisory); background: var(--advisory-bg); }}
.badge-informational {{ color: var(--info); background: var(--info-bg); }}
footer {{
  margin-top: 4em;
  padding-top: 1.5em;
  border-top: 1px solid var(--border);
  color: var(--text-muted);
  font-size: 0.82rem;
}}
</style>
</head>
<body>
<div class="page">
  <div class="masthead">
    <div class="kicker">{kicker}</div>
    <h1>{title}</h1>
    <div class="meta">{subtitle}</div>
  </div>
  {toc}
  {body}
  <footer>Generated from <code>{source_name}</code> for the Groupe CAT VIP — Integration Knowledge Hub build.</footer>
</div>
</body>
</html>
"""


def badge_markers(html):
    """Turn a bracketed severity word at the start of a bullet, like
    '## Blocking - resolve ... (23)', into a colored badge next to the
    heading, and inline '**Blocking**'/'**Advisory**' style words too."""
    def repl(m):
        word = m.group(1)
        cls = word.lower()
        return f'{m.group(0)} <span class="badge badge-{cls}">{word}</span>'
    html = re.sub(r'(<h2[^>]*>)(Blocking|Advisory|Informational)([^<]*</h2>)',
                  lambda m: f'{m.group(1)}{m.group(2)}{m.group(3)}'.replace(
                      m.group(3), f'<span class="badge badge-{m.group(2).lower()}">{m.group(2)}</span>{m.group(3)}'
                  ), html)
    return html


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("md_path")
    ap.add_argument("--out", required=True)
    ap.add_argument("--title", required=True)
    ap.add_argument("--kicker", default="Groupe CAT VIP — Integration Knowledge Hub")
    ap.add_argument("--subtitle", default="")
    args = ap.parse_args()

    md_text = Path(args.md_path).read_text(encoding="utf-8")

    md = markdown.Markdown(extensions=[
        "fenced_code", "tables", "toc", "sane_lists", "codehilite", "attr_list",
    ], extension_configs={
        "codehilite": {"css_class": "codehilite"},
        "toc": {"anchorlink": False, "permalink": False},
    })
    body_html = md.convert(md_text)

    # Build a simple TOC from the h2 entries markdown.extensions.toc produced
    toc_html = ""
    if hasattr(md, "toc") and md.toc:
        toc_html = f'<div class="toc"><strong>Contents</strong>{md.toc}</div>'
        # keep only top-level items for a cleaner sidebar-less TOC
    toc_html = re.sub(r'<div class="toctitle">.*?</div>', "", toc_html)

    pygments_css = HtmlFormatter(style="default").get_style_defs(".codehilite")
    body_html = body_html  # pygments classes already applied by codehilite ext

    full_css_extra = f"<style>{pygments_css}\n.codehilite {{ background: var(--code-bg); border:1px solid var(--border); border-radius:8px; padding:12px 14px; overflow-x:auto; }}</style>"

    html = TEMPLATE.format(
        title=args.title,
        kicker=args.kicker,
        subtitle=args.subtitle,
        toc=toc_html,
        body=body_html,
        source_name=Path(args.md_path).name,
    )
    html = html.replace("</head>", full_css_extra + "</head>")
    html = badge_markers(html)

    Path(args.out).write_text(html, encoding="utf-8")
    print(f"Wrote {args.out} ({len(html)} bytes)")


if __name__ == "__main__":
    main()
