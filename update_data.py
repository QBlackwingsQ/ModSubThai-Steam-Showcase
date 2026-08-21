import os
import json
import requests
from bs4 import BeautifulSoup
import re
import time

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mod_data")
DATA_FILE = os.path.join(DATA_DIR, "games.json")

def parse_steam_recommendations(html_data):
    if not html_data: return []
    soup = BeautifulSoup(html_data, 'html.parser')
    rows = soup.find_all('div', class_=re.compile(r'\brecommendation\b', re.I))
    if not rows:
        rows = [elem.find_parent('div', class_=re.compile(r'recommendation', re.I)) or elem for elem in soup.select('[data-ds-appid]')]

    parsed_items = []
    seen = set()
    for row in rows:
        if not row: continue
        appid_elem = row if row.get('data-ds-appid') else row.find(attrs={'data-ds-appid': True})
        appid = appid_elem.get('data-ds-appid') if appid_elem else ""
        if not appid:
            link = row.find('a', href=re.compile(r'/app/(\d+)'))
            if link:
                m = re.search(r'/app/(\d+)', link['href'])
                if m: appid = m.group(1)
        if not appid or appid in seen: continue
        seen.add(appid)

        img_tag = row.find('img')
        if img_tag and 'src' in img_tag.attrs and img_tag['src'].startswith('http'):
            img_url = img_tag['src']
        elif appid:
            img_url = f"https://cdn.cloudflare.steamstatic.com/steam/apps/{appid}/header.jpg"
        else:
            img_url = "https://cdn.cloudflare.steamstatic.com/steam/apps/641990/header.jpg"

        full_text = row.get_text(separator=" ", strip=True)
        game_name = ""
        title_elem = row.find(class_=re.compile(r'(app_title|title|game_name|app_name)', re.I))
        if title_elem and len(title_elem.get_text(strip=True)) > 1:
            game_name = title_elem.get_text(strip=True)
        elif img_tag and img_tag.get('alt') and len(img_tag['alt']) > 1:
            game_name = img_tag['alt']

        if not game_name or len(game_name) < 2:
            name_match = re.search(r"Mod\s*(?:ภาษา|ซับ|แปล)?ไทย\s*:?\s*(.*?)\s*(?:โหลดได้ที่|ดาวน์โหลดที่|ดาวน์โหลด|โหลดที่|ลิงก์|link|ลิ้ง|โหลด\s*:|:|$|http|www\.)", full_text, re.IGNORECASE)
            if name_match and len(name_match.group(1).strip()) > 1:
                game_name = name_match.group(1).strip().strip('“”"\' :')
            else:
                game_name = f"Steam Game #{appid}"

        url_match = re.search(r'(https?://[^\s"“”\'<>]+|(?:www\.)[^\s"“”\'<>]+|[a-zA-Z0-9][-a-zA-Z0-9]*\.(?:com|net|org|app|io|th|gg|me|dev|cc|xyz|co|info|tv|site|online|link|page|to|space|tech|github\.io|vercel\.app)(?:/[^\s"“”\'<>]*)?)', full_text, re.IGNORECASE)
        if url_match:
            extracted_url = url_match.group(1).rstrip('”"\'.,;:)')
            mod_url = extracted_url if extracted_url.startswith(('http://', 'https://')) else f"https://{extracted_url}"
        elif appid:
            mod_url = f"https://store.steampowered.com/app/{appid}/"
        else:
            mod_url = "#"

        price = ""
        final_price = row.find(class_=re.compile(r'(discount_final_price|game_purchase_price)', re.I))
        if final_price: price = final_price.get_text(strip=True)

        type_elem = row.find(class_=re.compile(r'recommendation_type', re.I))
        rec_type = type_elem.get_text(strip=True) if type_elem else "แนะนำ"

        parsed_items.append({"appid": appid, "name": game_name, "img": img_url, "desc": full_text, "url": mod_url, "type": rec_type, "price": price})
    return parsed_items

def load_local_json():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f: return json.load(f)
        except Exception: pass
    return {"total_count": 0, "items": []}

def auto_check_and_sync():
    print("เริ่มการทำงาน: ดึงข้อมูลจาก Steam...")
    url = "https://store.steampowered.com/curator/38366376-ModSubThai/ajaxgetfilteredrecommendations"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": "https://store.steampowered.com/curator/38366376-ModSubThai/",
        "Accept-Language": "th-TH,th;q=0.9,en;q=0.8"
    }
    cookies = {"birthtime": "-2208988799", "mature_content": "1", "wants_mature_content": "1", "Steam_Language": "thai"}

    local_data = load_local_json()
    local_items = local_data.get("items", [])
    known_ids = {str(item.get("appid", "")).strip() for item in local_items}
    
    new_items = []
    offset = 0
    remote_total = local_data.get("total_count", len(local_items))

    while True:
        params = {"start": offset, "count": 50, "tag": 0, "sort": "recent", "types": 0}
        res = requests.get(url, params=params, headers=headers, cookies=cookies, timeout=10)
        if res.status_code != 200: break
        
        data = res.json()
        remote_total = data.get("total_count", remote_total)
        page_items = parse_steam_recommendations(data.get("results_html", ""))
        if not page_items: break

        unknown_on_page = []
        for item in page_items:
            appid = str(item.get("appid", "")).strip()
            if appid and appid not in known_ids:
                known_ids.add(appid)
                unknown_on_page.append(item)
        new_items.extend(unknown_on_page)

        # หากไม่มีข้อมูลใหม่ในหน้านี้ แปลว่าดึงครบแล้ว
        if not unknown_on_page or offset + 50 >= remote_total:
            break
        offset += 50
        time.sleep(0.5)

    if new_items:
        print(f"พบข้อมูลมอดใหม่: {len(new_items)} เกม!")
        updated_items = new_items + [item for item in local_items if str(item.get("appid", "")).strip() not in {str(it.get("appid", "")).strip() for it in new_items}]
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump({"total_count": remote_total, "items": updated_items}, f, ensure_ascii=False, indent=2)
    else:
        print("ข้อมูลเป็นปัจจุบันแล้ว ไม่พบมอดใหม่")

if __name__ == "__main__":
    auto_check_and_sync()