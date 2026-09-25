"""Probe 12: dump BS Event JSON-LD raw segment."""
import requests

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126.0 lewagon-probe/1.0"}

d = requests.get("https://balisquad.com/event/bali-volleyball-academy-70cdcJ", headers=UA, timeout=20)
i = d.text.find('"@type":"Event"')
seg = d.text[max(0, i-500):i+3000]
open("C:/code/lewagon-calendar/.logs/probe12.txt", "w", encoding="utf-8").write(seg)
print("wrote probe12.txt")
