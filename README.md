# YouTube Auto Pipeline

**GitHub Actions'та** толук автоматтык иштеген YouTube видео өндүрүү системасы
(мотивация жана психология, орус тилдүү аудитория, ~8 мүнөттүк видео). **Colab талап кылынбайт.**

Тема → Сценарий → Сахналар → Үн (Gemini TTS, Algenib) → Субтитр (Whisper) → Клиптер →
Анимация → Музыка → Монтаж (FFmpeg, 1080p) → QA → **Final MP4 Google Drive'да**.

> 📌 **Азыркы абал, ачык көйгөйлөр жана кийинки кадамдар: [PROJECT_STATUS.md](PROJECT_STATUS.md)**
> (биринчи толук видео чыныгы API менен 2026-11-16 жасалды — ошол файлды караңыз).

## Документтер
- 📱 Колдонуу: [docs/USER_GUIDE.md](docs/USER_GUIDE.md)
- 🔧 Бир жолку жөндөө (ачкычтар, Google Drive): [docs/GITHUB_ACTIONS_SETUP.md](docs/GITHUB_ACTIONS_SETUP.md)
- 📜 Каналдын эрежелери: [docs/VIDEO_RULES.md](docs/VIDEO_RULES.md) ·
  кодго кантип киргизилген: [docs/RULES_IMPLEMENTATION.md](docs/RULES_IMPLEMENTATION.md)
- 🤖 Claude үчүн сессия тартиби: [CLAUDE.md](CLAUDE.md)

## 🎬 Формат: мотивациялык видео (ниша `motivation`, «🎬 Видео жасоо» демейкиси; 2026-11-24)
Кино-окуя форматы колдонуучунун чечими менен токтотулду; анын коду сакталды, бирок өзү сурамайынча иштетилбейт.

### (Токтотулган) кино-окуя: бир каармандын 8 мүнөттүк кыска кино-окуясы (ниша `psych_story`;
`hero` талаасына каарман жөнүндө талап жазса болот). Каарман профили → 7 актылуу сюжет → окуя сценарийи →
кино-разбивка → каармандын туруктуулугу (continuity) → режиссёрдук концепция → музыкалык арка → окуя обложкасы →
QA `check_story`. Модулдар: `pipeline/story.py`, `pipeline/continuity.py`. Эски формат: `niche: motivation`.

## 🥇 Оригиналдуулук — №1 приоритет
Ар видео өз монтаж концепциясы менен жасалат жана мурунку даяр видеолор менен салыштырылат; окшош болсо QA
видеону бербейт. Толук эреже: CLAUDE.md, docs/VIDEO_RULES.md (0-бөлүм), docs/RULES_IMPLEMENTATION.md.

## 🎯 Hook, обложка, retention (2026-11-21)
Кликке азгыруу эмес — чыныгы кызыгуу. s1: катаал «көрүүчү» (Gemini) hook'ту, убаданы (сценарийден цитата менен),
жалган интриганы, кайталоону жана финалды баалайт; жетишсиз болсо башталыш/финал кайра жазылат (`pipeline/retention.py`).
s9: биринчи фраза даяр үндө ≤5 сек, жалган убада жок (милдеттүү). Обложка: ≤6 сөз, контраст, жообу видеодо бар,
мурункулардан башка жайгашуу/түс/сүрөт, Gemini көрүү баасы. Отчетто 6 суроолуу акыркы текшерүү.
Даяр видеонун обложкасын кайра жасоо: Actions → «🖼 Обложка» → `thumbs: auto`.

## Керектүү API ачкычтар (GitHub → Settings → Secrets and variables → Actions)

