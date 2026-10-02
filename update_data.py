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

        type_elem = row.find(class_=re.compile(r'recommendation_type', re.I))
        rec_type = type_elem.get_text(strip=True) if type_elem else "แนะนำ"

        parsed_items.append({
            "appid": appid,
            "name": game_name,
            "img": img_url,
            "desc": full_text,
            "url": mod_url,
            "type": rec_type,
            "price": "" # เว้นไว้ให้ฟังก์ชันดึงราคา THB จัดการต่อ
        })
    return parsed_items

def fetch_thb_prices(items):
    """ฟังก์ชันยิงดึงราคาโซนไทย (THB / ฿) โดยตรงจาก Steam Store API"""
    print(f"\n--- เริ่มต้นอัปเดตราคาเงินบาท (THB) ให้ตรงกับร้านค้าไทย ทั้งหมด {len(items)} เกม ---")
    appids = [str(item['appid']).strip() for item in items if item.get('appid')]
    
    # แบ่งกลุ่มยิงทีละ 25 เกมเพื่อป้องกัน Steam บล็อก
    chunk_size = 25
    prices_map = {}

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    }

    for i in range(0, len(appids), chunk_size):
        chunk = appids[i:i + chunk_size]
        url = "https://store.steampowered.com/api/appdetails"
        params = {
            "appids": ",".join(chunk),
            "cc": "th",         # บังคับสกุลเงินไทย (THB)
            "l": "thai",
            "filters": "price_overview"
        }

        try:
            res = requests.get(url, params=params, headers=headers, timeout=15)
            if res.status_code == 200:
                data = res.json()
                for appid in chunk:
                    app_info = data.get(str(appid), {})
                    if app_info.get("success"):
                        overview = app_info.get("data", {}).get("price_overview")
                        if not overview:
                            prices_map[appid] = "เล่นฟรี"
                        else:
                            discount = overview.get("discount_percent", 0)
                            final_formatted = overview.get("final_formatted", "")
                            if discount > 0:
                                prices_map[appid] = f"-{discount}% {final_formatted}"
                            else:
                                prices_map[appid] = final_formatted
            print(f"ดึงราคาเงินบาทสำเร็จแล้ว: {min(i + chunk_size, len(appids))}/{len(appids)} เกม")
        except Exception as e:
            print(f"ขัดข้องในการดึงราคาช่วง {i}: {e}")

        time.sleep(0.6)

    # อัปเดตราคาเงินบาทลงใน items
    for item in items:
        aid = str(item.get("appid", "")).strip()
        if aid in prices_map and prices_map[aid]:
            item["price"] = prices_map[aid]

    print("--- ดึงราคาเงินบาท (THB) ครบถ้วนทุกเกมแล้ว! ---\n")

def load_local_json():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f: return json.load(f)
        except Exception: pass
    return {"total_count": 0, "items": []}

def auto_check_and_sync():
    print("เริ่มการทำงาน: ดึงข้อมูลจาก Steam Curator...")
    url = "https://store.steampowered.com/curator/38366376-ModSubThai/ajaxgetfilteredrecommendations"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": "https://store.steampowered.com/curator/38366376-ModSubThai/"
    }
    cookies = {
        "birthtime": "-2208988799",
        "mature_content": "1",
        "wants_mature_content": "1"
    }

    local_data = load_local_json()
    local_items = local_data.get("items", [])
    items_dict = {str(item.get("appid", "")).strip(): item for item in local_items if item.get("appid")}

    offset = 0
    remote_total = 9999

    while offset < remote_total:
        params = {"start": offset, "count": 50, "tag": 0, "sort": "recent", "types": 0}
        print(f"กำลังกวาดข้อมูลม็อดจาก Curator: ตำแหน่ง {offset} ถึง {offset + 50} จาก {remote_total}...")
        
        try:
            res = requests.get(url, params=params, headers=headers, cookies=cookies, timeout=20)
            if res.status_code != 200: break
            
            data = res.json()
            remote_total = data.get("total_count", remote_total)
            page_items = parse_steam_recommendations(data.get("results_html", ""))
            
            if not page_items: break

            for item in page_items:
                appid = str(item.get("appid", "")).strip()
                if not appid: continue
                
                if appid in items_dict:
                    # อัปเดตข้อมูลม็อดโดยยังเก็บข้อมูลเดิมไว้
                    items_dict[appid]["name"] = item["name"]
                    items_dict[appid]["url"] = item["url"]
                    items_dict[appid]["img"] = item["img"]
                    items_dict[appid]["type"] = item["type"]
                else:
                    items_dict[appid] = item

            offset += 50
            time.sleep(0.5)
        except Exception as e:
            print(f"เกิดข้อผิดพลาดที่ offset {offset}: {e}")
            break

    all_items = list(items_dict.values())
    
    # ดึงราคาโซนไทย (THB) ให้กับทุกเกมที่มี
    fetch_thb_prices(all_items)

    print(f"เสร็จสิ้น! บันทึกข้อมูลทั้งหมด {len(all_items)} รายการลงไฟล์ games.json")
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump({"total_count": len(all_items), "items": all_items}, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    auto_check_and_sync()
