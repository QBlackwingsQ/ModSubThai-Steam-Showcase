import os
import json
import requests
from bs4 import BeautifulSoup
import re
import time

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mod_data")
DATA_FILE = os.path.join(DATA_DIR, "games.json")

def parse_steam_recommendations(html_data):
    if not html_data: 
        return []
    soup = BeautifulSoup(html_data, 'html.parser')
    rows = soup.find_all('div', class_=re.compile(r'\brecommendation\b', re.I))
    if not rows:
        rows = [elem.find_parent('div', class_=re.compile(r'recommendation', re.I)) or elem for elem in soup.select('[data-ds-appid]')]

    parsed_items = []
    seen = set()
    for row in rows:
        if not row: 
            continue
        appid_elem = row if row.get('data-ds-appid') else row.find(attrs={'data-ds-appid': True})
        appid = appid_elem.get('data-ds-appid') if appid_elem else ""
        if not appid:
            link = row.find('a', href=re.compile(r'/app/(\d+)'))
            if link:
                m = re.search(r'/app/(\d+)', link['href'])
                if m: 
                    appid = m.group(1)
        if not appid or appid in seen: 
            continue
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

        type_elem = row.find(class_=re.compile(r'recommendation_type', re.I))
        rec_type = type_elem.get_text(strip=True) if type_elem else "แนะนำ"

        parsed_items.append({
            "appid": appid,
            "name": game_name,
            "img": img_url,
            "desc": full_text,
            "url": mod_url,
            "type": rec_type,
            "price": "ฟรี / Mod"
        })
    return parsed_items

def get_thai_price(appid, session):
    """ฟังก์ชันดึงราคาโซนไทย (THB) ตรงจาก Steam Store API"""
    url = "https://store.steampowered.com/api/appdetails"
    params = {
        "appids": appid,
        "cc": "th",         # บังคับสกุลเงินไทย (THB)
        "l": "thai",
        "filters": "price_overview"
    }
    try:
        res = session.get(url, params=params, timeout=5)
        if res.status_code == 200:
            data = res.json().get(str(appid), {})
            if data.get("success"):
                overview = data.get("data", {}).get("price_overview")
                if not overview:
                    return "เล่นฟรี"
                discount = overview.get("discount_percent", 0)
                final_price = overview.get("final_formatted", "")
                if discount > 0:
                    return f"-{discount}% {final_price}"
                return final_price
    except Exception:
        pass
    return None

def auto_check_and_sync():
    print("=== [ขั้นตอนที่ 1] กวาดข้อมูลม็อดทั้งหมดจาก Curator ===")
    url = "https://store.steampowered.com/curator/38366376-ModSubThai/ajaxgetfilteredrecommendations"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json"
    }

    all_games_map = {}
    offset = 0
    remote_total = 9999

    while offset < remote_total:
        params = {"start": offset, "count": 50, "tag": 0, "sort": "recent", "types": 0}
        print(f"กำลังดึงข้อมูลตำแหน่ง {offset} ถึง {offset + 50} จาก {remote_total}...")
        try:
            res = requests.get(url, params=params, headers=headers, timeout=20)
            if res.status_code != 200:
                break
            data = res.json()
            remote_total = data.get("total_count", remote_total)
            page_items = parse_steam_recommendations(data.get("results_html", ""))
            
            if not page_items:
                break

            for item in page_items:
                aid = str(item.get("appid", "")).strip()
                if aid and aid not in all_games_map:
                    all_games_map[aid] = item

            offset += 50
            time.sleep(0.3)
        except Exception as e:
            print(f"ขัดข้องที่ offset {offset}: {e}")
            break

    items_list = list(all_games_map.values())
    print(f"\nพบเกมทั้งหมด: {len(items_list)} รายการ")

    print("\n=== [ขั้นตอนที่ 2] ดึงราคาเงินบาท (THB) ตรงจาก Steam Store API ===")
    session = requests.Session()
    session.headers.update(headers)

    for idx, game in enumerate(items_list):
        aid = game.get("appid")
        th_price = get_thai_price(aid, session)
        if th_price:
            game["price"] = th_price
        
        # แสดงสถานะทุกๆ 20 เกม
        if (idx + 1) % 20 == 0 or (idx + 1) == len(items_list):
            print(f"อัปเดตราคาแล้ว: {idx + 1}/{len(items_list)} เกม")
        
        time.sleep(0.1) # หน่วงเวลาเล็กน้อยเพื่อป้องกัน Rate Limit

    # เขียนไฟล์ใหม่แบบ Clean ทันที
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump({"total_count": len(items_list), "items": items_list}, f, ensure_ascii=False, indent=2)

    print("\n บันทึกไฟล์ mod_data/games.json แบบคลีนสมบูรณ์เรียบร้อยแล้วค่ะ!")

if __name__ == "__main__":
    auto_check_and_sync()
