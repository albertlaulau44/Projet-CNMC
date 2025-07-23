#!/usr/bin/env python3
import re
import time
import logging
from pathlib import Path
from datetime import datetime
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

# ----------------------------
# Configuration
# ----------------------------
BASE_URL    = "https://ici.radio-canada.ca/info/analyses"
OUTPUT_DIR  = Path.home() / "Desktop" / "chroniques_radio_canada"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
MAX_PAGES   = 10
PAGE_TIMEOUT = 30000  # ms
SELECTOR_TIMEOUT = 30000  # ms
DELAY_SEC    = 2

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Month mapping for French dates
MOIS_FR = {
    "janvier":   "01", "février":  "02", "mars":     "03",
    "avril":     "04", "mai":      "05", "juin":     "06",
    "juillet":   "07", "août":     "08", "septembre":"09",
    "octobre":   "10", "novembre": "11", "décembre": "12"
}

# ----------------------------
# Utility functions
# ----------------------------
def safe_filename(text, max_length=60):
    """Sanitize a string to be filesystem-safe."""
    name = re.sub(r'[<>:"/\\|?*]', '_', text)
    name = re.sub(r'\s+', '_', name).strip('_')
    return name[:max_length]

def extract_date(page) -> str:
    """Try several selectors to parse a YYYY-MM-DD date."""
    date_selectors = [
        'time[datetime]', 'span[data-testid="date"]', 'time',
        '.published-date', '.date'
    ]
    for sel in date_selectors:
        try:
            elt = page.query_selector(sel)
            if not elt:
                continue
            # first, try datetime attribute
            dt = elt.get_attribute("datetime") or ""
            m = re.search(r'(\d{4}-\d{2}-\d{2})', dt)
            if m:
                return m.group(1)
            # next, fallback to inner text
            txt = elt.inner_text().strip()
            # ISO style in text?
            m = re.search(r'(\d{4}-\d{2}-\d{2})', txt)
            if m:
                return m.group(1)
            # french style, e.g. "15 juillet 2025"
            m = re.search(r'(\d{1,2})\s+([A-Za-zéû]+)\s+(\d{4})', txt)
            if m:
                day, mois, year = m.groups()
                mois = MOIS_FR.get(mois.lower(), "01")
                return f"{year}-{mois}-{int(day):02d}"
        except Exception:
            continue
    return datetime.today().strftime("%Y-%m-%d")

def extract_content(page) -> str:
    """Aggregate paragraphs from a set of candidate selectors."""
    selectors = [
        'div[data-testid="text-content"] p',
        'article div p',
        'div.article-content p',
        '[data-testid="article-body"] p',
        'main p',
        'div.content p',
        'p'
    ]
    for sel in selectors:
        try:
            elems = page.query_selector_all(sel)
            texts = [e.inner_text().strip() for e in elems]
            # keep only paragraphs longer than 50 chars
            paras = [t for t in texts if len(t) > 50]
            if paras:
                logger.info(f"   ✅ contenu extrait via « {sel} »")
                return "\n\n".join(paras)
        except Exception:
            continue
    # fallback: raw body text
    return page.content()[:500] + "..."

def find_article_links(page) -> set[str]:
    """Collect all unique article URLs on the listing page."""
    selectors = [
        'a[href*="/info/analyses/"]',
        'article a[href*="/info/analyses/"]',
        '.title a[href*="/analyses/"]'
    ]
    links = set()
    for sel in selectors:
        for a in page.query_selector_all(sel):
            href = a.get_attribute("href") or ""
            if "/info/analyses/" in href and not re.match(r"/info/analyses/?(?:/\d+)?/?$", href):
                if href.startswith("/"):
                    href = "https://ici.radio-canada.ca" + href
                links.add(href)
    return links

# ----------------------------
# Main scraping logic
# ----------------------------
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(
        user_agent=(
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/114.0.0.0 Safari/537.36"
        )
    )

    page = context.new_page()
    article_urls: set[str] = set()

    # 1) Collect listing pages
    for n in range(1, MAX_PAGES + 1):
        url = BASE_URL if n == 1 else f"{BASE_URL}/{n}"
        logger.info(f"🔄 Chargement page {n}: {url}")
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT)
            page.wait_for_selector('a[href*="/info/analyses/"]', timeout=SELECTOR_TIMEOUT)
            new_links = find_article_links(page)
            diff = new_links - article_urls
            if not diff:
                logger.info("✅ Aucun nouvel article, arrêt de la collecte.")
                break
            article_urls |= new_links
            logger.info(f"   ↳ {len(diff)} nouveaux liens trouvés (total {len(article_urls)})")
            time.sleep(DELAY_SEC)
        except PlaywrightTimeoutError:
            logger.warning(f"⚠️ Timeout sur la page {n}, on passe à la suivante.")
        except Exception as e:
            logger.error(f"❌ Erreur page {n}: {e}")

    logger.info(f"\n📚 {len(article_urls)} articles à télécharger\n")

    # 2) Download each article
    for idx, art_url in enumerate(sorted(article_urls), 1):
        logger.info(f"📥 [{idx}/{len(article_urls)}] {art_url}")
        try:
            art_page = context.new_page()
            art_page.goto(art_url, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT)
            art_page.wait_for_selector("h1, article, [data-testid='text-content']", timeout=SELECTOR_TIMEOUT)
            title = art_page.title().strip() or art_page.query_selector("h1").inner_text().strip()
            date  = extract_date(art_page)
            body  = extract_content(art_page)

            filename = f"{date}_RadioCanada_{safe_filename(title)}.txt"
            filepath = OUTPUT_DIR / filename
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(f"TITRE : {title}\nURL   : {art_url}\nDATE  : {date}\n\n{body}")

            logger.info(f"   ✅ Sauvegardé → {filename}")
            art_page.close()
            time.sleep(DELAY_SEC)
        except PlaywrightTimeoutError:
            logger.warning(f"⚠️ Timeout téléchargement: {art_url}")
        except Exception as e:
            logger.error(f"❌ Erreur téléchargement: {e}")

    browser.close()
    logger.info("✅ Scraping terminé !")
