# Street layout planner — 23 October 2026

Merged into `master` on 23 October (`ba417a2`). This continues the Forest experiment;
it does not change country packs or the building generator. Stock meshes remain
references to the player's installed game.

## Placement

`VEG.streetProps` now plans furniture, inferred lamps and avenue trees together.
The original uncommitted footprint work is retained and corrected: the footprint
passes the `curb` flag through, and candidates test each other's full capsules.

- Furniture uses the road's untrimmed distance lattice. Hydrants, mailboxes and
  bike stands are restricted to 120/180/48 m windows; they are not repeated at
  every dense sample. Footpaths omit curb fixtures and these rare road fixtures.
- Lamps use a separate 30 m cadence, respecting `lit=no`; wide roads can have
  both rows. Poles use measured stock bounds, face the road, and occupy the
  sidewalk's outer edge or the ground beside roads without sidewalks.
- Small avenue trees stand every 24 m (48–72 m at low density), offset by 12 m
  from the road's origin. They also follow explicitly mapped sidewalk footways.
  Crowns stand outside the pedestrian strip. Species follow the existing biome
  lookup at the actual position; no inferred avenue trees above the tree line,
  in tundra/ice, or with `maxTrees=0`.
- Buildings, road surfaces, footpath paving, crossings, mapped water and parking
  areas exclude candidates. Surveyed tree/lamp/stop nodes take precedence.
  Bridges and tunnels receive no inferred roadside furniture or lamps.
- Large furniture moves onto the outer verge when its width would leave less
  than 1.2 m on the sidewalk. Verge objects use terrain height. Models are kept
  at least 0.4 m apart using capsule geometry, including long bike racks.
- A 12 m planning halo includes competitors across tile edges. Lower priority
  number wins (lamp, tree, furniture), followed by stable hash/name. Each item
  must beat all overlapping candidates, even rejected ones: this deliberate
  conservative thinning avoids order-dependent greedy chains at tile seams.
  Only the final anchor's half-open tile owns the item.
- Accepted positions reserve space against subsequent vegetation scatter, so
  ordinary yard trees do not fill the same planting strip.

`propSpacing=0` disables inferred furniture and avenue trees; road lighting and
surveyed OSM points remain. Existing quality presets still control density and
near-tile range. Extra avenue trees are additional to the existing scatter cap.

## Furniture by place (23 October, master)

One street mix on every footway put planters and bike racks in yards and village
streets, and nothing stood by the buildings. The planner now picks a set by place:

| Place | How it is found | Furniture |
|---|---|---|
| Park path | path midpoint in `park` (most particular area wins) | bench + round bin, every 2× step |
| Yard path | town (a building within ~100 m), not park/square/paved | bench + small bin, bin, every 3× step |
| Square | `place=square` / pedestrian area | lattice of planters, benches, bollards, racks, 3.5 m in from the edge |
| Paved frontage, `footway=sidewalk` | `paved` area or the tag | the street mix |
| Path out of town | no building near, no area | none |
| Block of flats | `apartments`/`residential`/`dormitory`, or `yes` ≥ 12 m | entrance benches + bins 1 m off yard walls (backs to the wall); a row of three 1100 l containers 3.5–9 m into the yard |
| Shop | `retail`/`commercial`/`supermarket`/`kiosk`/`mall` or `shop=*` | planters, bins, racks on walls facing a street; a skip behind |
| House | `house`/`detached`/… or a 30–300 m² `yes` among houses | wheelie bin or bench at the road's verge, past a sidewalk |
| Village sidewalk | houses, no flats, under 1/6 of the ground built | sparse bench or bin |

A yard wall is one with no street (service ways and living streets do not count)
within 14 m of it. Groups (a bench and its bin, a row of containers) do not thin
each other; containers outrank other furniture. Car parks keep furniture out but
not lamps and trees. Density follows the street step: Potato fewer, OASIS more.
`earthng/props_map.py` draws a tile's props from a real pack and prints counts and
lat/lon samples for in-game views.

## Runtime

