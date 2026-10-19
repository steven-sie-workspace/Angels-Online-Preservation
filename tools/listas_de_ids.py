"""Genera las listas de IDs en markdown, en chino tradicional.

    docs/PET_EGG_IDS.md      los huevos: items de mascota en 原型 y sus dos
                             evoluciones
    docs/FUSION_PET_IDS.md   las mascotas de item que nacen ya en 頂階
                             (fusion y monstruo), mas los huevos/bolsas de
                             fusion y las pociones de fusion
    docs/ITEM_IDS.md         indice de todos los items por categoria
    docs/items/*.md          una tabla por categoria

Los IDs y categorias salen de corpus/content.db (item ... item9; gana la
tabla posterior, igual que en el cliente IGG que usa el servidor). Los
NOMBRES en chino tradicional salen del cliente de Global
(../Angels Online Global), que trae los textos por idioma en
SETTING\\BIG5\\STRING:

    STR_ITEM*.XML  id 1140000000 + item   文字1 prefijo, 文字2 nombre, 文字3 descripcion
    STR_PET.XML    id 1210000000 + sprite 文字1 nombre

El nombre que ensena el juego es 文字1 + 文字2 ("見習" + "短劍"). Un id que
Global no trae se queda con el nombre de content.db. Global y IGG comparten
los ids, pero no siempre: si el nombre ingles de Global (SETTING\\ENG) no es
el de content.db, el item lleva una ※ porque el texto chino podria ser de
otro item.

    python tools/listas_de_ids.py
"""
import difflib
import json
import pathlib
import re
import sqlite3
import sys

RAIZ = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / 'tools'))
from novedades_global import GLOBAL, _registros, abrir_paks  # noqa: E402

DB = RAIZ / 'corpus' / 'content.db'
MASCOTAS = RAIZ / 'server' / 'plantillas' / 'mascotas.json'
DOCS = RAIZ / 'docs'
TABLAS_ITEM = ('item', 'item2', 'item3', 'item4', 'item5', 'item6',
               'item7', 'item8', 'item9')
PREFIJO_ITEM = 1140000000
PREFIJO_PET = 1210000000
BS = '\\'

# Solo para el nombre del fichero de cada categoria (ASCII, enlaces estables).
FICHEROS = {
    '紙娃娃': 'fashion', '一般': 'general', '禮物': 'gift_box', '紅包': 'lucky_bag',
    '配方': 'recipe', '卷軸': 'scroll', '隱藏': 'hidden', '傢俱': 'furniture',
    '衣服': 'armor', '頭飾': 'headgear', '手套': 'gloves', '鞋子': 'shoes',
    '座騎': 'mount', '扭蛋': 'gashapon', '寶石': 'gem', '幸運骰': 'lucky_dice',
    '彈藥': 'ammo', '杖': 'staff', '影刃': 'shadow_blade', '槍': 'gun',
    '弓箭': 'bow', '徽章': 'badge', '機甲': 'mecha', '訂單': 'order',
    '飾品': 'accessory', '盾': 'shield', '刀': 'blade', '錘': 'hammer',
    '卡片': 'card', '寵物': 'pet', '斧': 'axe', '劍': 'sword', '披風': 'cape',
    '農場種子': 'farm_seed', '背包': 'backpack', '經驗卷': 'exp_scroll',
    '打孔道具': 'socket_punch', '怪物蛋': 'monster_egg', '強化道具': 'enhancement',
    '強化飼料': 'pet_feed', '防禦塔': 'defense_tower', '箭矢': 'arrow',
    '計時道具': 'timed_item', '附魔': 'enchant', '字卡': 'letter_card',
    '對話泡泡': 'chat_bubble', '表情卡': 'emote_card', '機甲零件': 'mecha_part',
    '寵物武器': 'pet_weapon', '寵物飾品': 'pet_accessory', '寵物防具': 'pet_armor',
    '寵物寶石': 'pet_gem', '房屋外觀': 'house_exterior', '彈弓': 'slingshot',
    '房屋': 'house', '技能經驗球': 'skill_exp_orb', '小遊戲道具': 'minigame_item',
    '特殊碎片': 'special_fragment', '魔力骰': 'magic_dice', '融合劑': 'fusion_potion',
    'DNA道具': 'dna_item', '抓寵空蛋': 'capture_egg', '地圖碎片': 'map_fragment',
    '挖寶石道具': 'gem_digging', '經驗球': 'exp_orb', '寵物強化': 'pet_enhance',
    '加速肥料': 'fertilizer', '驅蟲劑': 'repellent', '寵物經驗球': 'pet_exp_orb',
    '星盤金幣抽': 'star_wheel_draw', '鐵鍬': 'shovel', '釣竿': 'fishing_rod',
    '儲值道具': 'topup_item', '小鋼珠': 'pachinko_ball', '魯易浮標': 'fishing_float',
    '金錢': 'money', '寵物復活': 'pet_revive', '寵物裝備': 'pet_equipment',
    '星盤賓果': 'star_bingo', '更名道具': 'rename_item', None: 'uncategorized',
}

