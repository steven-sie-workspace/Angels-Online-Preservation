# Angels Online Server Emulator — AI Development & Architecture Guide
# Guía de Desarrollo y Arquitectura para IA (Bilingual: EN / ES)

> **Document Purpose / Propósito del Documento:**
> This document is designed for AI coding assistants (like Google Antigravity, Claude, ChatGPT) and developers continuing work on this Angels Online (AO / 天使之戀 Online) emulator. It outlines the codebase layout, network protocol, packet layouts, database persistence, and safety rules to prevent bugs or character loss.
>
> Este documento está diseñado para asistentes de IA y desarrolladores que continúen el desarrollo de este emulador de Angels Online. Detalla la estructura del código, el protocolo de red, el formato de los paquetes, la persistencia en base de datos y las reglas críticas para no romper avances de personajes.

---

## 1. Quick Overview & Architecture / Resumen y Arquitectura

```
                        +----------------------+
                        |   Game Client(s)     |
                        +----------+-----------+
                                   | TCP Packets
                                   v
             +---------------------------------------------+
             |            server/app.py                    |
             |  (Asyncio Event Loop, Router, Packet Loop)  |
             +------+--------------+----------------+------+
                    |              |                |
                    v              v                v
          +-------------+  +---------------+  +--------------+
          |  combate.py |  |  presencia.py |  |  cuentas.py  |
          |   Skills,   |  | Multi-client  |  |  SQLite WAL  |
          |  Formulas,  |  |  Map Sync,    |  |  Protection, |
          |   Buffs     |  |  Spawn 0x000E |  |   Backups    |
          +-------------+  +---------------+  +--------------+
                    |              |                |
                    +------+-------+----------------+
                           v
            +------------------------------+
            |      corpus/content.db       |
            | (Items, Spells, Monsters,    |
            |      NPCs, Quests, Maps)     |
            +------------------------------+
```

### Server Services & Ports / Servicios y Puertos
- **Login Server:** Port `16768` (Handles auth, channel selection, character selection/creation).
- **Game / World Server:** Port `16769` (Handles gameplay, combat, chat, inventory, movement).
- **File / Patch Server:** Port `16767` / `16765` (Client asset updates).

---

## 2. Database & Character Safety / Seguridad de Base de Datos y Personajes

### ⚠️ CRITICAL RULE / REGLA CRÍTICA
* **NEVER truncate, blindly overwrite, or replace accounts with empty objects.**
* **NUNCA trunques, sobreescribas a ciegas ni reemplaces cuentas con objetos vacíos.**

### Persistence Architecture:
1. **Source of Truth:** `data/cuentas.db` (SQLite3 with WAL mode `PRAGMA journal_mode = WAL` and `PRAGMA synchronous = FULL`).
   - Resistant to power outages and unexpected crashes.
   - Character data stored in `personajes` table: `(usuario, char_id, ranura, nombre, datos)`.
2. **Automated Hot Backups:** `data/backups/cuentas_auto_YYYYMMDD_HHMMSS.db`.
   - Performed via SQLite native online backup API (`src.backup(dst)`).
   - Triggered on major character changes and every 5 minutes.
3. **External Mirror:** `data/cuentas.json`.
   - Written atomically via temporary file replacement (`tempfile` + `os.replace`). Kept in sync for human inspection.

---

## 3. Network Protocol & Packet Specifications / Protocolo y Paquetes

### Packet Framing / Formato de Tramas
Packets are sent over TCP with Celestia framing:
- `[Length: U16 Little-Endian]` (or `U32` depending on opcode header)
- `[Opcode: U16 Little-Endian]`
- `[Payload / Body]`

### Core Opcodes Table / Tabla de Opcodes Principales

