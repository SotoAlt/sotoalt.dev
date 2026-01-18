#!/usr/bin/env python3
"""
publish.py - Minimal blog publishing system for sotoalt.dev

Usage:
    python3 publish.py posts/YYYY-MM-DD-slug.md           # Publish to site
    python3 publish.py posts/YYYY-MM-DD-slug.md --substack  # Output for Substack
    python3 publish.py --rss                               # Regenerate RSS only
    python3 publish.py --rebuild                           # Rebuild all posts
"""

import sys
import os
import re
import html
import subprocess
from datetime import datetime
from pathlib import Path

# Configuration
SITE_ROOT = Path(__file__).parent
POSTS_DIR = SITE_ROOT / "posts"
THOUGHTS_DIR = SITE_ROOT / "thoughts"
TEMPLATES_DIR = SITE_ROOT / "templates"
INDEX_FILE = SITE_ROOT / "index.html"
FEED_FILE = SITE_ROOT / "feed.xml"

SITE_URL = "https://sotoalt.dev"
SITE_TITLE = "sotoalt"
SITE_DESCRIPTION = "thoughts, experiments, and rabbit holes"


def parse_frontmatter(content: str) -> tuple[dict, str]:
    """Parse YAML-like frontmatter from markdown content."""
    if not content.startswith("---"):
        return {}, content

    parts = content.split("---", 2)
    if len(parts) < 3:
        return {}, content

    frontmatter = {}
    for line in parts[1].strip().split("\n"):
        if ":" in line:
            key, value = line.split(":", 1)
            frontmatter[key.strip()] = value.strip().strip('"').strip("'")

    return frontmatter, parts[2].strip()


def markdown_to_html(md: str) -> str:
    """Convert markdown to HTML. Simple parser, no dependencies."""
    lines = md.split("\n")
    html_lines = []
    in_list = False
    in_code = False
    code_block = []

    i = 0
    while i < len(lines):
        line = lines[i]

        # Code blocks
        if line.startswith("```"):
            if in_code:
                html_lines.append(f'<pre><code>{html.escape(chr(10).join(code_block))}</code></pre>')
                code_block = []
                in_code = False
            else:
                in_code = True
            i += 1
            continue

        if in_code:
            code_block.append(line)
            i += 1
            continue

        # Close list if needed
        if in_list and not line.strip().startswith("- ") and not line.strip().startswith("* "):
            html_lines.append("</ul>")
            in_list = False

        # Headers
        if line.startswith("# "):
            # Skip h1 as we use it in the template
            i += 1
            continue
        elif line.startswith("## "):
            html_lines.append(f'<h2>{process_inline(line[3:])}</h2>')
        elif line.startswith("### "):
            html_lines.append(f'<h3>{process_inline(line[4:])}</h3>')
        # Horizontal rule
        elif line.strip() in ("---", "***", "___"):
            html_lines.append("<hr>")
        # Lists
        elif line.strip().startswith("- ") or line.strip().startswith("* "):
            if not in_list:
                html_lines.append("<ul>")
                in_list = True
            item = line.strip()[2:]
            html_lines.append(f'<li>{process_inline(item)}</li>')
        # Blockquotes
        elif line.startswith("> "):
            html_lines.append(f'<blockquote><p>{process_inline(line[2:])}</p></blockquote>')
        # Images
        elif re.match(r'!\[.*\]\(.*\)', line):
            match = re.match(r'!\[(.*)\]\((.*)\)', line)
            if match:
                alt, src = match.groups()
                html_lines.append(f'<figure><img src="{src}" alt="{alt}"><figcaption>{alt}</figcaption></figure>')
        # Empty line
        elif not line.strip():
            html_lines.append("")
        # Paragraph
        else:
            # Collect multi-line paragraphs
            para_lines = [line]
            while i + 1 < len(lines) and lines[i + 1].strip() and not lines[i + 1].startswith(("#", "-", "*", ">", "```", "![", "---", "***", "___")):
                i += 1
                para_lines.append(lines[i])
            html_lines.append(f'<p>{process_inline(" ".join(para_lines))}</p>')

        i += 1

    # Close any open list
    if in_list:
        html_lines.append("</ul>")

    return "\n                ".join(html_lines)


def process_inline(text: str) -> str:
    """Process inline markdown: bold, italic, links, code."""
    # Escape HTML first
    text = html.escape(text)

    # Code (backticks)
    text = re.sub(r'`([^`]+)`', r'<code>\1</code>', text)

    # Bold
    text = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', text)
    text = re.sub(r'__([^_]+)__', r'<strong>\1</strong>', text)

    # Italic (use em for accent color per site style)
    text = re.sub(r'\*([^*]+)\*', r'<em>\1</em>', text)
    text = re.sub(r'_([^_]+)_', r'<em>\1</em>', text)

    # Links
    text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<a href="\2">\1</a>', text)

    # Em dash
    text = text.replace("--", "&mdash;")

    return text


