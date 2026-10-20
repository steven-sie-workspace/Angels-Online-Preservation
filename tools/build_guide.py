"""Build the Illustrated Guide: one HTML page to look up IDs.

Tabs for items, pets, monsters, NPCs, maps and quests, each with search and
filters (item level, pet tier, monster level, ...). Every ID has a copy
button that puts the GM command on the clipboard (/item <id>, /quest <id> 1).

Data comes from corpus/content.db (via build_item_wiki.load_items for the
items), server/plantillas/pets.json and the map templates (who spawns where).
Pictures are decoded straight from the client paks (latest pak wins), so no
extracted folder is needed:

    py -3 tools/build_guide.py [--client ..\\client] [--out guide.html]

The page is self-contained: the icons go in as one PNG atlas (data URI).
"""
from __future__ import annotations

import argparse
import base64
import gzip
import io
import json
import re
import sqlite3
import struct
import sys
import xml.etree.ElementTree as ET
import zlib
from collections import defaultdict
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_item_wiki import load_items  # noqa: E402
from shp_icon import decode_shp_bytes  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "corpus" / "content.db"
PETS = ROOT / "server" / "plantillas" / "pets.json"
PLANTILLAS = ROOT / "server" / "plantillas"
OUT = ROOT / "guide.html"
CLIENT = ROOT.parent / "client"
SEP = "\\"
CELL = 40  # atlas cell, px

TIER = {"原型": "Egg", "初階": "Basic", "中階": "Intermediate", "高階": "Advanced", "頂階": "Top"}
TIER_ORDER = ["Egg", "Basic", "Intermediate", "Advanced", "Top"]
ELEMENT = {"不死": "Undead", "人型": "Humanoid", "動物": "Animal", "惡魔": "Demon",
           "植物": "Plant", "能量": "Energy"}
FACTION = {"怪物陣營": "Monster", "中立": "Neutral", "無陣營": "None", "光明": "Light",
           "黑暗": "Dark", "渾沌": "Chaos", "大地": "Earth", "PK": "PK"}
PET_TYPE = {
    "萬能型": "All-round", "強攻型": "Power", "魔力型": "Mana", "攻防並重型": "Balanced",
    "魔攻型": "Magic Attack", "輔助攻擊型": "Support (Attack)", "堅守型": "Steadfast",
    "迅捷型": "Swift", "輔助回復型": "Support (Heal)", "大地強壯型": "Earth Sturdy",
    "風雷迅速型": "Wind-Thunder Swift", "攻擊型": "Attack", "平均型": "Average",
    "硬漢型": "Tough", "火焰攻擊型": "Flame Attack", "防禦型": "Defense",
    "寒冰防禦型": "Ice Defense", "血牛型": "HP Tank", "遠程攻擊型": "Ranged",
    "火屬性攻擊型": "Fire Attack", "敏捷型": "Agile", "雷屬性敏捷型": "Thunder Agile",
    "風雷迅捷型": "Wind-Thunder Swift", "水屬性平均型": "Water Average", "監守型": "Guardian",
}
QUEST_LV = re.compile(r"(?i)lv\.?l?\s*(\d+)\s*-\s*(.*)")
COLOR_CODE = re.compile(r"/c\S|/\d+|%\d+%|\\n")