| Secret | Милдеттүүбү | Эмне үчүн |
|---|---|---|
| `GOOGLE_API_KEY` | ✅ | Gemini: сценарий, үн (TTS), музыка/кадр анализи; AI-сүрөт (СЫНАК) үчүн ачкычтын долбоорунда **billing** күйгүзүлүшү керек |
| `PIXABAY_API_KEY` | ✅ | видео/сүрөт клиптер |
| `GDRIVE_CLIENT_ID` | ✅ | Google Drive OAuth |
| `GDRIVE_CLIENT_SECRET` | ✅ | Google Drive OAuth |
| `GDRIVE_REFRESH_TOKEN` | ✅ | Google Drive OAuth (токен **Production** режиминде алынышы керек) |
| `PEXELS_API_KEY` | – | кошумча клип булагы |

Репозиторий **ачык**: ачкычтарды коддо, логдо, issue'да же чатта эч качан жазбаңыз.

## Бир баскыч менен видео жасоо

1. github.com/Nazigul338/YouTube_Auto_Pipeline/actions → **🎬 Видео жасоо** → **Run workflow**.
2. **topic** талаасына теманы жазыңыз → **Run workflow**.
3. ~70 мүнөттөн кийин (чыныгы өлчөнгөн: 69 мүн, 9:31 видео) видео: Drive → `YouTube_Auto/Final_Videos/Video_NNN.mp4`.
   Сценарий, үн, субтитр, лицензия, QA отчету — `Scripts/`, `Audio/`, `Subtitles/`, `Licenses/`, `Projects/Video_NNN/`.

Токтоп калса: **🔁 Токтоп калган видеону улантуу** күн сайын өзү улантат (квота/убактылуу ката).
Колго улантуу: `🎬` → **video_id** (мис. `Video_004`), topic бош. Сынак: `test_run` ✓ (`YouTube_Auto_TEST/`).

## Workflow'дор

| Workflow | Эмне кылат |
|---|---|
| 🎬 Видео жасоо | Тема же `video_id` менен видео жасайт/улантат |
| 🔁 Токтоп калган видеону улантуу | Күн сайын өзү: квота/убактылуу катадан токтогонду улантат |
| 🔧 Жөндөөнү текшерүү | Ачкычтар, Gemini, Pixabay, Drive, музыка |
| 🔐 Drive авторизациясын текшерүү | OAuth режими (Testing/Production), токен жаңыртуу, чыныгы жүктөө |
| 🔬 Мүмкүнчүлүктөрдү сыноо | Gemini моделдери, TTS, Whisper чынында иштейби |

## Системанын архитектурасы

```
pipeline/
  ci.py          — GitHub Actions кирүү чекити (Video_NNN, улантуу, Drive'га сактоо, --resume-pending)
  runner.py      — этаптарды аткаруу, кайра аракет, ар этаптан кийин сактоо, ката түрлөрү
  storage.py     — Drive'дагы YouTube_Auto/ түзүлүшү жана реестр
  drive.py       — Google Drive API (OAuth)
  auth_check.py  — OAuth/Drive текшерүү
  gemini.py      — Gemini: текст, TTS, embedding, аудио/сүрөт анализ (запас моделдер, квота, timeout). Veo колдонулбайт
  asr.py         — Whisper (PyAV'сыз)
  stock.py       — Pixabay / Pexels (беттөө менен; бренд/логотиптүү жана мультфильм/анимация клиптери чыпкаланат, Pixabay video_type=film)
  ai_images.py   — Gemini AI-сүрөттөр (СЫНАК): prompt, 16:9, бюджет/баа, Drive AI_Images/ кэши
  visual_compare.py — даяр видеолорду визуалдык салыштыруу (кадрлар, түс, композиция, ыргак, түзүлүш) — `🎞 Визуалдык из`
  edit_concept.py — ар видеонун ӨЗ монтаж концепциясы (түс, ыргак, кыймыл, өтүү, субтитр) — мурункулардан айырмалуу
  visual_rules.py — кадр тандоонун жалпы эрежелери: маани (метафора → турмуштук кырдаал), монетизация, шаблонго каршы
  thumbnail.py   — обложка видеонун кадрынан (1280×720, жазуу, градиент, чынчылдык + көрүү баасы) → Drive Thumbnails/ (`🖼 Обложка` workflow, `auto`)
  story.py       — кино-окуя: каарман профили, 7 актылуу сюжет, актылар, окуя QA
  continuity.py  — каармандын туруктуулугу (эталон кадр + Gemini көрүү)
  retention.py   — hook + көрүүчүнү кармоо баалоосу, hook убактысы, 6 суроолуу акыркы текшерүү
  sfx_synth.py   — оригиналдуу үн эффекттерин синтездөө (CC0, жүктөө жок)
  sfx.py         — Sound Effects Library (СЫНАК): лицензия капкасы, сценага жараша тандоо, паузага коюу, деңгээл
  clipmemory.py  — Smart Video Memory: колдонулган клиптердин Drive базасы (JSON + CSV)
  clipsearch.py  — акылдуу издөө: сахнанын темасы/маанисине жараша, кайталанбастан
  music.py       — музыка китепканасы (булак папкадан, лицензия)
  media.py       — FFmpeg жардамчылары
  stages/        — s0_check … s9_qa (ар этап өзүнчө модуль)
  niches/        — ниша профилдери (motivation.yaml)
tests/           — 77 тест + толук интеграциялык тест (жалган API, чыныгы FFmpeg)
legacy/          — эски Colab блокноттору (колдонулбайт, тарых үчүн)
```

