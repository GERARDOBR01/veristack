# Motor 2 — Candidatos de id/aliases, Lotes 3-6 (Sesión V, bloque autónomo)

> **NINGUNO de estos criterios está aprobado.** Los 70 llevan `revisado_por_gerardo=false`
> y quedan así hasta que Gerardo los revise lote por lote en conversación (regla fija de la
> sesión: solo él marca `true`). Este documento es la vista de revisión, no una decisión.
>
> Generado deterministamente desde `capa2_validado_con_candidatos.json` (5 Jul 2026) con el
> generador ya corregido dos veces esta sesión (dígitos puros preservados + marcadores de
> lista "(N)" descartados). Mismo formato de tabla que Lotes 1 y 2, con una columna extra de
> **aliases candidatos** (siguen siendo recortes deterministas del texto, NO paráfrasis en
> lenguaje natural — esa revisión sigue pendiente, como desde Sesión S).
>
> El **Lote 2** (p11-14, 18 criterios) NO está en este archivo: ya fue presentado en la
> conversación y espera las correcciones de Gerardo. 18 (L2) + 18+17+20+15 (L3-L6) = 88 pendientes.

## Lote 3 — p26/27 + p35: Softline campamento + Diversos (18 criterios)

- p26/27 = campamento Softline; p35 = Diversos (única página de esa sección, `condicion_libre` bien poblada desde el piloto).
- Incluye 1 de las 3 correcciones del golden set (p27, marcada ⚠️ en su fila) — la corrección de peso/severidad NO está aplicada al JSON validado (decisión aparte, pendiente).
- Varios criterios de p26 traen `posible_herencia_fewshot=true` (texto legítimo de la página, pero peso/severidad no son juicio independiente del modelo — Sesión Q).

| p | id candidato | aliases candidatos | texto |
|---|---|---|---|
|26|`visibilidad_producto_descuento_alto_corridas`|"visibilidad producto" · "producto descuento"|Da visibilidad al producto con el descuento más alto y corridas completas *[herencia_fewshot]* *(golden set: verificado ✓)*|
|26|`mesa_realizar_bloques_mercancia_doblada`|"mesa realizar" · "realizar bloques"|En la mesa realizar bloques con mercancía doblada, se pueden integrar accesorios en bloques con el mismo descuento.|
|26|`barra_prendas_descuentos_altos_incluyendo`|"barra prendas" · "prendas descuentos"|En la barra prendas con los descuentos más altos, incluyendo prendas altas y prendas bajas, un look por barra. *[aplica_a: barra]*|
|26|`vestir_maniquies_prendas_esten_exhibicion`|"vestir maniquies" · "maniquies prendas"|Vestir los maniquíes con prendas que estén en la exhibición. *[herencia_fewshot]*|
|26|`poner_etiquetas_descuento_prendas_saturar`|"poner etiquetas" · "etiquetas descuento"|Poner etiquetas de descuento a las prendas, no saturar. *[herencia_fewshot]*|
|27|`cuentas_espacio_suficiente_obstruya_paso`|"cuentas espacio" · "espacio suficiente"|Si cuentas con el espacio suficiente sin que obstruya el paso al cliente o realiza campamentos o focales en espacios principales de tienda. Recuerda no forzar el espacio. ⚠️ **golden set: CORREGIDO** peso `MANDATORY→RECOMMENDATION`, severidad `GRAVE→OBSERVACION` — corrección SIN aplicar al JSON validado (decisión aparte)|
|27|`realiza_mercadeo_descuento_mayor_menor`|"realiza mercadeo" · "mercadeo descuento"|Realiza el mercadeo por descuento (mayor a menor) y tipo de producto. *(golden set: verificado ✓)*|
|27|`campamento_realiza_1_2_etapa`|"campamento realiza" · "realiza 1"|Si el campamento se realiza en la 1° ó 2° etapa de la promoción, realiza focales con propuesta de moda. *(golden set: verificado ✓)*|
|27|`realizar_campamento_punt_roma_98`|"realizar campamento" · "campamento punt"|Realizar campamento de Punt Roma con 98´s|
|27|`campamento_maniquies_tringlas_barra_cartulina`|"campamento maniquies" · "maniquies tringlas"|Campamento: Maniquíes + Tringlas o Barra + Cartulina *[aplica_a: barra]* *(golden set: verificado ✓)*|
|35|`agrupa_producto_zoopet_descuento_gondola`|"agrupa producto" · "producto zoopet"|Agrupa el producto zoopet con descuento en una góndola de la sección a pie de pasillo (hasta 50%)|
|35|`agrupa_tipo_producto`|"agrupa tipo" · "tipo producto"|Agrupa por tipo de producto|
|35|`dentro_clasificacion_agrupa_marca_rimax`|"dentro clasificacion" · "clasificacion agrupa"|Dentro de su clasificación, agrupa la marca RIMAX (casas)|
|35|`senaliza_cartulina_30`|"senaliza cartulina" · "cartulina 30"|Señaliza con cartulina (30%)|
|35|`dentro_clasificacion_agrupa_producto_descuento`|"dentro clasificacion" · "clasificacion agrupa"|Dentro de su clasificación agrupa el producto con descuento|
|35|`prioridad_producto_mobility_cloe_40`|"prioridad producto" · "producto mobility"|Prioridad de producto: Mobility y Cloe (40%)|
|35|`dentro_clasificacion_senaliza_exhibicion_cubos`|"dentro clasificacion" · "clasificacion senaliza"|Dentro de su clasificación señaliza las exhibición en cubos de hidrolavadoras (20%)|
|35|`senaliza_resto_seccion_promocion_25`|"senaliza resto" · "resto seccion"|Señaliza el resto de la sección con la promoción del 25%|

