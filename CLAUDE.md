# YouTube Auto Pipeline — Claude үчүн нускама

## Тил
Колдонуучу менен **кыргыз тилинде** сүйлөш. Түшүндүрмөлөр жөнөкөй, кадам-кадам.
Колдонуучу Android телефон аркылуу иштейт.

## Милдеттүү эрежелер
Ар бир видео жана ар бир код өзгөртүү **[docs/VIDEO_RULES.md](docs/VIDEO_RULES.md)** эрежелерине
баш ийет. Кайсы эреже кайда аткарылат: [docs/RULES_IMPLEMENTATION.md](docs/RULES_IMPLEMENTATION.md).
Негизгилери: оригиналдуулук автоматташтыруудан маанилүү; фактыларды ойлоп таппа;
лицензиясы белгисиз материал колдонулбайт; QA өтпөгөн видео «даяр» эмес;
видео YouTube'га автоматтык жарыяланбайт.

## Архитектура
- `pipeline/stages/` — этаптар (`s0_check` … `s9_qa`), `stages/__init__.py` ирети.
- `pipeline/runner.py` — `state.json` аркылуу улантуу/кайра иштетүү.
- `pipeline/ci.py` + `.github/workflows/` — GitHub Actions (негизги автоматтык жол).
- `notebooks/RUN_PIPELINE.ipynb` — Colab (запас жол).
- Drive: `YouTube_Auto/Music/<булак>/`, `YouTube_Auto/Videos/<дата>_<тема>/`.

## Коопсуздук
- Репозиторий **ачык**. API ачкычтары кодго, логго, коммитке эч качан жазылбайт
  (GitHub Secrets / Colab Secrets гана).
- Колдонуучунун Drive'ындагы файлдарды уруксатсыз өчүрбө, жылдырба, үстүнөн жазба.
- Иштеп жаткан кодду уруксатсыз өчүрбө.

## Текшерүү
`python -m unittest discover tests` — ар өзгөртүүдөн кийин.
Жөндөөнү текшерүү: GitHub Actions → «🔧 Жөндөөнү текшерүү».