# Chinese text: the per-language tables idioma_cliente.py put in the paks
# (SETTING\CHT, SETTING\CHS). A record keeps <field>_t / <field>_s only where
# that text exists and differs from the English one; the page falls back to
# English. _s is left out when the t2s char map turns _t into it anyway.
KANA = re.compile(r"[぀-ヿｦ-ﾟ]")   # Global's Japanese leftovers
CJK = re.compile(r"[㐀-鿿]")
SKILL_RANK = re.compile(r"\s*([Ⅰ-Ⅻ]+|[IVX]+|\d+)$")
# Item kinds and groups are the guide's own English categories (build_item_wiki).
VOCAB_T = {
    "Accessory": "飾品", "Advancement Stone": "進階石", "Ammo": "彈藥", "Antidote": "解毒劑",
    "Arrow": "箭矢", "Astrolabe Bingo": "星盤賓果", "Astrolabe Draw": "星盤抽獎", "Axe": "斧",
    "Backpack": "背包", "Badge": "徽章", "Body Armor": "衣服", "Boots": "鞋子", "Bow": "弓箭",
    "Buff": "增益道具", "Bug Spray": "殺蟲劑", "Card": "卡片", "Cash Item": "商城道具",
    "Chair": "椅子", "Chat Bubble": "聊天泡泡", "Cloak": "披風", "Cloth": "布料",
    "Crystal": "晶石", "DNA Item": "DNA道具", "Defense Tower": "防禦塔", "EXP Card": "經驗卡",
    "EXP Orb": "經驗珠", "EXP Scroll": "經驗卷軸", "EXP Stone": "經驗石", "Emote Card": "表情卡",
    "Empty Catch Egg": "空捕捉蛋", "Enchant": "附魔", "Enhance Feed": "強化飼料",
    "Enhance Tool": "強化工具", "Farm Seed": "農作種子", "Fashion": "時裝",
    "Fashion Body": "時裝衣服", "Fashion Feet": "時裝鞋子", "Fashion Hands": "時裝手套",
    "Fashion Head": "時裝頭飾", "Fashion Wings": "時裝翅膀", "Fish": "魚", "Fishing Float": "浮標",
    "Fishing Rod": "釣竿", "Floor": "地板", "Food": "食物", "Furniture": "家具",
    "Furniture Egg": "家具蛋", "Fusion Agent": "融合劑", "Gacha Egg": "扭蛋", "Gem": "寶石",
    "Gem Dig Tool": "挖寶工具", "General": "一般", "Gift": "禮物", "Gloves": "手套", "Gold": "金幣",
    "HP Potion": "HP藥水", "Hammer": "錘", "Headgear": "頭飾", "Herb": "藥草", "Hidden": "隱藏",
    "House": "房屋", "House Skin": "房屋外觀", "Key": "鑰匙", "Letter Card": "字母卡",
    "Lucky Bag": "福袋", "Lucky Dice": "幸運骰子", "MP Potion": "MP藥水", "Magic Dice": "魔法骰子",
    "Magic Scroll": "魔法卷軸", "Map Piece": "地圖碎片", "Meat": "肉類", "Mecha": "機甲",
    "Mecha Part": "機甲零件", "Minigame": "小遊戲", "Monster Card": "怪物卡",
    "Monster Egg": "魔獸蛋", "Mount": "坐騎", "Order": "訂單", "Ore": "礦石",
    "Pachinko Ball": "鋼珠", "Pet": "寵物", "Pet Accessory": "寵物飾品", "Pet Armor": "寵物防具",
    "Pet EXP Orb": "寵物經驗珠", "Pet Enhance": "寵物強化", "Pet Gem": "寵物寶石",
    "Pet Revive": "寵物復活", "Pet Weapon": "寵物武器", "Potion": "藥水", "Recipe": "配方",
    "Red Packet": "紅包", "Rename": "改名", "Sabre": "刀", "Scroll": "卷軸", "Shadow Blade": "影刃",
    "Shapeshift": "變身", "Shield": "盾", "Shovel": "鏟子", "Skill EXP Orb": "技能經驗珠",
    "Skill Leveling Stone": "技能升級石", "Skill Scroll": "技能卷軸", "Slingshot": "彈弓",
    "Socket Tool": "打孔工具", "Spear": "槍", "Special Shard": "特殊碎片",
    "Speed Fertilizer": "速效肥料", "Staff": "杖", "Suit Egg": "套裝蛋", "Sword": "劍",
    "Table": "桌子", "Teleport": "傳送", "Token": "代幣", "Unknown": "未知", "Wall": "牆壁",
    "Weapon Egg": "武器蛋", "Wood": "木材",
    "Accessories": "飾品", "Armor": "防具", "Cards": "卡片", "Consumables": "消耗品",
    "Eggs & Gifts": "蛋與禮物", "Farming": "農場", "Gems": "寶石", "Housing": "房屋",
    "Materials": "材料", "Mounts": "坐騎", "Other": "其他", "Pets": "寵物",
    "Scrolls & Recipes": "卷軸與配方", "Tools": "工具", "Weapons": "武器",
}
for _zh_en in (TIER, ELEMENT, PET_TYPE):
    for _zh, _en in _zh_en.items():
        VOCAB_T.setdefault(_en, _zh)
