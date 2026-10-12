"""ข่าว Arsenal / Premier League -> Claude สรุปภาษาไทย -> Telegram

MODE=digest   : สรุปข่าวทั้งหมดตั้งแต่รอบสรุปที่แล้ว (07:00, 19:00)
MODE=breaking : ส่งเฉพาะข่าวด่วนที่เพิ่งเข้ามา (ทุก 30 นาที)
"""
import json
import os
import sys
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

FEEDS = [
    "https://feeds.bbci.co.uk/sport/football/teams/arsenal/rss.xml",
    "https://www.theguardian.com/football/arsenal/rss",
    "https://feeds.bbci.co.uk/sport/football/premier-league/rss.xml",
    "https://www.theguardian.com/football/premierleague/rss",
]
MODEL = "claude-opus-5-5"  # เปลี่ยนเป็น "claude-haiku-5-5" ถ้าอยากประหยัด
STATE = "state.json"
KEEP_DAYS = 7

STYLE = ("เขียนเป็นภาษาไทย ข้อความธรรมดา ห้ามใช้ Markdown (ห้าม ** หรือ #) "
         "ใส่ลิงก์ต้นฉบับท้ายแต่ละข่าว ยาวไม่เกิน 3500 ตัวอักษร")
DIGEST = ("คุณคือผู้สรุปข่าวฟุตบอลให้แฟนอาร์เซนอล สรุปข่าวด้านล่าง "
          "แบ่งเป็น 2 หมวด: 🔴 อาร์เซนอล และ ⚽ พรีเมียร์ลีก "
          "ข่าวละ 1-2 บรรทัด รวมข่าวซ้ำเป็นข่าวเดียว ตัดข่าวไม่สำคัญทิ้ง " + STYLE)
BREAKING = ("จากข่าวด้านล่าง เลือกเฉพาะข่าวด่วนจริงๆ เช่น ซื้อขายนักเตะที่ยืนยันแล้ว "
            "ผู้เล่นหลักบาดเจ็บหนัก ปลดหรือแต่งตั้งผู้จัดการทีม ผลการแข่งขันของอาร์เซนอล "
            "โทษแบน หรือเหตุการณ์ใหญ่ในพรีเมียร์ลีก "
            "ถ้าไม่มีข่าวด่วนเลย ให้ตอบคำเดียวว่า NONE "
            "ถ้ามี ให้ขึ้นต้นด้วย 🚨 ข่าวด่วน แล้วสรุปแต่ละข่าว " + STYLE)


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def fetch():
    items = {}
    for url in FEEDS:
        try:
            root = ET.fromstring(get(url))
        except Exception as e:  # feed เดียวล่ม ไม่ควรทำให้ทั้งรอบล้ม
            print(f"skip {url}: {e}", file=sys.stderr)
            continue
        for it in root.iter("item"):
            link = (it.findtext("link") or "").strip()
            if link:
                items[link] = {"title": (it.findtext("title") or "").strip(),
                               "desc": (it.findtext("description") or "").strip()[:300],
                               "link": link}
    return list(items.values())


def update(state, items, now):
    """จดเวลาที่เห็นข่าวครั้งแรก ลบข่าวเก่าที่หลุดจาก feed แล้ว คืนรายการข่าวใหม่"""
    seen = state.setdefault("seen", {})
    current = {i["link"] for i in items}
    cutoff = (now - timedelta(days=KEEP_DAYS)).isoformat(timespec="seconds")
    for link in [k for k, t in seen.items() if t < cutoff and k not in current]:
        del seen[link]
    stamp = now.isoformat(timespec="seconds")
    new = [i for i in items if i["link"] not in seen]
    for i in new:
        seen[i["link"]] = stamp
    return new


def summarize(prompt, items):
    import anthropic  # import ตอนใช้ เทสต์จะได้รันได้โดยไม่ต้องติดตั้ง
    news = "\n\n".join(f"- {i['title']}\n  {i['desc']}\n  {i['link']}" for i in items)
    r = anthropic.Anthropic().beta.messages.create(
        model=MODEL,
        max_tokens=16000,
        output_config={"effort": "low"},  # งานสรุปข่าวไม่ต้องคิดลึก
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        messages=[{"role": "user", "content": f"{prompt}\n\n{news}"}],
    )
    if r.stop_reason == "refusal":
        raise RuntimeError(f"Claude refused: {r.stop_details}")
    return "".join(b.text for b in r.content if b.type == "text").strip()


def telegram(text):
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{os.environ['TELEGRAM_TOKEN']}/sendMessage",
        data=json.dumps({"chat_id": os.environ["TELEGRAM_CHAT_ID"], "text": text[:4096],
                         "link_preview_options": {"is_disabled": True}}).encode(),
        headers={"Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=30)


def main():
    mode = os.environ.get("MODE", "digest")
    now = datetime.now(timezone.utc)
    state = json.load(open(STATE, encoding="utf-8")) if os.path.exists(STATE) else {}
    first_run = not state.get("seen")
    items = fetch()
    new = update(state, items, now)

    if mode == "breaking":
        # ponytail: รอบแรกทุกข่าวนับเป็น "ใหม่" จึงข้ามไป ไม่งั้นจะได้ข่าวด่วนรัวๆ
        if new and not first_run:
            text = summarize(BREAKING, new[:40])
            if not text.upper().startswith("NONE"):
                telegram(text)
    else:
        since = state.get("last_digest", (now - timedelta(hours=12)).isoformat(timespec="seconds"))
        # ponytail: ใช้แค่ข่าวที่ยังอยู่ใน feed ตอนนี้; feed เก็บข่าวได้เกิน 12 ชม. จึงพอ
        recent = [i for i in items if state["seen"][i["link"]] > since]
        telegram(summarize(DIGEST, recent[:60]) if recent else "ไม่มีข่าวใหม่ในรอบนี้")
        state["last_digest"] = now.isoformat(timespec="seconds")

    # บันทึกหลังส่งสำเร็จ ถ้าส่งพัง รอบหน้าจะลองใหม่
    with open(STATE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
