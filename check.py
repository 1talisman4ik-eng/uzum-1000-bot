"""Uzum 1000: облачная проверка подборки. Шлёт в Telegram только стоящие товары."""
import json, os, urllib.parse, urllib.request
from pathlib import Path
from dataclasses import dataclass

URL = "https://uzum.uz/ru/promo/gift-1000"
STATE = Path("seen.json")
PROMO = 1000
MIN_SAVING, MIN_RATING, MIN_REVIEWS = 50_000, 4.5, 30

@dataclass(frozen=True)
class Item:
    pid: int
    title: str
    sell: int
    rating: float
    reviews: int
    @property
    def saving(self): return max(0, self.sell - PROMO)
    @property
    def good(self): return self.saving >= MIN_SAVING and self.rating >= MIN_RATING and self.reviews >= MIN_REVIEWS
    @property
    def score(self): return self.saving * (0.5 + 0.5 * min(1.0, self.reviews / 50) * (self.rating / 5))

def extract(node):
    found = {}
    def walk(o):
        if isinstance(o, dict):
            c = o.get("catalogCard")
            if isinstance(c, dict) and c.get("productId"):
                i = Item(int(c["productId"]), str(c.get("title", "")).strip(),
                         int(c.get("minSellPrice") or c.get("minFullPrice") or 0),
                         float(c.get("rating") or 0), int(c.get("feedbackQuantity") or 0))
                found[i.pid] = i
                return
            for v in o.values(): walk(v)
        elif isinstance(o, list):
            for v in o: walk(v)
    walk(node)
    return list(found.values())

def money(n): return f"{n:,}".replace(",", " ") + " сум"

def fmt(i):
    return (f"🔥 {i.title}\nЭкономия: {money(i.saving)} (цена {money(i.sell)} → {money(PROMO)})\n"
            f"⭐ {i.rating} ({i.reviews} отзывов)\nhttps://uzum.uz/ru/product/{i.pid}")

def fetch():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        page = b.new_context(locale="ru-RU", viewport={"width": 1280, "height": 900}).new_page()
        page.goto(URL, wait_until="domcontentloaded", timeout=60000)
        items = []
        for _ in range(25):
            d = page.evaluate("() => (window.__NUXT__ && window.__NUXT__.data) || null")
            items = extract(d) if d else []
            if items: break
            page.wait_for_timeout(1000)
        b.close()
        return items

def send(token, chat, text):
    data = urllib.parse.urlencode({"chat_id": chat, "text": text, "disable_web_page_preview": "true"}).encode()
    urllib.request.urlopen(urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=data), timeout=30).read()

def run(fetch_fn, notify):
    first = not STATE.exists()
    st = json.loads(STATE.read_text(encoding="utf-8")) if not first else {"seen": [], "empty": 0, "alerted": False}
    items = fetch_fn()
    if not items:
        st["empty"] += 1
        if st["empty"] >= 3 and not st["alerted"]:
            notify("⚠️ Не удаётся прочитать подборку Uzum (3 проверки подряд пусто). Возможно, Uzum блокирует облако или страница изменилась.")
            st["alerted"] = True
    else:
        st["empty"], st["alerted"] = 0, False
        seen = set(st["seen"])
        good = sorted([i for i in items if i.good], key=lambda i: -i.score)
        if first:
            notify(f"✅ Облачная проверка запущена. Стоящих товаров сейчас: {len(good)} из {len(items)}.")
            for i in good: notify(fmt(i))
        else:
            for i in good:
                if i.pid not in seen: notify("Новый стоящий товар за 1 000 сум\n\n" + fmt(i))
        st["seen"] = sorted(seen | {i.pid for i in items})
    STATE.write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")

if __name__ == "__main__":
    t, c = os.environ["BOT_TOKEN"], os.environ["CHAT_ID"]
    run(fetch, lambda m: send(t, c, m))
