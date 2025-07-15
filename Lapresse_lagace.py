from playwright.sync_api import sync_playwright
from pathlib import Path
import json, re, requests, time
from bs4 import BeautifulSoup
import urllib.parse
from datetime import datetime, timedelta
import random

AUTHOR = "patrick-lagace"
OUTPUT_DIR = Path("~/Desktop/chroniques_lagace_complet").expanduser()
OUTPUT_DIR.mkdir(exist_ok=True)

# Set pour éviter les doublons
unique_articles = set()
scraped_urls = set()

def clean_filename(text):
    """Nettoie le texte pour créer un nom de fichier valide"""
    cleaned = re.sub(r'[^\w\s-]', '_', text)
    cleaned = re.sub(r'\s+', '_', cleaned)
    return cleaned[:60].strip('_')

def extract_article_content(soup):
    """Extrait le contenu principal de l'article"""
    content_selectors = [
        "article p",
        ".article-content p",
        ".story-content p",
        ".content p",
        "div[data-module='ArticleBody'] p",
        ".text-content p",
        ".entry-content p",
        ".post-content p",
        ".article-body p"
    ]
    
    texte = ""
    for selector in content_selectors:
        paragraphs = soup.select(selector)
        if paragraphs:
            texte = "\n".join(p.get_text(strip=True) for p in paragraphs if p.get_text(strip=True))
            break
    
    return texte

def is_lagace_article(soup, url):
    """Vérifie si l'article est bien de Patrick Lagacé"""
    # Vérifier dans l'URL
    if "patrick-lagace" in url.lower() or "lagace" in url.lower():
        return True
    
    # Vérifier dans les métadonnées auteur
    author_selectors = [
        ".author",
        ".byline",
        "[data-testid='author']",
        ".article-author",
        ".story-author",
        "span[class*='author']",
        "div[class*='author']",
        "meta[name='author']"
    ]
    
    for selector in author_selectors:
        author_elem = soup.select_one(selector)
        if author_elem:
            author_text = author_elem.get_text(strip=True) if hasattr(author_elem, 'get_text') else author_elem.get('content', '')
            if "patrick" in author_text.lower() and "lagac" in author_text.lower():
                return True
    
    # Vérifier dans le JSON-LD
    json_ld_scripts = soup.find_all("script", type="application/ld+json")
    for script in json_ld_scripts:
        try:
            data = json.loads(script.string)
            if isinstance(data, dict) and "author" in data:
                author_name = data["author"]
                if isinstance(author_name, dict):
                    author_name = author_name.get("name", "")
                if "patrick" in str(author_name).lower() and "lagac" in str(author_name).lower():
                    return True
        except:
            pass
    
    return False

def scrape_archives():
    """Scrape les archives de manière systématique"""
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()
        
        # Configuration des headers
        page.set_extra_http_headers({
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        })
        
        # 1. Page auteur principale - avec pagination systématique
        print("🔍 Scraping page auteur avec pagination...")
        base_url = f"https://www.lapresse.ca/auteurs/{AUTHOR}"
        
        page_num = 1
        while page_num <= 50:  # Limiter à 50 pages max
            try:
                if page_num == 1:
                    url = base_url
                else:
                    url = f"{base_url}?page={page_num}"
                
                print(f"📄 Page {page_num}: {url}")
                page.goto(url, timeout=30000)
                page.wait_for_timeout(2000)
                
                # Extraire tous les liens d'articles sur cette page
                articles_found = extract_article_links(page)
                
                if articles_found == 0:
                    print(f"❌ Aucun article trouvé sur la page {page_num}, arrêt")
                    break
                
                page_num += 1
                time.sleep(1)  # Pause entre les pages
                
            except Exception as e:
                print(f"❌ Erreur page {page_num}: {e}")
                break
        
        # 2. Section chroniques si elle existe
        print("\n🔍 Scraping section chroniques...")
        chroniques_urls = [
            "https://www.lapresse.ca/debats/chroniques",
            "https://www.lapresse.ca/actualites/chroniques",
            "https://www.lapresse.ca/chroniques"
        ]
        
        for chronique_url in chroniques_urls:
            try:
                page.goto(chronique_url, timeout=30000)
                page.wait_for_timeout(2000)
                
                # Scroll pour charger plus de contenu
                for i in range(10):
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    page.wait_for_timeout(1000)
                
                extract_article_links(page, filter_lagace=True)
                
            except Exception as e:
                print(f"❌ Erreur section chroniques {chronique_url}: {e}")
        
        browser.close()