# Simplified forms the data never pairs up (UI words and vocab only).
T2S_EXTRA = dict(zip("錘鏟骰飼釣盤賓獎襲殺劑階聖寵獸寶裝飾鞋盾頭陣營傳鑰匙紅幣復隱變機甲訂礦藥卷軸農場區圖顯示搜尋類別篩選無結果載入資料請開啟頁複製詳細連結給任務階級經驗掉落進化來源地點為與屬",
                     "锤铲骰饲钓盘宾奖袭杀剂阶圣宠兽宝装饰鞋盾头阵营传钥匙红币复隐变机甲订矿药卷轴农场区图显示搜寻类别筛选无结果载入资料请开启页复制详细连结给任务阶级经验掉落进化来源地点为与属"))


# ---------------------------------------------------------------- paks
def _pak_order(p: Path) -> int:
    n = p.stem.lower()
    if n == "data1":
        return -1
    if n == "update":
        return 0
    m = re.search(r"(\d+)$", n)
    return int(m.group(1)) if m else 999


class Paks:
    """Latest-wins view of every file in the client paks (OD\\x05\\x06 format)."""

    def __init__(self, client: Path):
        self.files: dict[str, tuple[Path, int, int, int]] = {}
        self.blobs: dict[Path, bytes] = {}
        paks = [p for p in client.iterdir()
                if p.suffix.lower() == ".pak" and p.stem.lower() != "music"]
        for pak in sorted(paks, key=_pak_order):
            data = pak.read_bytes()
            eocd = bytearray(data[-22:])
            if eocd[:4] != b"OD\x05\x06":
                continue
            for i in range(4, 22):
                eocd[i] ^= (3 * i - 91) & 0xFF
            cd_off = struct.unpack_from("<I", eocd, 16)[0]
            # The 16-bit compressed size overflows on big paks: inflate to the end.
            raw = bytearray(data[cd_off + 4:len(data) - 22])
            raw[0] ^= 0x7A
            cd = zlib.decompressobj().decompress(bytes(raw))
            self.blobs[pak] = data
            off = 0
            while off + 46 <= len(cd):
                f = struct.unpack_from("<IHHHHHHIIIHHHHHII", cd, off)
                name = cd[off + 46:off + 46 + f[10]].decode("latin1").upper().replace("/", SEP)
                self.files[name] = (pak, f[4], f[8], f[16])
                off += 46 + f[10] + f[11] + f[12]

    def read(self, name: str) -> bytes | None:
        hit = self.files.get(name.upper().replace("/", SEP))
        if not hit:
            return None
        pak, method, size, off = hit
        raw = self.blobs[pak][off:off + size]
        return zlib.decompress(raw, -15) if method == 8 else raw


def icon_map(paks: Paks, pattern: str) -> dict[int, str]:
    """icon id -> SHAPE path, merged over every matching *ICON*.XML."""
    out: dict[int, str] = {}
    names = sorted(n for n in paks.files if re.fullmatch(pattern, n))
    for name in names:
        txt = paks.read(name).decode("utf-8", "replace").lstrip("﻿")
        txt = re.sub(r"<\?xml[^>]*\?>", "", txt)
        try:
            root = ET.fromstring(txt)
        except ET.ParseError:
            continue
        for el in root.iter("icon"):
            try:
                iid = int(el.attrib.get("id", "0"))
            except ValueError:
                continue
            stem = (el.attrib.get("normal") or "").strip()
            folder = (el.attrib.get("dir") or "").strip("\\/")
            if iid and stem and stem not in ("normal", "nullshp") and folder:
                out[iid] = f"SHAPE{SEP}{folder}{SEP}{stem}.SHP".upper()
    return out