Этаптар: `s0_check` → `s1_script` → `s2_scenes` → `s3_voice` → `s4_subtitles` → `s5_visuals` →
`s6_animation` → `s7_music` → `s8_render` → `s9_qa` (QA өтсө гана Final MP4 «даяр»).

## Каталарды аныктоо жана чечүү

Иштин **Summary** бетинде кайсы этапта, эмне себептен токтогону жазылат.

| Ката | Себеби жана чечими |
|---|---|
| `КҮНҮМДҮК квота бүттү` (Gemini) | Акысыз квота бүттү — 🔁 workflow эртеси өзү улантат |
| `503 high demand` | Gemini убактылуу бош эмес — система өзү кайра аракет кылат |
| `refresh token эскирген` / `invalid_grant` | Google токени өчтү (Testing токени 7 күн). `docs/GITHUB_ACTIONS_SETUP.md` B5 менен жаңы токен алып, `GDRIVE_REFRESH_TOKEN`'ди алмаштырыңыз; текшерүү: 🔐 workflow |
| `QA өткөн жок` | `Projects/Video_NNN/report.txt`'те ❌ пункттарды караңыз; чыныгы ката автоматтык уланбайт |
| `GOOGLE_API_KEY жок` ж.б. | Secrets'ке кошуңуз; `🔧 Жөндөөнү текшерүү` иштетиңиз |
| Үн «туура эмес» (3-этап) | Система бөлүктү өзү кайра жаратат; 4 аракеттен кийин да болбосо — `rerun_from: s3_voice` |

Тесттер: `YTA_SKIP_SLOW=1 python -m unittest discover tests`

## Коопсуздук

API ачкычтары **GitHub Secrets'те гана**; логдо email жашырылат; видео ачык жерге (artifact)
коюлбайт — Drive'га гана; видео YouTube'га **автоматтык жарыяланбайт**.

## 🎞 Cinematic режими — PRODUCTION'до күйүк (колдонуучу бекитти 2026-11-20)

> `🎬 Видео жасоо` жана `🔁 улантуу` workflow'дору: `YTA_CINEMATIC=1`, `YTA_HYPERFRAMES=1`, `YTA_SFX=1`, `YTA_VOICE_STYLE=motivational`.
> Код коргоосу: `pipeline/cinematic.py: PRODUCTION_APPROVED` (False кылса — кайра TEST гана). Production'до файл `Final_Videos/<ID>.mp4`.
> AI-сүрөттөр — TEST гана (billing жок).