## Lote 4 — p31-34 + p38: Hardline masivo/marca (17 criterios)

- Hardline: masivos, bloques de marca, cocina y electro (p34).
- Incluye 1 de las 3 correcciones del golden set (p32, marcada ⚠️ en su fila) — sin aplicar al JSON validado.
- Los hermanos ya confirmados de estas páginas (`no_mezclar_marcas`, `exhibir_1_focal_por_marca`, `colocar_alternando_seccion`, `mercadeo_bloqueo_producto`, `colocar_producto_mayor_descuento`, `mantener_orden_exhibicion` — Sesiones T/U) NO aparecen aquí: ya están revisados.

| p | id candidato | aliases candidatos | texto |
|---|---|---|---|
|31|`masivo_bloque_marca_tipo_producto`|"masivo bloque" · "bloque marca"|Masivo en bloque de marca y tipo de producto|
|31|`caja_vajilla_cerrada_narrative_kostlich`|"caja vajilla" · "vajilla cerrada"|caja de vajilla cerrada Narrative y Kostlich. *[cond: Mesa Fina — herencia_fewshot]*|
|31|`coloca_caja_vajilla_cerrada_general`|"coloca caja" · "caja vajilla"|coloca caja de vajilla cerrada en general. *[cond: Mesa Casual]*|
|32|`coloca_exhibiciones_masivas_producto_participante`|"coloca exhibiciones" · "exhibiciones masivas"|Coloca exhibiciones masivas de producto participante y shots promocionales.|
|32|`exhibe_bloque_tipo_producto_marca`|"exhibe bloque" · "bloque tipo"|Exhibe por bloque y tipo de producto (marca/modelo) ⚠️ **golden set: CORREGIDO** severidad `OBSERVACION→GRAVE` — corrección SIN aplicar al JSON validado (decisión aparte)|
|32|`respetar_alturas_estiba_maxima`|"respetar alturas" · "alturas estiba"|Respetar alturas/estiba máxima|
|32|`asegura_coloque_cartulina_beneficio`|"asegura coloque" · "coloque cartulina"|Asegura se coloque la cartulina con el beneficio***|
|32|`importante_mantener_surtido_caso_vaciarse`|"importante mantener" · "mantener surtido"|Es importante mantener surtido, en caso de vaciarse el modelo, resurtir con otro que tenga suficiente profundidad.|
|32|`masivos_pasillo_deben_contar_espacio`|"masivos pasillo" · "pasillo deben"|Los masivos en pasillo deben contar con espacio que no obstruya la circulación del cliente.|
|32|`separacion_masivos_3_5_metros`|"separacion masivos" · "masivos 3"|Separación entre masivos de 3 a 5 metros|
|33|`exhibe_producto_tendencia_oasis_floral`|"exhibe producto" · "producto tendencia"|Exhibe producto de tendencia Oasis Floral y Oasis Tropical de las secciones de Mesa Fina, Mesa Casual, Blancos, Baño, Organización Hogar y Decoración textil. (Evita mezclar las secciones de diferentes mundos).|
|33|`mochilas_loncheras_lapiceras_concepto`|"mochilas loncheras" · "loncheras lapiceras"|Mochilas, loncheras, lapiceras en concepto.|
|34|`colocar_alternando_largo_seccion_focales`|"colocar alternando" · "alternando largo"|Colocar alternando a lo largo de la sección, los focales en volúmen por marca.|
|34|`focal_bloque_marca_tipo_producto`|"focal bloque" · "bloque marca"|Focal en bloque de marca y tipo de producto.|
|38|`cajas_organizadoras`|"cajas organizadoras"|Cajas organizadoras.|
|38|`protectores_sofa`|"protectores sofa"|Protectores de sofá.|
|38|`puff_caja`|"puff caja"|Puff en caja.|

