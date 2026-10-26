# Regeneracion de HP/MP medida en Venus (Global oficial), 23/10/2026

Grabacion: `logs/proxy/mundo_213252_913057_orden.jsonl` (no va en el repo),
hecha con `grabar_venus.bat` y medida con `medir_regen.bat`
(`tools/medir_regen.py`). Cliente de Global en `C:\UserJoy\Angels Online
Global`, servidor Venus (20.2.137.147:28111). 466 s de sesion.

## El personaje

Nivel 57, 魔法戰士. HP max 2447, MP max 1178 (del 0x0042). 體質 2, 心靈 0.
Habilidades: 生命 49, 混亂 50, 吟咒 53, 斧錘 32, 強身 46, 法袍 53.
Sin buffs de regeneracion a la vista.

## Lo medido

| postura | HP por tick | MP por tick | cada | ticks |
|---|---|---|---|---|
| sentado | +53 (2,17% del max) | +27 (2,29%) | 1,00 s | 74 HP / 86 MP |
| de pie  | +53 (2,17%) | +27 (2,29%) | 2,00 s | 77 HP / 90 MP |

- **La cantidad por tick es la misma sentado y de pie.** Sentado solo hace
  tick el doble de seguido: regenera el doble por segundo.
- El ultimo tick antes del maximo se recorta (+50 HP, +25 MP): se para justo
  en el tope.
- HP y MP llegan en el mismo instante, en dos 0x0013 seguidos.
- De pie los ticks caen en un reloj fijo del servidor (siempre en x,61-x,62 s).
- Sentado: el primer tick llega 1 s despues del 0x000A accion 8. De pie: 2 s
  despues de pararse (tras revivir, 2 s despues del 0x000A accion 0).
- Andando (0x0004 seguidos) no hay ningun tick.
- En combate casi no hay: un solo tick suelto en cada una de dos peleas largas
  (t=29,32 y t=353,51, recibiendo golpes). La regla de "fuera de combate" no
  es simplemente "no te han pegado".
- Los +489 HP (4 veces) no son pociones: es revivir, 0x000A accion 0 justo
  tras la muerte (accion 7, HP 0). 489 = 20% de 2447.

## Lo que NO se sabe todavia

Con un solo personaje no se puede separar que mueve la cantidad: el maximo,
el nivel, 體質/心靈 o alguna habilidad (強身 46). 53 y 27 no son el mismo % del
maximo (2,17% contra 2,29%), asi que puede que no sea un % del maximo.
Hace falta repetir con el mismo personaje tras subir de nivel o de
habilidad, o con otro personaje distinto.

## Comparacion con Celestia (privado, corpus/packets.db)

Nivel 38-40, de pie: HP +11 (0,53% del max), MP +20 a nivel 38 y +22 a 39-40
(2,26% / 2,44%). Sin marcas de tiempo, sin sentarse. El MP se parece a Venus;
el HP no. Celestia es un servidor privado y puede tener su propia formula.

## Nuestro servidor (configuracion.regenera)

Antes de esta medida: sentado 2% cada 1 s, de pie 0,5% + 0,005% por nivel
cada 2 s (0,79% a nivel 57, la tercera parte de lo medido).

Desde el 23/10/2026: 2,2% del maximo por tick en las dos posturas, sin subida
por nivel, suelo de 6 en todo; sentado cada 1 s, de pie cada 2 s y solo
quieto y fuera de combate (app._bucle_regeneracion, que ya lo hacia asi). A
nivel 57 da +54 HP / +26 MP, contra +53 / +27 medidos.
tools/test_dano_y_regen.py::test_regeneracion_como_en_venus lo fija.