class Atlas:
    def __init__(self, paks: Paks):
        self.paks = paks
        self.cells: list[Image.Image] = []
        self.index: dict[str, int] = {}

    def add(self, shp: str | None) -> int:
        if not shp:
            return -1
        if shp in self.index:
            return self.index[shp]
        data = self.paks.read(shp)
        img = decode_shp_bytes(data) if data else None
        if img is not None:
            box = img.getbbox()
            img = img.crop(box) if box else None
        if img is None:
            self.index[shp] = -1
            return -1
        img.thumbnail((CELL, CELL), Image.NEAREST)
        cell = Image.new("RGBA", (CELL, CELL), (0, 0, 0, 0))
        cell.paste(img, ((CELL - img.width) // 2, (CELL - img.height) // 2))
        self.cells.append(cell)
        self.index[shp] = len(self.cells) - 1
        return self.index[shp]

    def png(self) -> tuple[str, int]:
        cols = 64
        rows = max(1, -(-len(self.cells) // cols))
        sheet = Image.new("RGBA", (cols * CELL, rows * CELL), (0, 0, 0, 0))
        for i, cell in enumerate(self.cells):
            sheet.paste(cell, ((i % cols) * CELL, (i // cols) * CELL))
        buf = io.BytesIO()
        # Lossless WebP is half the size of the PNG and keeps the pixel art exact.
        sheet.save(buf, "WEBP", lossless=True, method=6)
        return base64.b64encode(buf.getvalue()).decode(), cols


# ---------------------------------------------------------------- data
def num(v) -> int:
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return 0


def tidy(text) -> str:
    return re.sub(r"\s+", " ", COLOR_CODE.sub(" ", str(text or ""))).strip()


def zh_text(text, limit: int = 0) -> str:
    """Tidied Chinese text, or "" when it is missing, Japanese or still English."""
    t = tidy(text)
    if not t or KANA.search(t) or not CJK.search(t):
        return ""
    return t[:limit] if limit else t


class Chinese:
    """SETTING\\CHT and SETTING\\CHS tables by id, plus a Traditional->Simplified char map."""

    def __init__(self, paks: Paks):
        self.t: dict[str, dict[int, dict]] = {}
        self.s: dict[str, dict[int, dict]] = {}
        for lang, out in (("CHT", self.t), ("CHS", self.s)):
            for key, pattern in (("item", r"ITEM\d*"), ("monster", "MONSTER"), ("npc", "NPC"),
                                 ("stage", "STAGE"), ("quest", "QUEST"), ("pet", "PET"),
                                 ("magic", "MAGIC")):
                rec: dict[int, dict] = {}
                names = sorted((n for n in paks.files
                                if re.fullmatch(rf"SETTING\\{lang}\\{pattern}\.XML", n)),
                               key=lambda n: int(re.sub(r"\D", "", n.split(SEP)[-1]) or 0))
                for name in names:
                    txt = paks.read(name).decode("utf-8", "replace").lstrip("﻿")
                    try:
                        root = ET.fromstring(re.sub(r"<\?xml[^>]*\?>", "", txt))
                    except ET.ParseError:
                        continue
                    for el in root:
                        iid = num(el.attrib.get("編號"))
                        if iid:
                            rec[iid] = el.attrib
                out[key] = rec
        self.map = self._char_map()

    def _char_map(self) -> dict[str, str]:
        """Vote per char over every same-length CHT/CHS text pair."""
        votes: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        for key, rows in self.t.items():
            other = self.s.get(key, {})
            for iid, a in rows.items():
                b = other.get(iid)
                if not b:
                    continue
                for field, tv in a.items():
                    sv = b.get(field)
                    if not sv or len(sv) != len(tv) or tv == sv or not CJK.search(tv):
                        continue
                    for ct, cs in zip(tv, sv):
                        if CJK.match(ct) and CJK.match(cs):
                            votes[ct][cs] += 1
        out = {}
        for ct, v in votes.items():
            cs, n = max(v.items(), key=lambda kv: kv[1])
            if cs != ct and n >= 2 and n * 2 > sum(v.values()):
                out[ct] = cs
        for ct, cs in T2S_EXTRA.items():
            out.setdefault(ct, cs)
        return {ct: cs for ct, cs in out.items() if ct != cs}

    def conv(self, text: str) -> str:
        return "".join(self.map.get(c, c) for c in text)

    def put(self, row: dict, key: str, t: str, s: str, en: str = "") -> None:
        """Attach <key>_t / <key>_s to row (see the comment at the top)."""
        if t and t != en:
            row[key + "_t"] = t
        else:
            t = ""
        if s and s != en and s != self.conv(t or en):
            row[key + "_s"] = s

    def attr(self, lang: str, table: str, iid: int, field: str, limit: int = 0) -> str:
        rows = self.t if lang == "t" else self.s
        return zh_text(rows.get(table, {}).get(iid, {}).get(field), limit)

    def both(self, row: dict, key: str, table: str, iid: int, field: str, limit: int = 0) -> None:
        self.put(row, key, self.attr("t", table, iid, field, limit),
                 self.attr("s", table, iid, field, limit), row.get(key, ""))

    def item_name(self, lang: str, iid: int) -> str:
        rows = self.t if lang == "t" else self.s
        a = rows.get("item", {}).get(iid)
        if not a:
            return ""
        name = zh_text(a.get("基本名稱"))
        if not name:
            return ""
        prefix = tidy(a.get("原型名稱"))
        if prefix and prefix not in name:
            name = prefix + ("" if prefix.endswith(("-", "－")) else " ") + name
        return name

    def skill(self, lang: str, ranks: list) -> str:
        for mid in ranks or []:
            name = self.attr(lang, "magic", num(mid), "名稱")
            if name:
                return SKILL_RANK.sub("", name)
        return ""


def load_spawns() -> tuple[dict, dict, dict]:
    """monster id -> stages, npc id -> stages, stage -> (monsters, npcs)."""
    mon, npc = defaultdict(set), defaultdict(set)
    stage_mon, stage_npc = defaultdict(set), defaultdict(set)
    for f in PLANTILLAS.glob("*.json"):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except (ValueError, UnicodeDecodeError):
            continue
        if not isinstance(d, dict) or "spawns" not in d or not d.get("stage"):
            continue
        st = num(d["stage"])
        for s in d["spawns"]:
            t = num(s.get("npc_type"))
            if not t:
                continue
            if s.get("monstruo"):
                mon[t].add(st)
                stage_mon[st].add(t)
            else:
                npc[t].add(st)
                stage_npc[st].add(t)
    return mon, npc, {"m": stage_mon, "n": stage_npc}


def build(client: Path) -> dict:
    paks = Paks(client)
    print(f"  {len(paks.files)} files in {len(paks.blobs)} paks")
    atlas = Atlas(paks)
    item_icons = icon_map(paks, r"SETTING\\ITEMICON\d*\.XML")
    pet_icons = icon_map(paks, r"SETTING\\PETICON\.XML")
    print(f"  {len(item_icons)} item icons, {len(pet_icons)} pet portraits")
    zh = Chinese(paks)
    print(f"  chinese: {len(zh.t['item'])} / {len(zh.s['item'])} items, {len(zh.map)} t2s chars")

    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row

    # items ---------------------------------------------------------
    items = load_items()
    pet_of_item: dict[int, int] = {}
    for t in ("item", "item2", "item3", "item4", "item5", "item6", "item7", "item8", "item9"):
        cols = {c[1] for c in con.execute(f"pragma table_info({t})")}
        if "動態資料1" not in cols:
            continue
        for r in con.execute(f"select id, 動態資料1 from {t} where 物品類別 in ('寵物','寵物蛋','魔獸蛋')"):
            if num(r[1]):
                pet_of_item[num(r[0])] = num(r[1])
    for it in items:
        it.pop("raw", None)
        it.pop("prefix", None)
        it["ic"] = atlas.add(item_icons.get(it.pop("icon", 0)))
        if it["id"] in pet_of_item:
            it["pet"] = pet_of_item[it["id"]]
        zh.put(it, "name", zh.item_name("t", it["id"]), zh.item_name("s", it["id"]), it["name"])
        zh.both(it, "desc", "item", it["id"], "說明定義", 180)
    item_name = {it["id"]: it["name"] for it in items}
    print(f"  {len(items)} items")

    # stages --------------------------------------------------------
    stages = {num(r["id"]): tidy(r["name"]) for r in con.execute("select id, name from stage")}
    mon_at, npc_at, by_stage = load_spawns()

    # drops ---------------------------------------------------------
    drops: dict[int, list[int]] = {}
    for r in con.execute("select * from drop_table"):
        ids = [num(r[f"item{i}"]) for i in range(1, 21)]
        drops[num(r["id"])] = [i for i in ids if i in item_name]

    # monsters ------------------------------------------------------
    monsters = []
    dropped_by = defaultdict(list)
    for r in con.execute("select id, name, level, element, faction, hp, exp_value, drop_id, 王 from monster"):
        mid, name = num(r["id"]), tidy(r["name"])
        if not name:
            continue
        m = {"id": mid, "name": name, "lv": num(r["level"])}
        zh.both(m, "name", "monster", mid, "名稱")
        if r["element"]:
            m["el"] = ELEMENT.get(r["element"], r["element"])
        if num(r["hp"]):
            m["hp"] = num(r["hp"])
        if num(r["exp_value"]):
            m["exp"] = num(r["exp_value"])
        if r["王"] == "是":
            m["boss"] = 1
        d = drops.get(num(r["drop_id"]))
        if d:
            m["drops"] = d
            for iid in d:
                if len(dropped_by[iid]) < 40:
                    dropped_by[iid].append(mid)
        if mon_at.get(mid):
            m["maps"] = sorted(mon_at[mid])
        monsters.append(m)
    for it in items:
        if it["id"] in dropped_by:
            it["from"] = dropped_by[it["id"]]
    print(f"  {len(monsters)} monsters")

    # npcs ----------------------------------------------------------
    npcs = []
    for r in con.execute("select id, name, level, faction from npc"):
        name = tidy(r["name"])
        if not name:
            continue
        n = {"id": num(r["id"]), "name": name}
        zh.both(n, "name", "npc", n["id"], "名稱")
        if n["id"] in npc_at:
            n["maps"] = sorted(npc_at[n["id"]])
        npcs.append(n)
    print(f"  {len(npcs)} npcs")

    # maps ----------------------------------------------------------
    maps = []
    for sid, name in sorted(stages.items()):
        if not name:
            continue
        row = {"id": sid, "name": name}
        zh.both(row, "name", "stage", sid, "名稱")
        if by_stage["m"].get(sid):
            row["mons"] = sorted(by_stage["m"][sid])
        if by_stage["n"].get(sid):
            row["npcs"] = sorted(by_stage["n"][sid])
        maps.append(row)

    # quests --------------------------------------------------------
    quests = []
    for r in con.execute("select id, 任務名稱, 任務類型, 承接, 地點, 任務前言 from quest"):
        name = tidy(r["任務名稱"])
        if not name:
            continue
        q = {"id": num(r["id"]), "name": name}
        if r["任務類型"]:
            q["type"] = tidy(r["任務類型"])
        giver = tidy(r["承接"])
        m = QUEST_LV.match(giver)
        if m:
            q["lv"] = int(m.group(1))
            giver = m.group(2).strip()
        if giver:
            q["npc"] = giver
        if r["地點"]:
            q["at"] = tidy(r["地點"])
        if r["任務前言"]:
            q["desc"] = tidy(r["任務前言"])[:220]
        qid = q["id"]
        zh.both(q, "name", "quest", qid, "任務名稱")
        zh.both(q, "type", "quest", qid, "任務類型")
        zh.both(q, "at", "quest", qid, "地點")
        zh.both(q, "desc", "quest", qid, "任務前言", 220)
        givers = []
        for lang in ("t", "s"):
            g = zh.attr(lang, "quest", qid, "承接")
            m = QUEST_LV.match(g)
            givers.append(m.group(2).strip() if m else g)
        zh.put(q, "npc", givers[0], givers[1], q.get("npc", ""))
        quests.append(q)
    print(f"  {len(quests)} quests")

    # pets ----------------------------------------------------------
    pj = json.loads(PETS.read_text(encoding="utf-8"))
    skill_name = {int(k): v["name"] for k, v in pj["skills"].items()}
    skill_zh = {int(k): (zh.skill("t", v.get("ranks")), zh.skill("s", v.get("ranks")))
                for k, v in pj["skills"].items()}
    items_of_pet = defaultdict(list)
    item_level = {it["id"]: it.get("level", 0) for it in items}
    for iid, pid in pet_of_item.items():
        if iid in item_name:
            items_of_pet[pid].append(iid)
    prev = defaultdict(list)
    for pid, p in pj["pets"].items():
        for n in p.get("next") or []:
            prev[int(n)].append(int(pid))
    pets = []
    for pid_s, p in pj["pets"].items():
        pid = int(pid_s)
        row = {"id": pid, "name": tidy(p.get("name")) or f"Pet {pid}",
               "ic": atlas.add(pet_icons.get(num(p.get("portrait")))),
               "tier": TIER.get(p.get("stage"), p.get("stage") or ""),
               "type": PET_TYPE.get(p.get("type"), p.get("type") or ""),
               "el": ELEMENT.get(p.get("element"), p.get("element") or "")}
        if p.get("next"):
            row["next"] = [int(n) for n in p["next"]]
        if prev.get(pid):
            row["prev"] = sorted(prev[pid])
        zh.both(row, "name", "pet", pid, "名稱")
        ids = [int(s) for s in p.get("skills") or [] if skill_name.get(int(s))]
        if ids:
            row["skills"] = [skill_name[s] for s in ids]
            sk_t = [skill_zh[s][0] or skill_name[s] for s in ids]
            sk_s = [skill_zh[s][1] or zh.conv(sk_t[i]) for i, s in enumerate(ids)]
            if sk_t != row["skills"]:
                row["skills_t"] = sk_t
            if sk_s != [zh.conv(x) for x in sk_t]:
                row["skills_s"] = sk_s
        its = sorted(items_of_pet.get(pid, []))
        if its:
            row["items"] = its
            lv = [item_level[i] for i in its if item_level.get(i)]
            if lv:
                row["lv"] = min(lv)
        if p.get("stats"):
            row["stats"] = p["stats"]
        pets.append(row)
    pets.sort(key=lambda r: r["id"])
    print(f"  {len(pets)} pets")
    con.close()

    sheet, cols = atlas.png()
    print(f"  atlas {len(atlas.cells)} icons, {len(sheet) // 1024} KB")
    return {"sheet": sheet, "cols": cols, "cell": CELL, "items": items, "pets": pets,
            "monsters": monsters, "npcs": npcs, "maps": maps, "quests": quests,
            "tiers": TIER_ORDER, "vocab": VOCAB_T,
            "t2s": "".join(f"{a}{b}" for a, b in sorted(zh.map.items()))}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--client", type=Path, default=CLIENT)
    ap.add_argument("--out", type=Path, default=OUT)
    a = ap.parse_args()
    print(f"reading {a.client}")
    data = build(a.client)
    sheet = data.pop("sheet")
    # ~20 MB of JSON gzips to ~3 MB; the page inflates it with DecompressionStream.
    blob = gzip.compress(json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8"), 9)
    html = ((ROOT / "tools" / "guide_template.html").read_text(encoding="utf-8")
            .replace("__SHEET__", sheet)
            .replace("__DATA__", base64.b64encode(blob).decode()))
    a.out.write_text(html, encoding="utf-8")
    print(f"wrote {a.out} ({a.out.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
