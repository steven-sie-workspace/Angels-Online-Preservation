# Code review & navigation map (2026-10-19)

Read-only review of the server, written as a reference for future edits.
Context: the server is run on **localhost only** by its owner, so the security
findings below are *known, accepted* gaps, not a to-do list. They matter only if
the server is ever exposed to other players. Line numbers drift; grep the
quoted names.

---

## 1. Where things live

| Area | File(s) | Notes |
|---|---|---|
| Entry point | `server/app.py` → `main()` (~16617) | Run as `py -3 server/app.py -v` (Python 3.10+, stdlib only) |
| Server class | `app.py` `class Servidor` (~6331) | Starts listeners, per-connection loop, `finally` saves on disconnect |
| Packet dispatch | `app.py` `Servidor.manejar` (~7207) | ~9,000 lines of `if opcode == ...` branches, wrapped per-opcode in `try/except` → `log.exception` |
| World rooms | `app.py` `class _SalaDelMundo` (~5179), `_difundir_en_sala` | Broadcast per map |
| Framing/codec | `proto/framing.py`, `proto/codec.py`, `proto/messages.py`, `server/session.py` | 16-bit length, bounded, resyncs on bad header |
| Login flow | `server/login.py`, `server/login_server.py`, `app.py` opcode 0x0002/0x0003/0x0004/0x0006 on `ses.rol=='login'` (~7341) | |
| Accounts / persistence | `server/cuentas.py` | SQLite `data/cuentas.db` (WAL, synchronous=FULL), JSON mirror `data/cuentas.json`, rotating backups |
| Config flags | `cuentas.py` `CONFIGURACION_POR_DEFECTO`, `flag()`; `server/configuracion.py` | `validar_password`, `registrar_primer_hash` |
| GM commands | `app.py` `_probar_gm` (~1249), `server/gm.py`, `data/gm.txt` (console) | See `GM_ITEM_COMMAND_FOR_AI.md` |
| Presence / spawn 0x000E | `server/presencia.py` (`entrar`, `notificar_equipo`, `_spawn`) | 128-byte spawn layout in `AI_DEVELOPMENT_GUIDE.md` §4 |
| Combat | `server/combate.py`, `server/skills.py`, `app.py` 0x0006 handler (~8949-10800) | Global `combate.ATACANTE[0]` = current attacker |
| Monster AI | `app.py` `_ia_monstruos` (~7640), 0.1 s tick | |
| Inventory / bags | `server/inventario.py`, `server/bolsas.py`; `app.py` 0x0012 (move), 0x002F containers | Slot ranges: 0 gold, 1-19 equip, 20-120 bag, 166 stall card, 167-556 fashion/card/furniture |
| Shop | `app.py` 0x0027 buy (~11377), 0x0028 sell, `_precio_compra` (~476) | Prices from `item.xml` |
| Stalls | `app.py` 0x0025/0x0026 | |
| Bank | `app.py` ~12013-12244 | |
| Upgrades | `server/mejoras.py` (`personaje.mejoras` keyed by slot) | |
| Pets | `server/mascotas.py` | |
| Houses | `server/casas.py`, `server/house_services.py`; furniture save 0x013B (~12960) | Global dict keyed by char_id |
| Quests / dialogs | `server/misiones.py`, `server/dialogos.py`, `server/dialogos_mapa.py`; dialog option handling `app.py` ~15106 | |
| Card book | `server/cartas.py` | Plan on deep copy → save → apply (good pattern) |
| World events | `server/eventos.py`, `server/eventos_mundo.py` | |
| Map content | `server/plantillas/*.json` (one per map), `corpus/content.db` | From captures |
| Movement | `app.py` 0x0004 handler (~16186) | |
| Tests | `tools/test_*.py` (67 files, pytest-style asserts, no runner/CI) | None cover `manejar` |

## 2. Patterns worth reusing when editing

- **Plan → save → apply** (`cartas.py`) and **snapshot + rollback** (furniture 0x013B):
  use these for any multi-step state change. Most other handlers mutate in place
  with no rollback, so an exception halfway leaves state half-applied.
- `manejar` is fully synchronous: no `await` inside, so two handlers can't
  interleave. Keep it that way; adding an `await` mid-transaction introduces races.
- Never blindly overwrite accounts (`AI_DEVELOPMENT_GUIDE.md` §2).
- Mount offset 92 must be 0 when not mounted (`ses.montado`).

## 3. Known gaps (accepted for localhost use)

### Auth / session
1. `ses.usuario` is set **before** `cuentas.validar()` (~7343). A rejected login
   keeps the connection, and 0x0003/0x0004/0x0006 don't check auth.
2. World login is matched by **client IP** (`self.pendientes[addr[0]]`, ~7467),
   never removed, with no one-session-per-character guard. Two world connections
   from the same IP load the same character twice, and both save on disconnect.