Furniture, inferred/surveyed lamps and surveyed/avenue trees use collidable
Forest kinds (`shape#solid`) and the existing bounded 600-item FIFO commits.
Other forest/yard vegetation retains its previous collision policy. The fallback
is TSStatic with Collision Mesh. Stock model collision detail is engine-provided.

Forest lamp anchors enter the night light pool only after a successful commit;
retirement removes them, and stale queued generations cannot leave phantom lights.
Collision activation still follows the normal world collision rebuild; this does
not promise immediate solidity on the first visual frame.

## Verification

285 automated tests run, 282 pass and 3 skip for unavailable local cache fixtures.
New regression cases cover 3 m rack spacing across a tile boundary, split versus
whole-tile planning, reversed source order, surveyed-point priority, water,
quality/lit/bridge/far exclusions, curb roles and lamp commit/retirement lifecycle.
The prior independent rectangle-outline tests cover acute forks and bends.

Machine-local evidence and test builds: `out/city-detail/`. The baseline build is
committed `8ac0415`, using the same base planet art as the updated build. Offline
results in `offline.json` use nine central Kyiv tiles and the same LuaJIT runtime.
In-game results must be read separately from offline generator timings.

Offline, near tiles only (single pass, 9 tiles):

| Version / spacing | Mean generation, ms/tile | Solid street items across 9 tiles |
|---|---:|---:|
| Previous / 0 m | 442.2 | 0 |
| Previous / 6 m | 429.3 | 7251 |
| Previous / 3 m | 434.4 | 14008 |
| Updated / 0 m | 444.1 | 382 |
| Updated / 6 m | 460.4 | 4232 |
| Updated / 3 m | 458.3 | 7729 |

Updated totals include collidable lamps and mapped/avenue trees. The 0 m case
keeps lighting and surveyed trees, so its count is intentionally nonzero. Counts
fall as obsolete dense fixtures, overlaps and blocked positions are removed;
this is improved placement, not a claim of more objects per tile.

BeamNG 0.40.3, same Ukraine pack, Kyiv centre route, requested Normal / 1280×720,
60 seconds driving at target 20 m/s, fresh isolated profiles, one game at a time:

| Version / spacing | Travel, m | Mean frame, ms | p99, ms | Frames >100 ms | Largest Forest commit, ms |
|---|---:|---:|---:|---:|---:|
| Previous / 6 m | 928.0 | 18.48 | 47.0 | 2 | 3.88 |
| Updated / 6 m | 928.9 | 18.64 | 48.5 | 2 | 3.68 |
| Updated / 3 m | 928.2 | 19.29 | 51.5 | 3 | 9.28* |

Both drives pass the functional checks and fail the strict no-frame-over-100-ms
performance gate. Worst frames: 205 ms previous, 515 ms updated, at drive startup.
Only one run each; cache warm-up and window resize are confounders, not evidence
of a proven FPS gain. Logs report the same changing render sizes for both runs
(1264×681, 1180×720, 392×719), despite the requested resolution. Collision rebuilds
also increased (8 → 10; cumulative 171 → 269 ms), so reduced prop count does not
mean all runtime costs decrease. Gallery camera moves change streamed counts;
end-of-report totals are not a steady-state population comparison.

The 3 m stress run also switched Potato → OASIS after driving; both checks kept
the road and vehicle height stable. Its largest Forest commit (*) includes that
quality transition. It likewise passes functionally and fails the frame gate.
After the drive, `earthng/probe/street_layout.lua` found 21 solid trees, 64 solid
lamps and 561 furniture items in a 500 m box around the vehicle; 137 light anchors
were registered globally. Following an explicit collision rebuild, four horizontal
rays around each of 10 sampled lamps and 10 sampled trees all hit within 4 m.
This confirms nearby collision surfaces, not mesh identity or vehicle-impact
behaviour for every model. Evidence: `collision-check.json`. No pending removals
remained; 124 additions were still queued when the gallery run ended, so this run
does not establish that every far tile and queue had fully drained.