GM = '用 GM 指令給自己，例如 `/item 3851`（或在 `data/gm.txt` 寫 `item 3851`）。'


def celda(s):
    s = str(s if s is not None else '').replace('|', '\\|').replace('\n', ' ').strip()
    return s or '—'


def cargar_items():
    """{id: (nombre ingles, categoria, 動態資料1)}; la tabla posterior gana."""
    con = sqlite3.connect(DB)
    items = {}
    for t in TABLAS_ITEM:
        try:
            filas = con.execute(f'select id, "基本名稱", "物品類別", "動態資料1" from {t}')
        except sqlite3.Error:
            continue
        for iid, nombre, cat, din in filas:
            if str(iid).isdigit():
                items[int(iid)] = (nombre, cat, din)
    con.close()
    return items


def textos_global(idioma, fichero_re):
    """{id de texto: registro} de SETTING\\<idioma>\\STRING; el pak posterior gana."""
    carpeta = f'SETTING{BS}{idioma}{BS}STRING{BS}'
    salida = {}
    for pak in abrir_paks(GLOBAL):
        for k in pak.entradas:
            if k.startswith(carpeta) and re.fullmatch(fichero_re, k[len(carpeta):]):
                for rid, r in _registros(pak, k):
                    salida[int(rid)] = r
    return salida


def _normal(s):
    return re.sub(r'[^a-z0-9]', '', s.lower())


def _parecido(a, b):
    """0..1. Tolera "3 days"/"3D" o "Lvl"/"Lv"; un item distinto da < 0.5."""
    return difflib.SequenceMatcher(None, _normal(a), _normal(b)).ratio()


class Nombres:
    def __init__(self, items):
        tc = textos_global('BIG5', r'STR_ITEM\d?\.XML')
        en = textos_global('ENG', r'STR_ITEM\d?\.XML')
        self.pets = textos_global('BIG5', r'STR_PET\.XML')
        self.item = {}
        self.desc = {}
        self.dudosos = set()
        self.faltan = 0
        for iid, (ingles, _, _) in items.items():
            r = tc.get(PREFIJO_ITEM + iid)
            nombre = (r.get('文字1') or '') + (r.get('文字2') or '') if r else ''
            if not nombre.strip():
                self.faltan += 1
                self.item[iid] = ingles
                continue
            self.item[iid] = nombre
            self.desc[iid] = r.get('文字3') or ''
            # Solo se compara si el nombre de IGG es ingles: muchos se quedaron
            # en japones o chino y Global los tradujo, sin ser otro item.
            e = (en.get(PREFIJO_ITEM + iid) or {}).get('文字2') or ''
            if (ingles and ingles.isascii() and e.isascii()
                    and _normal(e) and _parecido(e, ingles) < 0.5):
                self.dudosos.add(iid)

    def de_item(self, iid):
        n = self.item.get(iid, '')
        return f'{n} ※' if iid in self.dudosos else n

    def de_pet(self, sprite, defecto):
        r = self.pets.get(PREFIJO_PET + int(sprite))
        return (r or {}).get('文字1') or defecto


