from datetime import datetime, timedelta, timezone

from bot import update

now = datetime(2026, 10, 12, tzinfo=timezone.utc)
a, b = {"link": "a"}, {"link": "b"}
s = {}
assert update(s, [a], now) == [a]
assert update(s, [a, b], now + timedelta(hours=1)) == [b]  # a ไม่นับซ้ำ

old = (now - timedelta(days=30)).isoformat(timespec="seconds")
s["seen"] = {"a": old, "b": old}
update(s, [b], now)
assert "a" not in s["seen"] and "b" in s["seen"]  # ลบเฉพาะข่าวเก่าที่หลุด feed แล้ว
print("ok")