Reproduction (use an existing base planet with this branch's `mod/` files):

```powershell
C:\js\EarthNG\.venv\Scripts\python.exe earthng/test_world.py --out out/city-detail/repeat --planet out/city-detail/city.zip --mod C:\js\EarthNG\out\native-packs\earthng_ukraine.zip --route C:\js\EarthNG\out\routes\kyiv-center.json --speed 20 --drive-seconds 60 --prop-spacing 6 --gallery --timeout 420
```

Reviewed screenshots: `drive-city6/e2r-4-landed.png`, `e2r-g1-street.png`,
`e2r-g3-right.png`: visible avenue trees, lamps and furniture beside the street.
The driving route remains clear; these views do not certify every generated tile.

Limits: this is an inferred layout, not a survey of actual street furniture.
Packs do not contain building entrance/driveway geometry or most amenity nodes.
Tree clearance is a conservative planting envelope, not a mesh collision solver.
Building facade realism and new asset production are separate work.

## Двір багатоповерхівки — 25 жовтня 2026

Еталон — фото двору Прилужної 4/15 (Київ, 50.4603, 30.3447) з вікна західного крила
на схід. На фото: авто вздовж кожного проїзду, майданчик (пісок, гойдалки, гірка,
пісочниця під грибком, карусель, альтанки), живопліт, палісадники з низькою фарбованою
огорожею під вікнами, ґанки з козирками над під'їздами, контейнери за синім парканом,
ліхтар над проїздом, ялинка біля дверей, жовті бетонні півсфери на розі проїзду. До цієї
зміни генератор ставив там лише газон, кільцевий проїзд і одне дерево.

`YARD.build` (`generator.lua`) іде після `VEG.streetProps` і не займає їхніх місць.
Усе, що він поставив, резервується від розсіювання дерев.

| Що | Де | Звідки |
|---|---|---|
| Палісадник: кущі в смузі 0,6–4,5 м від стіни, низька огорожа з прутів (0,75 м) | двірна стіна блоку від 12 м: у 14 м немає вулиці (проїзд не рахується) | лише правило; глибина до проїзду, доріжки чи майданчика мінус 0,6 м |
| Ґанок: сходинка, двері, козирок 2,9 м | кожні двері на двірній стіні | `entrance=staircase/main/home` з пака, інакше кожні 25 м, як лавки |
| Лавка й урна | поруч із дверима, 2,6 м уздовж стіни | `VEG.entrance` (було просто перед дверима) |
| Авто паралельно проїзду, ~74 % місць, крок 5,7 м | `service` і `living_street` у 40 м від блоку | процедурне авто ~100 трикутників, декор без колізії |
| Ліхтар `lamp1` над проїздом | той самий проїзд, кожні ~34 м, з одного боку | лічильник ґратки авто |
| Півсфери 2+2 | гирло проїзду на перехресті, ~45 % | процедурні, жовті або бетон |
| Майданчик: пісок, до 9 елементів (по одному на 28 м²), лавки по краю | `leisure=playground` (полігон або точка → коло 9 м) | новий клас пака `playground` |
| Живопліт `cypress_hedge_3m` ×0,7 | край майданчика, якщо проїзна частина ближче 8 м | правило |
| Екран навколо контейнерів 1,5 м | ряд із трьох контейнерів `VEG.container` | правило |
| Ялинка (`douglasfir_small_c` ×0,55) | біля 22 % дверей палісадника | правило |

Процедурні речі малюються в атласі `yard` (16 кольорів, `fast_art.YARD_COLOURS`) і в трьох
матеріалах огорожі `railing_*` (біла мапа з прутами в непрозорості, фарба — sRGB-множник).
Авто на ділянках парковок теж нові: та сама модель замість трьох коробок; справжні авто
`gameplay_parking` і далі стоять лише на ділянках `amenity=parking`.

Пак: нові класи `playground` (площа й точка), `hedge` (лінія), `entrance` (точка) потрапляють
лише в нові збірки. Старий пак їх не має: авто, палісадники, ґанки за правилом, ліхтарі
й півсфери працюють і на ньому, майданчика й живоплоту з OSM нема.
Перевірка поза грою: `test_generator.py` (`test_a_yard_driveway_*`, `test_a_playground_*`,
`test_front_gardens_*`), `test_styles.py` (`test_yard_*`).

## Сховані стіни і рамки вікон за принципами MaGE — 9 листопада 2026

[MaGE](https://github.com/5DROR5/MaGE) — інструмент World Editor, який будує тротуари,
стіни й будівлі зі стоковими вікнами й обрамленням. Код не запозичено: README називає
AGPL-3.0, а кореневий LICENSE — GPL-3.0. Взято два принципи.

**Overlap — сховане не малювати.** MaGE відрізає трикутники, що лежать усередині іншого
об'єкта. У EarthNG сусідні будинки щільної забудови ділять стіну, і генератор малював
обидві разом із вікнами, кондиціонерами, балконами, ринвами й вікном щипця. Ці деталі
стояли всередині сусіда. Тепер `BLD.cover` індексує зовнішні стіни будівель тайла.
Не індексуються контури `e2r_outline`, відкриті дахи `building=roof` і підняті частини
(`min_height`). `BLD.hidden` дає для стіни відрізки, що лежать на стіні сусіда (паралельні,
до 20 см від лінії) з сусідом зовні стіни. Над кожним відрізком стіна схована до верху
найвищого сусіда, і стіна малюється шматками (`BLD.pieces`). Відкриті шматки проходять
звичайний шлях. Схований шматок над нижчим сусідом стає глухим брандмауером:
у блоків — власний торець `_end`, за тинькованим фасадом — гола цегла `wall_brk_red_end`,
за склом і вітринами — бетон `plinth`. Повністю схований шматок не малюється.
Двері будинку переходять на найдовшу відкриту стіну. Стіна з вітриною (`experimentalShopfront`)
лишається цілою, бо її прольоти прив'язані до всієї стіни. Далекі тайли (коробки) цього не роблять.

**Обрамлення вікон, з LOD.** MaGE дає вікну раму з підвіконням і надвіконням. У EarthNG
вікна будинків (`hw_*`) — окремі квади, тож рамка стає точно під вікном (`BLD.frame`).
Від Balanced (`dress.mass`, detail ≥ 40) під кожним вікном є підвіконня: верх і фасад,
4 трикутники; оцинковане (`pipe`) під ПВХ, дошка (`gable`) під дерев'яним. Від High
(detail ≥ 65) дерев'яне вікно має ще лиштву сільської хати: пласкі бічні дошки й
надвіконня з верхом, ще 8 трикутників. Блоки з фото-фасадами мають намальовані вікна
і рамок не отримують.

Перевірка поза грою (`test_generator.py`): `test_adjoining_buildings_hide_their_shared_wall`
(рівний, нижчий, вужчий, піднятий сусід і частина всередині контуру),
`test_terraced_houses_have_no_windows_in_the_party_wall`,
`test_house_windows_have_sills_and_wooden_ones_a_casing`.

Офлайн-замір `mesh_pairs.py`, пак України, 9 ближніх тайлів, опції за замовчуванням:

| Місце | Трикутники сцени до → після | Пари об'єкт × матеріал | Вікон у спільних стінах прибрано |
|---|---:|---:|---:|
| Хрещатик, 50.4501, 30.5234 | 259 362 → 276 213 (+6,5%) | 622 → 633 | ~1 270 з ~7 900 |
| Поділ, 50.4630, 30.5071 | 243 164 → 273 811 (+12,6%) | 605 → 623 | ~1 270 з ~10 700 |

Сховані стіни зекономили 6–9 тис. трикутників на 9 тайлів (плінтуси, вікна, парапети;
сама стіна — один квад). Підвіконня додали 26–37 тис. Час генерації тайла в межах шуму
(Поділ 787 → 708 мс, Хрещатик без змін). Кадр гри цим не виміряно.

`bench_native.py` тепер вантажить `manual_editor.lua`: без нього `native.land` у 0.8.1 падав,
і `mesh_pairs.py` не працював.

Гра, A/B: BeamNG 0.40, окремі профілі, пак України, якість 80 (High), 1600×900, посадка
50.4628, 30.5172. Базова планета — та сама збірка з `generator.lua` з `master`. Кадр
`close` (камера 50.46262, 30.51690, 5 м): у новій версії над нижчим сусідом голий
цегляний брандмауер замість спільної стіни з вікном, козирок, що стирчав зі спільної
стіни під балконом, зник, у вікон будинку є підвіконня й лиштва. Обидва запуски
функціонально пройшли поїздку на 20 м (у базового є ще `not_moved`) і обидва не пройшли
поріг кадру понад 100 мс: стартові статтери, worst 1143 і 886 мс. Середній кадр 31,7 і 27,7 мс
за одного запуску на кожну версію не доводить виграшу. Кадр `street` потрапив у дах,
вид уздовж вулиці не перевірено. Артефакти — локальні `out/mage-detail/` (не в Git).

## Бордюри, тротуари й парапети мостів за принципами MaGE — 9 листопада 2026

Продовження попереднього розділу. Код MaGE не запозичено, лише принципи з його `Settings.lua`
і `Bridge.lua`: бордюр видно над проїжджою частиною (~15 см), стіни мосту низькі, зі стійками.

**Подвійні тротуари.** У центрі Києва тротуари замаплені окремими лініями
`footway=sidewalk`, а вулиця має `sidewalk:both=separate` або не має тега. Генератор
малював і свою 2-метрову смугу, і лінію з пака: дві паралельні смуги через газон (кадр w5).
На тайлі Хрещатика 42% площі згенерованого тротуару лежало поверх footway/paved з пака.
Тепер `separate` не дає вулиці власного тротуару. Сторона вулиці без тега з паралельною
лінією `footway=sidewalk` поруч (`ROADS.mappedWalk`: до 25°, від краю проїжджої частини
до 9 м за ним, у двох із трьох точок сегмента) теж його не отримує. Мости й тунелі
лишають свій тротуар, бо лінія на мосту не малюється на висоті настилу.

**Вимощення до замапленого тротуару.** Лінія `footway` лягає на землю, і укіс узбіччя від
піднятого бордюру накривав її в межах 3 м від дороги (кадр w2: тротуару не видно взагалі).
Тому така сторона вимощена від бордюру до дальнього краю лінії (`walkAt`, `walk.kerb`,
не більше 6 м); без лінії поруч лишається сам бордюрний камінь 0,25 м. Один сегмент,
який пошук пропустив між двома знайденими, бере їхню ширину (`ROADS.fillKerbs`). Пропси
лінії, що опинились під вимощенням, не ставляться (смуга `walks`). Меблі вулиці стоять
на вимощенні.

**Піднятий тротуар з гранню бордюру.** Раніше тротуар лежав урівень з асфальтом, а бордюр
був білою смугою. `ROADS.curbSlab` піднімає шматок тротуару на 12 см (`ROADS.CURB`) і
опускає грань бордюру на 3 см під дорогу. Грань ставиться на краю проїжджої частини,
на внутрішньому боці кільця перехрестя (бордюр огинає ріг) і на кожному зрізі, де
тротуар обрізано асфальтом (бічна вулиця, заїзд, зірка перехрестя). Шви між шматками,
які дає відсікання, грані не отримують: по той бік бруківка, а не асфальт
(`lists.onAsphalt`). Шматки менші за 0,05 м² лишаються пласкими, щоб не було зуба 12 см
у смузі. Узбіччя починається від піднятого краю. Пропси вулиці підняті на 12 см.

**Парапет мосту.** Суцільна стіна 0,9 м разом із фасадом настилу читалася з вулиці як
бетонна смуга заввишки 2 м. Тепер `ROADS.parapet` (звичайні й об'єднані настили) малює
фасад від низу настилу до бортової стінки 0,45 м, її внутрішню грань і верх. Над нею
поручня до тієї ж висоти 0,9 м: сітчаста панель `fence_mesh` (alpha test, двобічна,
тверда для машини, як стіна раніше), поручень і стійки через 2,5 м (`pipe`). Ліхтар на
мосту стоїть на бортовій стінці.

Перевірка поза грою (`test_generator.py`): `test_a_mapped_sidewalk_way_replaces_the_streets_own_sidewalk`,
`test_per_side_sidewalk_tags_win`, `test_sidewalks_stay_off_the_other_street_at_a_crossing`
(висота, грані на обох вулицях), `test_curb_runs_along_the_top_row_of_the_trim_sheet`,
`test_a_bridge_deck_has_edges_a_soffit_and_parapets` (бортова стінка, сітка, поручень, стійки),
`test_street_props_skip_a_separate_sidewalk_and_stay_off_the_street_band`. Увесь набір: 823 OK.

Офлайн-замір (`walks.py` у scratchpad, один тайл Хрещатика 50.4473, 30.5199):

| | До | Після |
|---|---:|---:|
| Площа згенерованого тротуару | 6 204 м² | 843 м² (до вимощення до ліній) |
| Перекриття з footway/paved з пака | 2 595 м² (42%) | 244 м² |
| Граней бордюру всередині проїжджої частини | — | 4 трикутники з 806 |

`mesh_pairs.py`, 9 тайлів, шар доріг (master → гілка): Хрещатик 160 110 → 160 131,
Поштова площа 84 393 → 87 514. Перша версія граней (на кожному шві) давала +7,9 тис.
на Хрещатику; перевірка асфальту за швом зняла їх.

Гра: BeamNG 0.40, пак України, якість 80 (High), 1600×900. Тротуари: посадка 50.4473, 30.5199,
кадри w1–w5 (камера на тротуарі 1,6 м). Було: w5 — плитка, газон і асфальтова лінія поруч;
w2 — пласкі смуги з білим бордюром. Стало: широкий тротуар від бордюру з видимою гранню
(w2, w5). На w3 (житлова вулиця) були розриви вимощення; про них наступний підрозділ. Міст: посадка
50.4598, 30.5255, кадри `side` (50.459800, 30.526200, 3 м) і `near` (50.459950, 30.526050, 2,5 м).
Видно бетонний фасад, бортову стінку, сітку зі стійками, а не суцільну смугу. Крило устою
(`ROADS.wing`) не змінювалось. Всі запуски не пройшли поріг кадру понад 100 мс
(стартові статтери), FPS цим не порівнювали.

**Вимощення через перехрестя (9.11, перед 0.8.2).** Кадр w3 (50.446305, 30.518624; однобічна
`residential` шириною 4 м, тротуари замаплені з обох боків на 5–9 м від осі, з одного боку
з'їзди у двори) перезняли після `ROADS.fillKerbs`: розриви лишились. Офлайн-план тайла
показав, що це не сегменти, а перехрестя. Кільце тротуару навколо перехрестя робилося лише
тоді, коли до нього підходила вулиця з власним 2-метровим тротуаром, а вимощення до замапленої
лінії (`walk.kerb`) кільця не давало. Тому бруківка обривалась на кожному з'їзді у двір.
Тепер кінець смуги несе ширину вимощення з кожного боку (`ROADS.endWalks`), а
`ROADS.ringInsets` дає кутам кільця ширину того боку, що в них закінчується. Кут відступає
від вузла, як і раніше, але настільки, щоб дістати краю вимощення своєї дороги (не більше
1/`ROADS.RING_REACH` = 1,33 ширини). Відступ поперек дороги перекручував чотирикутники на
вузькій вулиці, бо промені сусідніх кутів перетиналися. Кут з'їзду без тротуару бере ширину
сусіда через ріг і міряє її від краю цього сусіда: бруківка заповнює ріг до лінії тротуару
вулиці, а не тягнеться вздовж з'їзду і не обривається клином до газону. Кут без гирла бере
вужчого з сусідів. Якщо до перехрестя підходить вулиця з власним тротуаром, кільце, як і
раніше, має щонайменше 2 м усюди. Узбіччя кільця на гирлі дороги не малюється: з довшими відступами воно лягало поперек вимощення самої дороги, і на похилому рельєфі в кадрі w3 були смуги газону через тротуар. Другий пропуск того самого кадру — лівий бік однобічної вулиці. Для вулиці без тегів
його вгадували без тротуару, і між бордюром і замапленою лінією лишався газон. Тепер
замаплена лінія `footway=sidewalk` поруч рахується з обох боків (`walkAt`).

Перевірка поза грою: `test_paving_to_a_mapped_footway_runs_across_a_side_roads_mouth`.
`mesh_pairs.py`, шар доріг до → після: тайл Хрещатика (50.4473, 30.5199) 21 834 → 23 757, сусідній (50.4510, 30.5170) 19 059 → 20 321 трикутників (+6–9 % доріг, +2,5–3 % тайла: тепер вимощені кути перехресть і лівий бік однобічних вулиць).

## Біличі: джерела і фасади — 29 жовтня 2026

Дослідний квадрат 1000 × 1000 м у EPSG:32636 має центр 50.460360, 30.344190;
результати і стан роботи — [BILYCHI_EXPERIMENT.md](BILYCHI_EXPERIMENT.md). Мета — розширити
існуючий тайловий генератор, а не дублювати `YARD.build`, `VEG.streetProps`,
парковки або дорожній рендер.

Локальний знімок Geofabrik Ukraine OSM (replication 2026-10-25T21:21:21Z) дав
165 `building`, 18 `building:part`, 717 об'єктів із класами `highway`, 44 `shop`,
31 `playground` і 44 позначені дерева в квадраті. `highway` включає пішохідні шляхи;
категорії можуть перетинатися. Просторовий аудит рахує вузли й повні ways, не
збирає multipolygon relations і може пропустити довгі ways поза буфером. Це не
повний кадастр або незалежне підтвердження об'єктів. У релізі Overture 2026-10-21.0
для квадрата виміряно 282 `building`, з них 168 із джерелом OSM і 114 із Microsoft
ML. Жоден ML-контур не перетнув замкнені OSM building ways у перевіреному тайлі,
але relations не враховані й ML може помилятися: це не доказ 114 нових будинків.
Дедуплікація джерел і перевірка їхніх ліцензій залишаються необхідними.

З 83 досліджених комерційних POI 69 мають точку всередині замкненого OSM
`building` way, один на межі, два поза ним до 10 м; 11 не мають кандидата до 10 м.
У 13 POI більше одного кандидата в цьому радіусі. Для 21 POI комерційний тег і
`building` — на тому самому way, а для way застосовано представницьку точку,
не координату входу. Просторовий збіг — кандидат на зв'язування, не доказ фасаду.
Потрібні стійкі ID, походження, збереження неоднозначності та перевірка проходів і
проїзду; невідомий вхід не вигадувати.

У цій гілці є вузький opt-in `experimentalShopfront` у `generator.build`: лише
прямий комерційний тег будівлі й одна придатна вулична стіна дозволяють замінити
нижню частину стіни на синтетичний матеріал; предмети на землі не додаються.
Прапорець за замовчуванням вимкнено і в `native.lua` не прокинуто. На наявному
spot-паку жоден з дев'яти ближніх тайлів не отримав трикутників вітрини, хоча
автоматичні тести на синтетичних будівлях пройшли. Тому жодного візуального
поліпшення району або ігрової ціни ще не доведено. Відкритий пропуск і критерії
приймання — у [GENERATION_GAPS.md](GENERATION_GAPS.md).

Baseline: BeamNG.drive 0.40.3, окремий профіль, `master` коміт
`b443b9f876df5d026b6f780f81134f88caee6797`, наявний 6-км spot-пак, якість світу 70,
High, 1280×964. Заїзд від 50.459752, 30.345888 на цілі 20 м/с пройшов 644,39 м:
середній кадр 15,47 мс, p99 36 мс; 3 кадри понад 100 мс, тому функціональний тест
`passed`, загальний `failed`. `real-v-street`, `night-v-street` і `real-v-photo`
досягли таймауту очікування сцени; відсутнє дорожнє покриття на `street`-кадрі не
доводить дірку дороги. Ракурс уздовж комерційного фасаду, повна перевірка стиків та
ігровий A/B для Data-rich і Maximum Detail ще відсутні.

Первинні звіти, знімки й ZIP зберігалися локально в `out/experiments/bilychi-1km/`,
вхідні дані — у `data/`; обидві теки ігноруються Git. Не припускати, що вони є в
іншому checkout. Spot-пак був зібраний раніше; його тотожність PBF аудиту не доведена.