def contenido_huevo(desc):
    """Los premios que la descripcion lista, uno por linea tras los dos puntos."""
    if '：' not in desc and ':' not in desc:
        return ''
    lineas = [x.strip() for x in desc.replace('\\n', '\n').split('\n')[1:]]
    lineas = [x for x in lineas if x and not x.startswith('/c')]
    return '、'.join(lineas)


NOTA_DUDOSO = ('※ = 此 ID 在 Global 客戶端的英文名稱與本伺服器（IGG）資料不同，'
               '中文名稱可能屬於另一個物品，請以遊戲內為準。')


def fusion(items, pets, nombres):
    unicas = []
    for iid, (_, cat, din) in sorted(items.items()):
        if cat != '寵物' or not str(din or '').isdigit():
            continue
        p = pets.get(str(din))
        if p and p.get('etapa') == '頂階':
            unicas.append((iid, int(din), p))
    huevos = [i for i, (n, c, _) in sorted(items.items())
              if c == '紅包' and (re.search(r'fusion', n or '', re.I)
                                  or '融合寵' in nombres.item.get(i, ''))]
    pociones = [i for i, (_, c, _) in sorted(items.items()) if c == '融合劑']

    out = [
        '# 融合寵物物品 ID', '', GM, '',
        f'共 {len(unicas)} 個寵物物品，其寵物在 pet.xml 的階段為「頂階」：'
        '融合寵物與怪物寵物，一出生就是最終型態，不會再進化。'
        '由 `tools/listas_de_ids.py` 依物品表與 `server/plantillas/mascotas.json` 產生，'
        '中文名稱取自 Global 客戶端的 BIG5 文字表。', '',
        NOTA_DUDOSO, '',
        '| 物品 ID | 物品名稱 | 寵物圖號 | 寵物名稱 | 寵物類型 |',
        '|---:|---|---:|---|---|',
    ]
    for iid, sprite, p in unicas:
        out.append(f'| {iid} | {celda(nombres.de_item(iid))} | {sprite} | '
                   f'{celda(nombres.de_pet(sprite, p.get("nombre")))} | '
                   f'{celda(p.get("clase"))} |')
    out += ['', '## 融合寵扭蛋 / 福袋', '',
            '類別「紅包」。伺服器目前還無法開啟這些物品（其 動態資料1 沒有對應的 '
            'drop_table，見 `server/bolsas.py`），給自己後打開可能沒有反應。'
            '「可能內容」取自物品說明文字。', '',
            '| 物品 ID | 名稱 | 可能內容 |', '|---:|---|---|']
    out += [f'| {i} | {celda(nombres.de_item(i))} | '
            f'{celda(contenido_huevo(nombres.desc.get(i, "")))} |' for i in huevos]
    out += ['', '## 融合劑', '', '類別「融合劑」。', '',
            '| 物品 ID | 名稱 |', '|---:|---|']
    out += [f'| {i} | {celda(nombres.de_item(i))} |' for i in pociones]
    (DOCS / 'FUSION_PET_IDS.md').write_text('\n'.join(out) + '\n', encoding='utf-8')
    return len(unicas), len(huevos), len(pociones)