| Opcode | Hex | Direction | Description (EN) | Descripción (ES) |
|---|---|---|---|---|
| `2` | `0x0002` | C $\to$ S | Keepalive / Heartbeat / Ping | Latido / Ping del cliente |
| `5` | `0x0005` | C $\to$ S | Move Request (waypoints) | Petición de movimiento con coordenadas |
| `6` | `0x0006` | C $\to$ S | Attack / Skill Cast Request | Petición de ataque o lanzamiento de hechizo |
| `7` | `0x0007` | S $\to$ C | Despawn Entity (Remove from screen) | Desaparición de entidad del mapa |
| `10` | `0x000A` | S $\to$ C | Combat Action / Lock Target / Anim | Acción de combate / Fijar objetivo |
| `14` | `0x000E` | S $\to$ C | Entity Spawn (Player/NPC/Monster) | Aparición de entidad en pantalla (128 bytes) |
| `17` | `0x0011` | S $\to$ C | Floating Combat Text (Damage/Heal) | Texto flotante de daño / curación / esquiva |
| `19` | `0x0013` | S $\to$ C | Entity Attribute Update (HP/MP/SP) | Actualización de atributo (HP, MP, SP, etc.) |
| `22` | `0x0016` | C $\to$ S | Action / Sit (4) / Switch Weapon (13 / 0x0D) | Acción / Sentarse (4) / Cambiar Arma (13) |
| `26` | `0x001A` | S $\to$ C | Inventory Slot Update | Actualización de ranuras de inventario |
| `29` | `0x001D` | S $\to$ C | Character Stats Update (Atk/Def/Stats) | Actualización de estadísticas y nivel |
| `46` | `0x002E` | C $\to$ S | Use Item (Right Click / Equip) | Usar item (clic derecho / equipar) |

---

## 4. Entity Spawn (0x000E) — 128 Bytes Binary Layout / Estructura Binaria

When players spawn on each other's screen, the server builds a fixed 128-byte packet in `server/presencia.py` (`_spawn(ses)`):

```
Offset  Size  Field (EN)                  Campo (ES)
---------------------------------------------------------------------------------
0x00    4     Entity ID (LE32)            ID de entidad
0x04    4     Type (LE32, 1000=Player)    Tipo de entidad (1000=Jugador)
0x08    4     Sprite ID (LE32)            Sprite base del modelo
0x0C    2     Pixel X (tile_x * 32)       Posición en píxeles X
0x0E    2     Pixel Y (tile_y * 32)       Posición en píxeles Y
0x10    2     Tile X                      Casilla X en el mapa
0x12    2     Tile Y                      Casilla Y en el mapa
0x14    1     Move Speed                  Velocidad de movimiento
0x37    1     Gender (Bit 55)             Género (1 = femenino)
0x3C    1     Class Byte                  ID de clase / profesión (e.g. 16 = Archer)
0x40    4     Head Gear / Fashion         Casco / Sombrero (Fashion > Gear)
0x44    4     Body Armor / Fashion        Pechera / Vestimenta (Fashion > Gear)
0x48    4     Main Hand Weapon            Arma mano derecha (Fashion > Gear)
0x4C    4     Off Hand Weapon / Shield    Arma mano izquierda / Escudo
0x50    4     Legs / Fashion              Pantalones / Grebas
0x54    4     Boots / Fashion             Botas
0x58    4     Back / Wings                Alas / Capa (Ranura 7)
0x5C    4     Mount Sprite (Offset 92)    Montura (0 = a pie / walking on foot!)
0x60    4     Trinket 1                   Accesorio 1 (Ranura 9)
0x64    4     Trinket 2                   Accesorio 2 (Ranura 10)
```

> [!IMPORTANT]
> **Mount Rule / Regla de Monturas:**
> Offset 92 must be `0` when the player is walking on foot! If set to the equipped mount item while unmounted, the client renders the player mounted permanently. Only set offset 92 when `ses.montado == True`.

---

## 5. Multi-Client Multiplayer & Real-Time Sync / Sincronización Multijugador

