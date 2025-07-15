from playwright.sync_api import sync_playwright
from pathlib import Path
import re
import time

BASE_URL = "https://www.journaldemontreal.com/auteur/mathieu-bock-cote/page/{page}?pageSize=20&ajax=true"
OUTPUT_DIR = Path("~/Desktop/chroniques_bock_cote").expanduser()
OUTPUT_DIR.mkdir(exist_ok=True)

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()

    all_links = set()
    max_pages = 200

    print("🔄 Chargement des pages AJAX pour Mathieu Bock-Côté...")

    for page_num in range(0, max_pages):
        url = BASE_URL.format(page=page_num)
        print(f"📄 Chargement page {page_num} : {url}")
        page.goto(url, timeout=30000)
        page.wait_for_timeout(1000)

        links = page.evaluate("""
            () => Array.from(document.querySelectorAll("a"))
                      .map(a => a.href)
                      .filter(h => h.includes("/202") && h.includes("journaldemontreal.com"))
        """)
        new_links = set(links) - all_links

        print(f"🔗 Nouveaux liens trouvés : {len(new_links)}")

        if not new_links:
            print("✅ Plus de nouveaux articles. Fin.")
            break

        all_links.update(new_links)

    print(f"📚 Total d’articles collectés : {len(all_links)}")

    articles = sorted(all_links)
    for i, url in enumerate(articles, 1):
        print(f"📥 [{i}/{len(articles)}] Téléchargement : {url}")
        try:
            article_page = browser.new_page()
            article_page.goto(url, timeout=60000)
            article_page.wait_for_timeout(3000)

            titre = article_page.title().strip()
            auteur = "Mathieu Bock-Côté"

            date_elem = article_page.locator("time").first
            date_text = date_elem.get_attribute("datetime")[:10] if date_elem.count() > 0 else "0000-00-00"

            texte = article_page.evaluate("""
                () => Array.from(document.querySelectorAll('article p'))
                          .map(p => p.innerText.trim())
                          .join('\\n')
            """)

            titre_fichier = re.sub(r"[^\w\d-]", "_", titre)[:60]
            fichier_name = f"{date_text}_BockCote_{titre_fichier}.txt"
            fichier_path = OUTPUT_DIR / fichier_name

            with open(fichier_path, "w", encoding="utf-8") as f:
                f.write(f"TITRE  : {titre}\n")
                f.write(f"URL    : {url}\n")
                f.write(f"AUTEUR : {auteur}\n")
                f.write(f"DATE   : {date_text}\n\n")
                f.write(texte)

            print(f"✅ Sauvegardé : {fichier_name}")
            article_page.close()
            time.sleep(2)
        except Exception as e:
            print(f"❌ Erreur : {e}")

    browser.close()
