from playwright.sync_api import sync_playwright
from pathlib import Path
import re
import time

BASE_URL = "https://www.ledevoir.com/auteur/jean-francois-lisee"
OUTPUT_DIR = Path("~/Desktop/chroniques_lisee").expanduser()
OUTPUT_DIR.mkdir(exist_ok=True)

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()

    all_links = set()
    max_pages = 100

    print("🔄 Chargement des pages auteur de Jean-François Lisée...")

    for page_num in range(1, max_pages + 1):
        url = BASE_URL if page_num == 1 else f"{BASE_URL}/{page_num}"
        print(f"📄 Page {page_num} : {url}")
        page.goto(url, timeout=30000)
        page.wait_for_timeout(1000)

        # Extraire uniquement les chroniques
        links = page.evaluate("""
            () => Array.from(document.querySelectorAll("a"))
                      .map(a => a.href)
                      .filter(h => h.includes("/opinion/chroniques/"))
        """)
        new_links = set(links) - all_links

        print(f"🔗 Chroniques trouvées : {len(new_links)}")

        if not new_links:
            print("✅ Fin de la pagination. Aucun nouveau lien.")
            break

        all_links.update(new_links)

    print(f"📚 Total de chroniques collectées : {len(all_links)}")

    for i, url in enumerate(sorted(all_links), 1):
        print(f"📥 [{i}/{len(all_links)}] Téléchargement : {url}")
        try:
            article_page = browser.new_page()
            article_page.goto(url, timeout=60000)
            article_page.wait_for_timeout(3000)

            titre = article_page.title().strip()
            auteur = "Jean-François Lisée"

            date_elem = article_page.locator("time").first
            date_text = date_elem.get_attribute("datetime")[:10] if date_elem.count() > 0 else "0000-00-00"

            texte = article_page.evaluate("""
                () => Array.from(document.querySelectorAll('article p'))
                          .map(p => p.innerText.trim())
                          .join('\\n')
            """)

            titre_fichier = re.sub(r"[^\w\d-]", "_", titre)[:60]
            fichier_name = f"{date_text}_Lisee_{titre_fichier}.txt"
            fichier_path = OUTPUT_DIR / fichier_name

            with open(fichier_path, "w", encoding="utf-8") as f:
                f.write(f"TITRE  : {titre}\n")
                f.write(f"URL    : {url}\n")
                f.write(f"AUTEUR : {auteur}\n")
                f.write(f"DATE   : {date_text}\n\n")
                f.write(texte)

            print(f"✅ Sauvegardé : {fichier_name}")
            article_page.close()
            time.sleep(1)
        except Exception as e:
            print(f"❌ Erreur : {e}")

    browser.close()