In `server/presencia.py`:
- `entrar(ses, stage)`: Registers session into `_POR_MAPA[stage]`. Spawns `ses` on all existing players' screens, and spawns all existing players on `ses`'s screen.
- `notificar_equipo(ses)`: Must be called whenever equipment, weapons, or fashion change (swap, move, right-click equip/unequip). Re-broadcasts the 0x000E spawn packet to all nearby players.
- `notificar_transformacion(ses, trans_sprite)`: Broadcasts `0x0013` with `KIND_TRANSFORM (14)` when casting shifts (Shark Shift 35028, Wolf Spirit 35029, Bear Shift 35030) or reverting (sprite 0).

---

## 6. Combat, Spells & Summons / Combate, Hechizos e Invocaciones

In `server/combate.py` & `server/app.py`:
- **Melee Transformations vs Summons:**
  - Transformation spells (Shark Shift, Wolf Spirit, Bear Shift) grant self-buffs and change the player's sprite via `KIND_TRANSFORM`. They are **NOT** summons and must not spawn companion NPCs.
  - `mp_to_hp_pct` only applies to Shark Shift.
- **Totems (e.g. Blackthorn Totem):**
  - Totems are stationary summons (`move_speed = 0`).
  - They plant at the caster's feet and cast area-of-effect pulse spells (e.g., skill 16782 with range 10).
  - They **must never** attempt to walk towards enemies or follow the player.
- **Cooldown & Action Validation:**
  - Skills enforce individual cooldowns measured in milliseconds (`mag.get('cd_ms')`).
  - Attack packets must respect weapon range (`rango`) and target alive status.

---

## 7. Inventory Slots Index / Ranuras de Inventario

```
Slot Range     Usage (EN)                           Uso (ES)
-----------------------------------------------------------------------------
0              Gold (Currency item 1)               Oro
1 .. 10        Equipped Combat Gear (Set I)         Equipo de combate equipado (Set I)
               1: Head, 2: Body, 3: Main Weapon I,
               4: Offhand/Shield I, 5: Legs, 6: Feet,
               7: Wings/Back, 8: Mount, 9: Acc 1, 10: Acc 2
11 .. 12       Alternate Reserve Weapons (Set II)   Armas de reserva (Set II)
               11: Main Weapon II, 12: Offhand/Shield/Arrows II
               Swapped with (3, 4) on Alt+~ or clicking [ I ] [ II ]
20 .. 79       Standard Backpack (60 slots)         Mochila principal
80 .. 159      Extra Bag Expansions                 Bolsas de expansión
167 .. 175     Fashion / Cosmetic Wardrobe          Armario de trajes / Fashion
               167: Hat, 168: Suit, 169: Weapon 1,
               170: Weapon 2, 171: Pants, 172: Boots,
               173: Wings, 175: Fashion Mount
```

---

## 8. Instructions for AI Assistants / Instrucciones para Asistentes de IA

1. **Always Verify Syntax:**
   Run `python -m py_compile server/app.py server/combate.py server/cuentas.py server/presencia.py` before reporting tasks complete.
2. **Never Break Backward Compatibility:**
   Preserve existing docstrings, Chinese text comments, and original Celestia protocol decoders.
3. **Session Logs are Gold:**
   When in doubt about a packet layout, inspect real captured client sessions in `logs/sesiones/*.jsonl` or `logs/proxy/*.jsonl`.
4. **Use Atomic Transactions:**
   Any script editing character data must use `server/cuentas.py` functions or explicit SQLite transactions and call `cuentas._notificar_cambio(inmediato=True)`.
5. **Keep Client and Server in Sync / Cliente y servidor sincronizados:**
   After editing any client `.pak` (or `corpus/content.db`), run `python tools/comprobar_sincronia.py`. It reads the client paks directly and compares every table with `content.db` and `client_tables.json`; exit code 1 means drift. Add `--detalle` to list the ids, `--tabla item9` for one table. The server's own deliberate patches (bound-gear sell price = price/2, seasonal stage decorations) are reported as "expected", not as errors. It only understands the IGG pak layout; the Global client (`SETTING\BASE` + `STRING\STR_*.XML`) is refused with a message.

