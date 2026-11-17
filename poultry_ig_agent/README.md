# 🐔 Poultry Farm Instagram Agent

YouTube пайплайнынан **толук өзүнчө** долбоор (импорт жок, өзүнүн тесттери бар).
Мазмуну: тоок ферма контенти, жумшак сатуу (курс/продукцияга кызыгуу), Reels жана карусель — кыргызча жана орусча. Автоматташтыруу/AI темасы постторго кирбейт (lint текшерет).

## Иштөө агымы
1. **plan** — Gemini апталык план түзөт (тирөөчтөр: мотивация, күндөлүк, кеңеш, уламыш, окуя, коомчулук).
2. **make** — Reel (сценарий+voiceover+caption) же карусель (PNG слайддар) драфт кылат.
3. **lint** — сан/пайыз/дары/дозалоо/«автоматташтыруу» сөздөрүн тосот; ката болсо `needs_fix`.
4. **Мен бекитем** — `approve <id>`. Бекитилмейинче эч нерсе жарыяланбайт.

## Телефондон иштетүү
GitHub → Actions → «🐔 Poultry Instagram — драфт жасоо» → Run workflow.
Натыйжа: Artifacts → `poultry-drafts` (слайддар, caption.txt, post.json).
Керек: GitHub Secret `POULTRY_GEMINI_API_KEY` (мотивация долбоорунун `GOOGLE_API_KEY`ине тийбейт). Убактысы ~2–4 мүнөт, Colab керек эмес.

## Жарыялоо
Драфтты бекиткенден кийин Metricool аркылуу график боюнча коюлат (кийинки кадам).

## Бөлүү эрежелери
- Өз secret: `POULTRY_GEMINI_API_KEY`; өз output: `poultry_ig_agent/out/`; өз workflow: `poultry_ig.yml`.
- `pipeline/` (Motivation YouTube) менен импорт/конфиг/prompt/база бөлүшүлбөйт — `tests/test_agent.py::Isolation` текшерет.
- Баа жана продукт маалыматы жок: агент аларды ойлоп таппайт (lint тосот). products.yaml кийинки этапта.

## Иштетүү
`python -m poultry_ig_agent.agent plan|make|list|approve <id>|reject <id>` (репозиторийдин тамырынан).
Тесттер: `python -m unittest discover -s poultry_ig_agent/tests -t .`