def huevos(items, pets, nombres):
    filas = []
    for iid, (_, cat, din) in sorted(items.items()):
        if cat != '寵物' or not str(din or '').isdigit():
            continue
        p = pets.get(str(din))
        if p and p.get('etapa') == '原型':
            filas.append((iid, int(din), p))

    def rama(sprite):
        if not sprite:
            return '—'
        d = pets.get(str(sprite)) or {}
        return nombres.de_pet(sprite, d.get('nombre') or str(sprite))

    out = [
        '# 寵物蛋物品 ID', '', GM, '',
        f'共 {len(filas)} 個寵物蛋（pet.xml 階段「原型」），由 `tools/listas_de_ids.py` '
        '依物品表產生，中文名稱取自 Global 客戶端的 BIG5 文字表。'
        '融合寵物另見 [FUSION_PET_IDS.md](FUSION_PET_IDS.md)。', '',
        NOTA_DUDOSO, '',
        '| 物品 ID | 名稱 | 寵物圖號 | 進化為 |',
        '|---:|---|---:|---|',
    ]
    for iid, sprite, p in filas:
        out.append(f'| {iid} | {celda(nombres.de_item(iid))} | {sprite} | '
                   f'{celda(rama(p.get("rama1")) + " / " + rama(p.get("rama2")))} |')
    (DOCS / 'PET_EGG_IDS.md').write_text('\n'.join(out) + '\n', encoding='utf-8')
    return len(filas)


def todos(items, nombres):
    carpeta = DOCS / 'items'
    carpeta.mkdir(exist_ok=True)
    for viejo in carpeta.glob('*.md'):
        viejo.unlink()
    por_cat = {}
    for iid, (_, cat, _) in sorted(items.items()):
        por_cat.setdefault(cat, []).append(iid)

    indice = [
        '# 物品 ID', '', GM, '',
        f'共 {len(items)} 個物品，由 `tools/listas_de_ids.py` 依物品表產生'
        '（`corpus/content.db` 的 item … item9；較新的更新會取代同 ID 的舊資料）。'
        '中文名稱取自 Global 客戶端的 BIG5 文字表；'
        f'其中 {nombres.faltan} 個 Global 沒有中文名稱，保留原本的英文名稱。'
        '每個類別一個檔案；寵物蛋與融合寵物另有專門清單：'
        '[PET_EGG_IDS.md](PET_EGG_IDS.md)、[FUSION_PET_IDS.md](FUSION_PET_IDS.md)。', '',
        NOTA_DUDOSO, '',
        '| 物品類別 | 數量 | 檔案 |', '|---|---:|---|',
    ]
    for cat, ids in sorted(por_cat.items(), key=lambda kv: -len(kv[1])):
        fichero = FICHEROS.get(cat) or f'cat_{str(cat).encode("utf-8").hex()}'
        fichero += '.md'
        nombre_cat = cat or '未分類'
        texto = [f'# {nombre_cat}', '',
                 f'共 {len(ids)} 個物品。返回 [ITEM_IDS.md](../ITEM_IDS.md)。', '',
                 '| 物品 ID | 名稱 |', '|---:|---|']
        texto += [f'| {i} | {celda(nombres.de_item(i))} |' for i in ids]
        (carpeta / fichero).write_text('\n'.join(texto) + '\n', encoding='utf-8')
        indice.append(f'| {nombre_cat} | {len(ids)} | [items/{fichero}](items/{fichero}) |')
    (DOCS / 'ITEM_IDS.md').write_text('\n'.join(indice) + '\n', encoding='utf-8')
    return len(por_cat)


def main():
    items = cargar_items()
    pets = json.loads(MASCOTAS.read_text(encoding='utf-8'))
    nombres = Nombres(items)
    e = huevos(items, pets, nombres)
    u, h, p = fusion(items, pets, nombres)
    n = todos(items, nombres)
    print(f'PET_EGG_IDS.md: {e} eggs')
    print(f'FUSION_PET_IDS.md: {u} pets, {h} fusion eggs, {p} potions')
    print(f'ITEM_IDS.md: {len(items)} items in {n} categories; '
          f'{nombres.faltan} without Chinese name, {len(nombres.dudosos)} flagged ※')


if __name__ == '__main__':
    main()