def estimate_reading_time(text: str) -> int:
    """Estimate reading time in minutes."""
    words = len(text.split())
    return max(1, round(words / 200))


def format_date_display(date_str: str) -> str:
    """Format date for display (YYYY.MM)."""
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        return dt.strftime("%Y.%m")
    except ValueError:
        return date_str


def format_date_rss(date_str: str) -> str:
    """Format date for RSS (RFC 822)."""
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        return dt.strftime("%a, %d %b %Y 00:00:00 +0000")
    except ValueError:
        return date_str


def get_slug_from_filename(filename: str) -> str:
    """Extract slug from filename (YYYY-MM-DD-slug.md -> slug)."""
    name = Path(filename).stem
    # Remove date prefix if present
    match = re.match(r'\d{4}-\d{2}-\d{2}-(.+)', name)
    if match:
        return match.group(1)
    return name


def publish_post(md_file: Path, substack: bool = False) -> dict:
    """Publish a markdown post to HTML."""
    content = md_file.read_text()
    frontmatter, body = parse_frontmatter(content)

    # Extract metadata
    title = frontmatter.get("title", get_slug_from_filename(md_file.name).replace("-", " "))
    date = frontmatter.get("date", datetime.now().strftime("%Y-%m-%d"))
    description = frontmatter.get("description", "")
    slug = get_slug_from_filename(md_file.name)

    # Convert markdown to HTML
    html_content = markdown_to_html(body)
    reading_time = estimate_reading_time(body)

    if substack:
        # Output clean HTML for Substack
        substack_html = html_content.replace("                ", "")
        print("\n" + "=" * 60)
        print("SUBSTACK HTML (copy below):")
        print("=" * 60 + "\n")
        print(substack_html)
        print("\n" + "=" * 60)

        # Try to copy to clipboard (macOS)
        try:
            subprocess.run(["pbcopy"], input=substack_html.encode(), check=True)
            print("Copied to clipboard!")
        except (subprocess.CalledProcessError, FileNotFoundError):
            pass

        return {
            "title": title,
            "date": date,
            "description": description,
            "slug": slug
        }

    # Load template
    template_file = TEMPLATES_DIR / "post.html"
    if not template_file.exists():
        print(f"Error: Template not found at {template_file}")
        sys.exit(1)

    template = template_file.read_text()

    # Fill template
    html_output = template.replace("{{title}}", title)
    html_output = html_output.replace("{{description}}", description)
    html_output = html_output.replace("{{slug}}", slug)
    html_output = html_output.replace("{{date_display}}", format_date_display(date))
    html_output = html_output.replace("{{reading_time}}", str(reading_time))
    html_output = html_output.replace("{{content}}", html_content)

    # Write output
    output_file = THOUGHTS_DIR / f"{slug}.html"
    output_file.write_text(html_output)
    print(f"Published: {output_file}")

    return {
        "title": title,
        "date": date,
        "description": description,
        "slug": slug,
        "file": output_file
    }


def extract_metadata_from_html(html_file: Path) -> dict:
    """Extract title, date, and description from existing HTML post."""
    content = html_file.read_text()
    slug = html_file.stem

    # Extract title from <title> tag
    title_match = re.search(r'<title>([^<]+) / sotoalt</title>', content)
    title = title_match.group(1) if title_match else slug.replace("-", " ")

    # Extract description from meta tag
    desc_match = re.search(r'<meta name="description" content="([^"]*)"', content)
    description = desc_match.group(1) if desc_match else ""

    # Extract date from meta (format: YYYY.MM)
    date_match = re.search(r'<p class="meta">(\d{4})\.(\d{2})', content)
    if date_match:
        year, month = date_match.groups()
        date = f"{year}-{month}-01"
    else:
        date = "1970-01-01"

    return {
        "title": title,
        "date": date,
        "description": description,
        "slug": slug,
        "file": html_file,
        "source": "html"
    }