## Lote 5 — p36/37 + p39-42: Hogar/Book de Impulsos + Multimedia (20 criterios)

- p36/37 = Hogar muebles; p39/40 = Book de Impulsos (Hogar); p41/42 = Multimedia.
- p39/p40 contienen los 2 casos sub-marcados de `referencia_no_resuelta` conocidos desde Sesión O ("Book de impulsos" quedó `false` cuando debía ser `true`) — se señalan, NO se corrigen en este documento (pendiente aparte, ya documentado en CLAUDE.md).

| p | id candidato | aliases candidatos | texto |
|---|---|---|---|
|36|`coloca_material_grafico_forma_alternada`|"coloca material" · "material grafico"|Coloca el material gráfico de forma alternada entre los diferentes sets para evitar la saturación visual de la sección y mantener una exhibición más limpia y atractiva para el cliente.|
|36|`clasificacion_seccion_muebles_modifica_campana`|"clasificacion seccion" · "seccion muebles"|La clasificación de la sección de Muebles no se modifica con esta campaña; los productos deberán permanecer dentro de su clasificación correspondiente.|
|36|`cuentas_espacio_disponible_dentro_seccion`|"cuentas espacio" · "espacio disponible"|Si cuentas con espacio disponible dentro de la sección de Muebles, puedes concentrar la mercancía de liquidación en una exhibición tipo campamento, señalizándo con la cartulina correspondiente. *[cond: Espacio disponible]*|
|36|`caso_contar_espacio_necesario_mercancia`|"caso contar" · "contar espacio"|En caso de no contar con el espacio necesario, la mercancía de liquidación deberá permanecer dentro de su clasificación actual, señalizando cada mueble con la cartulina correspondiente. *[cond: Sin espacio disponible]*|
|37|`colocar_forma_alterna_material_grafico`|"colocar forma" · "forma alterna"|Colocar de forma alterna el material gráfico al costado de la cama|
|39|`coloca_coleccion_mundial_mesas_frente`|"coloca coleccion" · "coleccion mundial"|Coloca la colección del Mundial en las mesas del frente.|
|39|`exhibe_colecciones_indica_book_impulsos`|"exhibe colecciones" · "colecciones indica"|Exhibe las colecciones como se indica en el Book de impulsos tomando en cuenta Mayo y Junio.|
|39|`puedes_sacar_pasillo_masivos_cajas`|"puedes sacar" · "sacar pasillo"|Puedes sacar al pasillo masivos de cajas de vajilla cerrada.|
|40|`cuidar_senalizacion_saturar_seccion_recuerda`|"cuidar senalizacion" · "senalizacion saturar"|Cuidar señalización y no saturar sección, recuerda mantener producto lujo. *(golden set: verificado ✓)*|
|40|`mercadea_forme_book_impulsos_mayo`|"mercadea forme" · "forme book"|Mercadea con forme al Book de Impulsos de Mayo y Junio.|
|40|`impulsa_textiles_entran_98_puedes`|"impulsa textiles" · "textiles entran"|Impulsa todos los textiles que entran en 98´puedes apoyarte de mesa mmm para sacarlos a pasillo.|
|41|`distribuir_material_largo_departamento`|"distribuir material" · "material largo"|Distribuir material a lo largo del departamento.|
|41|`identificar_cartulina_shots_promocionales`|"identificar cartulina" · "cartulina shots"|Identificar con cartulina shots promocionales.|
|41|`permitido_material_pop_marcas_autorizadas`|"permitido material" · "material pop"|NO está permitido material POP de marcas no autorizadas.|
|41|`identificar_producto_descuento_participante`|"identificar producto" · "producto descuento"|Identificar producto con descuento participante.|
|41|`evitar_mezclar_marcas_respetar_clasificacion`|"evitar mezclar" · "mezclar marcas"|Evitar mezclar marcas y respetar clasificación.|
|41|`agrupar_combos_espacios_principales_seccion`|"agrupar combos" · "combos espacios"|Agrupar combos en espacios principales de la sección.|
|42|`colocar_producto_apuesta_comercial`|"colocar producto" · "producto apuesta"|Colocar producto de apuesta comercial.|
|42|`impulsar_producto_especial_acuerdo_matriz`|"impulsar producto" · "producto especial"|Impulsar producto especial de acuerdo a matriz.|
|42|`colocar_cartulinas`|"colocar cartulinas"|Colocar cartulinas.|