3. GM chat commands (`_probar_gm`) have **no permission check**. This is intentional for dev.
4. Character create: slot = `u32 & 0xFF`, and `INSERT OR REPLACE` on `(usuario, ranura)`
   overwrites an occupied slot.
5. `char_id = max(this account's ids)+1`, so every account's first character is 1001. `entity_id = 1000 + char_id%1000`
   collides across accounts. Houses and instances are keyed by char_id. **This will
   bite if multiple accounts are ever online together, even locally.**
6. `cuentas._actualizar_personaje` falls back to the user's *first* row when
   the char_id isn't found, so a save can land on the wrong character.
7. `registrar_primer_hash=1`: the first password seen claims an empty-password account.
8. `Grabador` logs the full c2s stream, including the replayable 32-byte password hash, to `logs/`.

### Economy (client-trusting)
- Shop buy 0x0027 accepts **any item_id** with no shop/NPC context. Items with no price cost 1 gold.
  202 items sell back for more than they buy for.
- Skill-branch swap (0x002F container 10) accepts any branch.
- Split (0x002F container 11) skips the `es_ranura_valida`/`puede_equipar` destination checks.
- Bank deposit/withdraw moves the item but leaves `mejoras`/`instancias`/`mascotas`
  **keyed to the slot**: upgrades are lost or transferred, and binding resets. *Also a bug for honest play.*
- Stall: the seller can swap the item in the listed slot (same id, lower upgrade) after listing.
- Bank withdraw doesn't bound the destination slot (≥65536 → `struct.error` after `banco.pop`).
- Legacy destroy 0x004C doesn't clear quantities/upgrades/instances.
- Exchange 0x0160: materials are consumed before `_meter`. If the bag is full, the reward is lost (*real bug*).
- Gold clamps at 2e9 can silently destroy gold (bank withdraw, stall seller credit). `banco_oro` is unbounded.

### Combat / world
- Movement 0x0004 is client-authoritative: no walkability, speed or travel-time check.
- Dialog: `if _el is None and (_v in _ops or _v > 100): _el = _v` accepts option ids that were never offered.
- 0x0006 doesn't check that the caster knows the skill (`tipo` is not checked against `p.habilidades`).
- `aceptar_mision` lets a completed non-repeatable quest be re-accepted (`misiones.py` ~660).

### Real bugs (affect localhost play too)

**Fixed 2026-10-19:** ghost AI task and `cerrada` (now set on disconnect; `Session.enviar` drops output once closed), `ATACANTE` (now a `ContextVar`, so `call_later` hits keep their attacker), double `import app` (aliased in `app.py`), cooldown before MP/SP check, bank upgrades/pet data (travel inside the bank entry as `(item, qty, extras)`), exchange with a full bag (rolls back), and `char_id` allocation (now server-wide via `cuentas.proximo_char_id`). Still open: `entity_id = 1000 + char_id % 1000` repeats after 1,000 characters; other `call_later` timers still fire after disconnect (their sends are dropped).
- **Ghost sessions:** `_ia_monstruos` loops `while ses.personaje`, which is never cleared on
  disconnect. The task is never cancelled either (only `patrulla_task`/`regen_task` are),
  so CPU and memory grow with every reconnect.
- `cerrada` is read (~5217, ~5322) but **never set**, so closed sessions keep getting broadcasts.
- `combate.ATACANTE[0]` is global. Delayed `call_later` hits (AoE sub-hits, pet hits,
  DoTs) credit damage, EXP and loot to whichever session ran last.
- `import app` from `presencia.py:552`, `equipos.py:132`, `gm.py:48` while the server runs
  as `__main__` **loads app.py a second time** with separate globals (entity counters,
  `_SALAS_DEL_MUNDO`, caches). Use `sys.modules['__main__']` or pass references instead.
- Cooldown is recorded before the MP check (~9095), so a cast refused for low MP still starts the cooldown.
- ~75 `call_later` timers capture `ses` and are not cancelled on disconnect.
- Every character save is synchronous on the event loop. It also re-reads the whole DB and rewrites the
  JSON mirror with fsync (`_notificar_cambio` → `_exportar_json_disco`), plus a backup every 25 changes.
  This causes hitches as the DB grows.

### Code health
- `app.py` is 16.6k lines, with 518 function-local imports and 135 `except Exception:` (64 followed by `pass`).
- `server/app.py.bak.20261001` and `server/combate.py.bak.20261001` are tracked and not ignored.
- `data/cuentas*.json` backups are tracked despite `.gitignore` (they hold only the test account `karma`/`123456`).
- Empty `AO.db`, `content.db` at the repo root.
- No requirements file. Python ≥3.10 is required (`int | None` in `skills.py`).