def get_all_posts() -> list[dict]:
    """Get all posts from markdown sources and existing HTML files, sorted by date descending."""
    posts = []
    seen_slugs = set()

    # First, get posts from markdown sources (these take priority)
    if POSTS_DIR.exists():
        for md_file in POSTS_DIR.glob("*.md"):
            content = md_file.read_text()
            frontmatter, body = parse_frontmatter(content)

            slug = get_slug_from_filename(md_file.name)
            date = frontmatter.get("date", "")

            # Try to extract date from filename if not in frontmatter
            if not date:
                match = re.match(r'(\d{4}-\d{2}-\d{2})-', md_file.name)
                if match:
                    date = match.group(1)
                else:
                    date = "1970-01-01"

            posts.append({
                "title": frontmatter.get("title", slug.replace("-", " ")),
                "date": date,
                "description": frontmatter.get("description", ""),
                "slug": slug,
                "file": md_file,
                "body": body,
                "source": "markdown"
            })
            seen_slugs.add(slug)

    # Then, add existing HTML posts that don't have markdown sources
    if THOUGHTS_DIR.exists():
        for html_file in THOUGHTS_DIR.glob("*.html"):
            slug = html_file.stem
            if slug not in seen_slugs:
                post = extract_metadata_from_html(html_file)
                posts.append(post)
                seen_slugs.add(slug)

    # Sort by date descending
    posts.sort(key=lambda p: p["date"], reverse=True)
    return posts


def update_index(posts: list[dict]):
    """Update the thoughts section in index.html with all posts."""
    if not INDEX_FILE.exists():
        print(f"Warning: {INDEX_FILE} not found, skipping index update")
        return

    index_content = INDEX_FILE.read_text()

    # Build new posts list HTML
    posts_html = []
    for post in posts:
        date_display = format_date_display(post["date"])
        posts_html.append(
            f'                <li>\n'
            f'                    <span class="date">{date_display}</span>\n'
            f'                    <a href="thoughts/{post["slug"]}.html">{post["title"]}</a>\n'
            f'                </li>'
        )

    new_posts_block = "\n".join(posts_html)

    # Replace the posts list in the thoughts section
    pattern = r'(<section id="thoughts">.*?<ul class="posts">)(.*?)(</ul>)'
    replacement = rf'\1\n{new_posts_block}\n            \3'

    new_index = re.sub(pattern, replacement, index_content, flags=re.DOTALL)

    if new_index != index_content:
        INDEX_FILE.write_text(new_index)
        print(f"Updated: {INDEX_FILE}")


def generate_rss(posts: list[dict]):
    """Generate RSS feed."""
    items = []

    for post in posts[:20]:  # Limit to 20 most recent
        item = f"""    <item>
      <title>{html.escape(post['title'])}</title>
      <link>{SITE_URL}/thoughts/{post['slug']}.html</link>
      <guid>{SITE_URL}/thoughts/{post['slug']}.html</guid>
      <pubDate>{format_date_rss(post['date'])}</pubDate>
      <description>{html.escape(post.get('description', ''))}</description>
    </item>"""
        items.append(item)

    rss = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">
  <channel>
    <title>{SITE_TITLE}</title>
    <link>{SITE_URL}</link>
    <description>{SITE_DESCRIPTION}</description>
    <language>en-us</language>
    <lastBuildDate>{datetime.now().strftime("%a, %d %b %Y %H:%M:%S +0000")}</lastBuildDate>
    <atom:link href="{SITE_URL}/feed.xml" rel="self" type="application/rss+xml"/>
{chr(10).join(items)}
  </channel>
</rss>"""

    FEED_FILE.write_text(rss)
    print(f"Generated: {FEED_FILE}")


def rebuild_all():
    """Rebuild all posts from markdown sources."""
    posts = get_all_posts()

    # Only rebuild posts that have markdown sources
    markdown_posts = [p for p in posts if p.get("source") == "markdown"]
    for post in markdown_posts:
        publish_post(post["file"])

    update_index(posts)
    generate_rss(posts)
    print(f"\nRebuilt {len(markdown_posts)} posts from markdown sources")
    print(f"Total posts in index: {len(posts)}")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    arg = sys.argv[1]

    if arg == "--rss":
        posts = get_all_posts()
        generate_rss(posts)
        return

    if arg == "--rebuild":
        rebuild_all()
        return

    # Publishing a specific post
    md_file = Path(arg)
    if not md_file.exists():
        print(f"Error: File not found: {md_file}")
        sys.exit(1)

    if not md_file.suffix == ".md":
        print(f"Error: Expected markdown file (.md)")
        sys.exit(1)

    substack = "--substack" in sys.argv

    # Publish the post
    post_info = publish_post(md_file, substack=substack)

    if not substack:
        # Update index and RSS with all posts
        posts = get_all_posts()
        update_index(posts)
        generate_rss(posts)

    print("\nDone!")


if __name__ == "__main__":
    main()