## Lote 6 — p43/44: Deportes (15 criterios)

- p44 incluye el bloque descriptivo de layout que salió de `vision_fallback.py` (pendiente de scope desde Sesión Q: son descripciones de planograma, no instrucciones verificables). Se listan tal cual — decidir si entran al knowledge es revisión de Gerardo, no de este documento.
- Los 4 ya confirmados de p43/44 (`acercate_jefe_seccion_pueda_dar` ×2, `exhibicion_disciplinas_mantiene_dentro_separan` ×2 — Sesión U) NO aparecen aquí.

| p | id candidato | aliases candidatos | texto |
|---|---|---|---|
|43|`exhibe_mesa_parte_visible_descuentos`|"exhibe mesa" · "mesa parte"|Exhibe en mesa en la parte más visible los descuentos más agresivos, en medio los descuentos más bajos y en la parte menos visible los avances de temporada.|
|43|`coloca_cartulina_descuento_agresivo_cuentes`|"coloca cartulina" · "cartulina descuento"|Coloca la cartulina con el descuento más agresivo con el que cuentes en la mesa correspondiente.|
|43|`perimetro_coloca_parte_superior_descuentos`|"perimetro coloca" · "coloca parte"|En perímetro coloca en la parte superior los descuentos más agresivos, en medio los descuentos más bajos y en la parte inferior los avances de temporada.|
|43|`mesa_lanzamientos_sigue_manejando_lanzamientos`|"mesa lanzamientos" · "lanzamientos sigue"|La mesa de lanzamientos sigue manejando los lanzamientos que tengas por mes.|
|44|`exhibe_siembra_espacio_visible_disciplina`|"exhibe siembra" · "siembra espacio"|Exhibe y siembra en el espacio más visible de la disciplina el producto con descuentos más agresivos, en medio los descuentos más bajos y en la parte menos visible los avances de temporada, este último puede ir al fondo del departamento o en perímetro. Coloca en el mueble la cartulina con el descuento correspondiente.|
|44|`barra_ballet_exhibe_producto_sola`|"barra ballet" · "ballet exhibe"|En barra de Ballet exhibe el producto de una sola disciplina con el descuento más agresivo. Recuerda separar por género y por partes bajas ó altas. *[aplica_a: barra]* *(golden set: verificado ✓)*|
|44|`unidad_exhibicion_horizontal_superior_izquierda`|"unidad exhibicion" · "exhibicion horizontal"|Unidad de exhibición horizontal (superior izquierda): Etiquetada 'No calificado', con áreas de '10%' y '50 + 20%'.|
|44|`unidad_exhibicion_horizontal_superior_centro`|"unidad exhibicion" · "exhibicion horizontal"|Unidad de exhibición horizontal (superior centro): Etiquetada 'No calificado', con áreas de '10%' y '50 + 20%'.|
|44|`unidad_exhibicion_horizontal_superior_derecha`|"unidad exhibicion" · "exhibicion horizontal"|Unidad de exhibición horizontal (superior derecha): Etiquetada 'No calificado', con áreas de '10%' y '50 + 20%'.|
|44|`unidad_exhibicion_horizontal_media_izquierda`|"unidad exhibicion" · "exhibicion horizontal"|Unidad de exhibición horizontal (media izquierda): Etiquetada 'No calificado', con áreas de '10%' y '50 + 20%'.|
|44|`unidad_exhibicion_vertical_media_derecha`|"unidad exhibicion" · "exhibicion vertical"|Unidad de exhibición vertical (media derecha): Con áreas de '30%', '50 + 20%' y '10%'.|
|44|`unidad_exhibicion_vertical_inferior_izquierda`|"unidad exhibicion" · "exhibicion vertical"|Unidad de exhibición vertical (inferior izquierda): Etiquetada 'No calificado', con áreas de '10%' y '50 + 20%'.|
|44|`unidad_exhibicion_vertical_inferior_centro`|"unidad exhibicion" · "exhibicion vertical"|Unidad de exhibición vertical (inferior centro): Etiquetada 'No calificado', con áreas de '10%' y '50 + 20%'.|
|44|`unidad_exhibicion_vertical_inferior_derecha`|"unidad exhibicion" · "exhibicion vertical"|Unidad de exhibición vertical (inferior derecha): Etiquetada 'No calificado', con áreas de '10%' y '50 + 20%'.|
|44|`exhibicion_ropa_deportiva_estanterias_maniquies`|"exhibicion ropa" · "ropa deportiva"|Exhibición de ropa deportiva en estanterías y maniquíes, con señalización de descuentos visibles.|

