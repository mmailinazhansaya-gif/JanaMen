# Визуальные ресурсы JanaMen

Все ресурсы находятся в `static/assets/` и входят в архив проекта.

- `office-characters.png`: прозрачный спрайт-лист 1448 × 1086, 4 столбца × 3 строки. Строки: Алина, Санжар, HR. Столбцы: спокойная поза, два кадра приветствия, вид со спины. Создан встроенным ImageGen по трём пользовательским изображениям персонажей.
- `office-map.png`: оригинальный фон офиса 1448 × 1086. Создан встроенным ImageGen по пользовательским референсам интерьеров. Комнаты, персонажи и кнопки взаимодействуют через отдельные HTML-элементы.
- `Tiny5.ttf`: открытый шрифт Tiny5 из https://github.com/google/fonts/tree/main/ofl/tiny5 . Лицензия в `Tiny5-OFL.txt`. Кириллические символы для приветствия и кнопок проверены.

## Задание для генерации персонажей

Create a production sprite sheet for a cute detailed pixel-art office web game. These three images are character identity and style REFERENCES, not target canvases. Output PNG with TRUE TRANSPARENT BACKGROUND, no checkerboard, no white. Exact layout: 4 equal columns x 3 equal rows, 12 equally sized cells. Wide canvas aspect ratio 4:3, ideally 1024x768. Each character centered horizontally in its cell and feet at same relative baseline, entire figure with ample padding; same scale in all cells; character occupies approx 65% cell height. Row 1: woman with long brown hair, red/pink outfit and black shoes like reference1. Row2: man black hair cream jacket black pants like reference2. Row3: woman black hair green top blue skirt like reference3. Every row columns: col1 front-facing idle arms down; col2 front-facing wave with right arm raised beside head; col3 front-facing wave with same raised hand tilted outward; col4 rear-facing standing, showing back hair/clothes. Crisp hand-placed pixel art, consistent dark outlines, expressive eyes, rich limited palette, no antialiasing or blurry edges, no props, no shadows outside character, absolutely no labels, text, grid, borders or decorations. Grid alignment important: centers x=12.5%,37.5%,62.5%,87.5%; row centers y=16.67%,50%,83.33%. These are friendly full-body chibi office avatars.

## Задание для генерации карты

Create an original high-quality pixel-art OFFICE FLOOR MAP for an interactive web game. References are only STYLE examples: detailed cozy 16-bit top-down interiors, solid pixel outlines, visible desks, sofas, potted plants. No hospital beds, no hospital, no copied floor plan, no watermark, absolutely NO people or characters and NO text or letters. Aspect 4:3. Fill whole image with a rectangular enclosed office floor viewed directly top down with slight front view furniture, sage green highlights, warm beige tile corridors, wooden room floors, cream walls, windows, bright cozy daylight. EXACT functional layout in percentage coordinates: LEFT column x2%-27%: kitchen with coffee station at y4%-32%, buffet counter and snacks at y36%-55%, lounge sofa and rug at y67%-88%. CENTRAL room open space x37%-65%, y16%-55%: exactly SIX individual desks in TWO columns THREE rows, each with monitor and its own chair BELOW its desk; leave empty walkway between the columns. Central top x37%-65%, y3%-12% a decorative window/wall plant feature. RIGHT x71%-97%: computer/AI room y4%-25%, manager private office with ONE big executive desk y29%-55%, HR file room with records and ONE desk y67%-88%. CENTER LOWER x37%-65%,y67%-88%: academy training room with bookcases and learning tables. MAIN CORRIDOR vertical x28%-36% spans full height, horizontal y57%-65% spans width. Bottom middle x28%-70%, y90%-100% a spacious ENTRANCE HALL with double glass entrance doors at bottom center x50%, welcome mat, reception counter at bottom-left of hall and plants, obvious unobstructed walking space. All room doors OPEN into these corridors, doorways at kitchen right edge y24%, buffet right edge y47%, lounge right edge y77%, open space left edge y44%, right-side rooms bottom edges connecting horizontal corridor. No walls across main corridors. Crisp clean pixel art, detailed readable furniture at game scale, nuanced pixel shading, consistent chunky pixel grid, no blur, no gradients, no text. This is a floor-plan game background, no UI overlays.

Координаты движения скорректированы по фактическому результату генерации. Оригинальный Workverse хранится отдельно без изменений.

## Разные NPC
`static/assets/npc-characters.png`: новый прозрачный атлас 4×3, 12 разных персонажей по двум предоставленным примерам от 10:11. На карте используются первые восемь, каждому закреплено отдельное место. Создан встроенным imagegen.


### Авторские учебные видео
client-service.mp4 и digital-safety.mp4 — самостоятельные демонстрационные уроки по 344,87 и 344,85 секунды. Рисованная программно доска 1280×720, 12 кадров/с; записи раскрываются поэтапно. Текст и тесты — content/academy.json. Синтетический мужской голос ru-RU-DmitryNeural создан через edge-tts; чужой голос не клонировался. Исходный WhatsApp-ролик использован только как пример формата «объяснение у доски», не встроен и не скопирован. Субтитры VTT рассчитаны по длительности фраз внутри каждой главы; возможны небольшие расхождения синхронизации.

### Дополнительные учебные видео

Двенадцать новых роликов Jana Academy построены из собственных учебных сценариев (`content/academy.json`) с анимированной доской и русской синтетической озвучкой. Использован локальный голос macOS с обработкой тембра; это не голос человека из видео-референса. Лица или фрагменты референса не использованы. Первые два ролика сохраняют исходную синтетическую озвучку.