def extract_article_links(page, filter_lagace=False):
    """Extrait les liens d'articles depuis une page"""
    articles_found = 0
    
    # Sélecteurs pour trouver les liens d'articles
    link_selectors = [
        "a[href*='/actualites/']",
        "a[href*='/debats/']",
        "a[href*='/chroniques/']",
        "a[href*='/sports/']",
        "a[href*='/arts/']",
        ".article-link",
        "[data-testid*='article'] a",
        "h1 a, h2 a, h3 a",
        ".headline a",
        ".title a"
    ]
    
    for selector in link_selectors:
        try:
            elements = page.locator(selector).all()
            for element in elements:
                href = element.get_attribute("href")
                if href and href not in scraped_urls:
                    if not href.startswith("http"):
                        href = "https://www.lapresse.ca" + href
                    
                    # Si on filtre, vérifier que c'est un article de Lagacé
                    if filter_lagace and not ("lagace" in href.lower() or "patrick-lagace" in href.lower()):
                        continue
                    
                    scraped_urls.add(href)
                    articles_found += 1
                    print(f"🔗 Article trouvé: {href}")
                    
        except Exception as e:
            print(f"⚠️ Erreur avec sélecteur {selector}: {e}")
    
    return articles_found

def download_and_verify_articles():
    """Télécharge et vérifie que chaque article est bien de Lagacé"""
    if not scraped_urls:
        print("❌ Aucun article trouvé.")
        return
    
    print(f"\n📥 Vérification et téléchargement de {len(scraped_urls)} articles...")
    
    verified_articles = []
    
    for i, url in enumerate(scraped_urls, 1):
        print(f"📥 [{i}/{len(scraped_urls)}] Vérification: {url}")
        
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }
            
            r = requests.get(url, headers=headers, timeout=15)
            r.raise_for_status()
            
            soup = BeautifulSoup(r.text, "html.parser")
            
            # Vérifier si c'est vraiment un article de Lagacé
            if not is_lagace_article(soup, url):
                print(f"⚠️ Pas un article de Lagacé, ignoré")
                continue
            
            # Extraction du titre
            titre = "Sans titre"
            title_selectors = ["h1", ".article-title", ".story-title", "[data-testid='article-title']"]
            for selector in title_selectors:
                title_elem = soup.select_one(selector)
                if title_elem:
                    titre = title_elem.get_text(strip=True)
                    break
            
            # Extraction de la date
            date = "0000-00-00"
            date_selectors = ["time", ".article-date", ".story-date", "[data-testid='article-date']"]
            for selector in date_selectors:
                date_elem = soup.select_one(selector)
                if date_elem:
                    date_attr = date_elem.get("datetime") or date_elem.get_text(strip=True)
                    if date_attr:
                        date_match = re.search(r'(\d{4}-\d{2}-\d{2})', date_attr)
                        if date_match:
                            date = date_match.group(1)
                            break
            
            # Extraction du contenu
            texte = extract_article_content(soup)
            
            if not texte:
                print(f"⚠️ Contenu vide, ignoré")
                continue
            
            # Créer une signature unique pour éviter les doublons
            article_signature = f"{titre}_{date}_{len(texte)}"
            if article_signature in unique_articles:
                print(f"⚠️ Doublon détecté, ignoré: {titre}")
                continue
            
            unique_articles.add(article_signature)
            
            # Création du nom de fichier
            fname = f"{date}_Lagace_{clean_filename(titre)}.txt"
            filepath = OUTPUT_DIR / fname
            
            # Sauvegarde
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(f"TITRE : {titre}\n")
                f.write(f"URL: {url}\n")
                f.write(f"AUTEUR: Patrick Lagacé\n")
                f.write(f"DATE: {date}\n\n")
                f.write(texte)
            
            verified_articles.append(fname)
            print(f"✅ Sauvegardé : {fname}")
            
            # Pause pour éviter d'être bloqué
            time.sleep(random.uniform(0.5, 1.5))
            
        except Exception as e:
            print(f"❌ Erreur pour {url}: {e}")
            continue
    
    return verified_articles

# Exécution du script
if __name__ == "__main__":
    print("🚀 Scraping ciblé des articles de Patrick Lagacé...")
    
    # Étape 1: Scraping des archives
    print("\n" + "="*50)
    print("ÉTAPE 1: Scraping des archives")
    print("="*50)
    scrape_archives()
    
    # Étape 2: Téléchargement et vérification
    print("\n" + "="*50)
    print("ÉTAPE 2: Téléchargement et vérification")
    print("="*50)
    verified_articles = download_and_verify_articles()
    
    print(f"\n🎉 Terminé !")
    print(f"📊 {len(scraped_urls)} URLs trouvées")
    print(f"📊 {len(verified_articles)} articles de Lagacé téléchargés")
    print(f"📁 Fichiers sauvegardés dans : {OUTPUT_DIR}")
    
    # Statistiques
    if verified_articles:
        dates = []
        for article in verified_articles:
            try:
                date_str = article.split("_")[0]
                if date_str != "0000-00-00":
                    dates.append(date_str)
            except:
                pass
        
        if dates:
            dates.sort()
            print(f"📅 Plus ancien: {dates[0]}")
            print(f"📅 Plus récent: {dates[-1]}")