---
**Control de conteo**: 70 criterios en este documento (L3=18, L4=17, L5=20, L6=15) + 18 del Lote 2 (en conversación) = 88 pendientes = 156 totales − 68 ya confirmados (Lote 1 + Sesiones T/U). Verificado por el script generador — aborta si no calza.

---
## Apéndice — Investigación del "(4)" faltante en la lista de p13 (RESUELTO: falsa alarma)

La nota del Lote 2 ("no hay id para el (4) de esta lista — revisar si el manual lo omite o el extractor lo perdió") resultó ser **falsa alarma**: el criterio existe en TODA la cadena y ya está confirmado. Evidencia:

1. **Fuente** — `manual_consolidado.json:513`: el texto de p13 (gemini_vision) trae la lista completa (1)-(5), incluyendo "(4) Identificar con cartulina de descuento."
2. **Extracción** — `extraccion_completa.log:28-29`: "[pág 13] → 8 criterio(s), grounding: 8 exact / 0 failed" — nada se perdió.
3. **Crudos** — `criterios_extraidos.json:506`: "(4) Identificar con cartulina de descuento." con pagina_origen=13, grounding=exact.
4. **Estado actual** — `capa2_validado_con_candidatos.json` (~línea 544): ese criterio tiene id `identificar_cartulina_descuento` y `revisado_por_gerardo=true` — es uno de los 2 del grupo de colisión p13/p14 que **Gerardo ya confirmó en Sesión U** con id compartido.

Por eso no apareció en la tabla del Lote 2: las tablas solo listan pendientes, y el (4) ya está revisado. **El mismo caso explica el "(5)" ausente de p14** (`criterios_extraidos.json:621`, pagina_origen=14, exact — el otro miembro del mismo grupo confirmado). Conteo cuadrado: p13 = intro + (1)-(5) + Nota + caso especial = 8 criterios (7 pendientes + 1 confirmado); p14 = intro + (1)-(6) = 7 (6 pendientes + 1 confirmado). No hay nada que corregir en extractor ni validator.