Негизги өндүрүшкө КОШУЛГАН ЭМЕС: колдонуучунун уруксатысыз production'го өтпөйт.
- Иштетүү: Actions → **🎞 Cinematic сынак (TEST гана)** → `video_id` (мис. `Video_003`). Ар дайым `YouTube_Auto_TEST`'ке жазат,
  жыйынтык `Final_Videos/<ID>_cinematic.mp4` (эски `<ID>.mp4` сакталат), салыштыруу барагы `_diagnose/<ID>_compare.jpg`.
- Код коргоосу: `YTA_CINEMATIC=1` + папка `YouTube_Auto_TEST` болгондо гана күйөт (`pipeline/cinematic.py: enabled`).
- Эффекттер: жумшак S-ийри (контраст, highlights/shadows), концепция түсү, жумшак glow (luma), film grain, кадрлардын жарык/түсүн
  бирдейлөө, 16:9'га туура келбеген материалга blur фон (кара тилке жок), кинематографиялык өтүүлөр (0.7 сек).
- HyperFrames (`tools/hyperframes`, Node 22, бекитилген 0.9.61) — орусча анимацияланган карточкалар (тунук фон, ProRes 4444);
  иштебесе — ASS карточкалары. Телеметрия өчүк.
- FFmpeg Skill (`.claude/skills/ffmpeg-skill`, MIT, v3.10.1): Claude сессияларында колдонулат; `check.py --platform youtube`
  cinematic сынагынын QA'сына кирет.

## 🎙 Мотивациялык диктор — PRODUCTION'до күйүк (2026-11-20)

- **Үн лабораториясы:** Actions → **🎙 Үн лабораториясы** → бир эле орусча текст 4 вариантта (Algenib учурдагы / Algenib
  мотивациялык / Orus / Charon). Drive → `YouTube_Auto_TEST/_voice_test/` (үн жана музыка менен MP3), run бетинде таблица:
  темп, Whisper дикциясы, паузалар, F0 (тереңдик), интонация өзгөрүлмөлүүлүгү, «үн − музыка» LU.
- **Видеодо:** `🎞 Cinematic сынак` → `rerun_from=s3_voice`, `motivational_voice` ✓ (`YTA_VOICE_STYLE=motivational`).
  `pipeline/voice_style.py`: режиссёрдук нускама, сахнанын `keywords` боюнча басым, паузалар (сөздөр өзгөрбөйт).
  Production'до (YouTube_Auto) өчүк — учурдагы Algenib + `tts_style` өзгөрүүсүз.

## 🖼 AI-сүрөттөр (Gemini API) — СЫНАК (TEST гана)

