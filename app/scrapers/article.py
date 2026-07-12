import requests
from bs4 import BeautifulSoup


def get_article_text(url: str) -> str:
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}

        response = requests.get(url, headers=headers)

        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")

        paragraphs = soup.find_all("p")

        full_text = ""
        for p in paragraphs:
            full_text += p.getText() + "\n\n"

        return full_text.strip()

    except Exception as e:
        print(f"Oops. No scrape article at {url}. Error: {e}")
        return ""
