# 🐔 Poultry Farm Instagram AI Agent (Кыргызстан)

Тоок ферма нишасы үчүн Instagram агенти: идея → сценарий → AI/реалдуу видео → диктор/субтитр/монтаж →
**сиз бекитесиз** → жарыялоо → комментарий/Direct → жумалык отчет.
**Motivation YouTube пайплайнынан толук өзүнчө** (`pipeline/` менен импорт, secret, output, prompt жок —
`tests/test_agent.py::Isolation` текшерет).

## Архитектура (модулдар, ар бири өзүнчө тесттелген)
| Модуль | Милдети |
|---|---|
| `niche/` | Ниша плагини: темалар (12), контент түрлөрү, ден соолук сөздөрү, ишенимдүү булак домендери, стиль. Жаңы ниша = жаңы файл + `REGISTRY` |
| `agent.py` | CLI жана `run()` (START), идея/пост генерациясы, бекитүү |
| `lint.py`, `safety.py`, `sales.py` | Эрежелер: тыюу сөздөр, сандар, ветеринар коопсуздугу, чынчыл сатуу |
| `calc.py` | Жем/киреше эсеби — сиз киргизген сандар менен, LLM сан ойлобойт |
| `video.py` | Кадр план → Veo/сиздин файлдар → Gemini TTS → субтитр → 9:16 монтаж (ffmpeg) |
| `instagram.py`, `publisher.py` | Meta Graph API жана жарыялоо дарбазасы (бекитүү, dry-run, автопилот шарттары) |
| `analytics.py` | Жумалык отчет |
| `settings.json`, `course.json` | Жөндөөлөр жана курс маалыматы (баа/төлөм/байланыш — өзгөртүлөт) |

## Башкаруу панели (телефондон)
GitHub → Actions → **«🐔 Poultry Instagram — START»** → Run workflow:
тема · түрү (билим/сатуу/…) · формат (Reels/Stories/карусель) · тил (ky/ru) · видео жасоо ✓.
Натыйжа: Artifacts → `poultry-package` (сценарий, caption, слайддар, `final.mp4`).
Жумалык отчет: «…жумалык отчет» (дүйшөмбү күнү автоматтык же кол менен).

## Жайгаштыруу (бир жолу)
1. **GitHub Secrets:** `POULTRY_GEMINI_API_KEY` (контент, Veo, диктор). Жарыялоо үчүн: `POULTRY_IG_ACCESS_TOKEN`, `POULTRY_IG_USER_ID`
   (Instagram Business/Creator аккаунт + Meta app, `instagram_content_publish`, `instagram_manage_comments`, `instagram_manage_insights`, `instagram_manage_messages` уруксаттары).
2. `course.json` толтуруңуз (баа, төлөм, WhatsApp). Бош болсо агент баа ойлоп таппайт, сатуу постун бекитүүгө жол бербейт.
3. Реалдуу видео/сүрөт: `poultry_ig_agent/assets/real/`, музыка: `assets/music/`.
   ⚠️ Репозиторий ачык — жеке/маанилүү файлдарды ушунда сактабаңыз (Drive интеграциясы кийинки этап).

## Диктор үнү (дайыма бир үн)
`settings.json → voice`: `provider: "elevenlabs"`, `elevenlabs_voice_id: "<ID>"`, `owner_consent_confirmed: true`
(үн ээси уруксат бергенде гана). Ачкыч — GitHub Secret `POULTRY_ELEVENLABS_API_KEY`. Ар Reel'дин caption'ына
«🎙 Диктордун үнү AI менен түзүлгөн» деген ачыктоо автоматтык кошулат (`disclose_ai_voice`).

## Коопсуздук жана чындык
- Дозасы, дары сунуштоо, диагноз — тыюу. Ден соолук посту: ветеринар эскертүүсү автоматтык, булак ишенимдүү домендер тизмесинен,
  `needs_vet_review` → `approve <id> --vet-reviewed` менен гана бекитилет. **Булактын мазмуну автоматтык тастыкталбайт — текшерүү сизде/ветеринарда.**
- Реалдуу видео жетишпесе агент AI'ге жашырын алмаштырбайт (`needs_footage`). `real_farm` — AI кадр жок. AI кадрга «AI иллюстрация» жазуусу + caption ачыктоосу.
- Сатуу: баа/кепилдик/жасалма шашылтуу жок; жооптор `course.json` фактыларынан. Белгисиз суроо → менеджерге.

## Жарыялоо жана автопилот
`list` → `approve <id>` → `publish <id>` (dry-run) → `publish <id> --live` (`settings.json: publish_live=true` болгондо).
Автопилот `settings.json → autopilot.enabled=true` + кол менен бекитилген N (5) жарыялоодон кийин гана; ден соолук/каталуу постко эч качан.

## Тесттер
`python -m unittest discover -s poultry_ig_agent/tests -t .` (46 тест; видео тесттери ffmpeg менен чыныгы монтаж жасайт).
Чыныгы API (Gemini/Veo/TTS/Meta) менен текшерүү → `PROJECT_STATUS.md` 5/7-бөлүк.