- **Иштетүү:** `🎞 Cinematic сынак` → `rerun_from=s5_visuals` (же жаңы видео), `ai_images` ✓, `ai_image_max` (демейки 12),
  `ai_image_budget` (демейки $0.50). Код коргоосу: `YTA_AI_IMAGES=1` + `YouTube_Auto_TEST` (production'да өчүк).
- **Эмне кылат:** негизги материал — Pixabay/Pexels видеолору. Gemini ар кадрды сценарийге баалайт; сток туура келбеген
  (≤2/5) жана сахнанын маанилүү кадрларына гана AI-сүрөт жаратылат (катар эмес, сахнада ≤2, видеонун ≤20%).
  AI-сүрөт да бааланат — стоктон жакшы болсо гана коюлат. Ар видеонун өз визуалдык стили (мурункуну кайталабайт).
  Сүрөттөр 16:9 жаратылып, 1920×1080'ге толтурулат жана кадр кыймылын (Ken Burns, zoom, dolly in/out) алат.
- **Чыгым:** баа `pipeline/ai_images.py: PRICE_USD` (gemini-2.5-flash-image ≈ $0.039/сүрөт) → 12 сүрөт ≈ **$0.47/видео**
  (чек ашпайт). Отчет: `Projects/<ID>/clips/ai_images.json`, QA `ai_images`. Кэш: Drive `AI_Images/` — кайра иштетүүдө
  акча кайра кетпейт; башка видеонун сүрөтү колдонулбайт.
- **Каталар:** 429 (акысыз ачкычта сүрөт квотасы 0 — 2026-11-18 чыныгы текшерүү, probe run #44355771363), billing жок,
  5xx → AI-сүрөттөр токтойт, кадрлар сток бойдон калат, видео токтобойт.
- **YouTube:** AI-сүрөт болсо QA «Altered or synthetic content = Yes» сунуштайт; LICENSE жана сүрөттөмөгө AI белгиси кошулат.
- **Текшерүү:** Actions → `🔬 Мүмкүнчүлүктөрдү сыноо` → `only=image` (1 сүрөт ≈ $0.04).


## 🔊 Үн эффекттери (Sound Effects Library) — PRODUCTION'до күйүк (2026-11-20)

- **Иштетүү:** `🎞 Cinematic сынак` → `rerun_from=s7_music` (же андан мурунку этап), `sound_effects` ✓.
  Код коргоосу: `YTA_SFX=1` + `YouTube_Auto_TEST` (production'да өчүк; желексиз 7-этап мурдагыдай).
- **Аудио кайда:** Drive `YouTube_Auto/Sound_Effects/<категория>/` (cinematic, atmosphere, nature, transitions, impact,
  emotional; папкаларды система түзөт). Репозиторийдеги `assets/sound_effects/` — структура, README, metadata үлгүсү;
  аудио ачык репозиторийге коммит кылынбайт (`.gitignore`).
- **Лицензия капкасы:** ар аудионун жанында `<файл>.metadata.json` (үлгү `assets/sound_effects/metadata.example.json`).
  `commercial_use: true` + лицензия CC0 / Pixabay Content License / Mixkit Free License + толук талаалар (+ sha256 жазылса
  дал келүү) болбосо — аудио видеого **кошулбайт** (логдо «🔇 SFX четке кагылды: … — себеби»).
- **Тандоо:** сахна алмашуусунда whoosh (≥20 сек аралык), dramatic/tense/determined → impact (≤3), hopeful/inspired →
  emotional/cinematic (≤3), табият кадрлары → nature фон, тынч маанай → atmosphere фон (≤50% убакыт). Бир эле үн катар
  кайталанбайт; план видеонун ID'си боюнча туруктуу.
- **Деңгээл:** диктордун өлчөнгөн катуулугуна салыштырмалуу: «сокку» — диктордун паузасында, 12–14 LU акырын (пик ≤ −6 dBFS);
  фондор 22–24 LU акырын жана диктор сүйлөгөндө музыка менен бирге басаңдайт. QA `sfx_license`, `sfx_level` (≥10 LU).
- **Угулуучу музыка (СЫНАК/cinematic, 2026-11-20):** мурунку жол (−31 LUFS + ratio 6) сүйлөө учурунда музыканы диктордон
  ~27 LU төмөн түшүргөн — телефондо угулчу эмес. Cinematic'те: −21 LUFS + жумшак басаңдатуу (ratio 2.5) → ~12 LU; QA `music_audible`
  (9–16 LU). Эффекттер: сокку 11 LU, фон 17 LU акырын. Production жолу өзгөргөн жок.
- **Отчет:** `Projects/<ID>/music/sfx.json` (окуялар, себептер, лицензиялар, четке кагылгандар); LICENSE.txt «ҮН ЭФФЕКТТЕРИ».
- **Булактар:** (1) `pipeline/sfx_synth.py` — 15 ОРИГИНАЛДУУ эффект (numpy+FFmpeg синтез; автору долбоор, CC0 1.0; жүктөө жок):
  `python -m pipeline.sfx_synth <папка>`; 2026-11-19 Drive `Sound_Effects/`'ке жүктөлдү. (2) Сиз өзүңүз салган аудио (metadata менен).
  Pixabay API'де үн эффекттери жок; ZvukiPro/Pixabay ж.б. сайттардан автоматтык жүктөө/scraping ЖОК.
- **Чыгым:** $0 (FFmpeg гана). Кошумча убакыт ≈ 1–2 мүн.
