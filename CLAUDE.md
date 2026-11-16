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
- `pipeline/ci.py` + `.github/workflows/make_video.yml` — GitHub Actions (ЖАЛГЫЗ жол;
  колдонуучу Colab'ды колдонбойт — Colab'га көз карандылык кошпо).
- Drive: `YouTube_Auto/{Projects,Scripts,Audio,Subtitles,Clips,Music,Final_Videos,Logs,Licenses}`;
  реестр `Projects/_registry.json`; сынак режими `YouTube_Auto_TEST/`.
- Gemini: v1beta (TTS ушунда гана иштейт), запас моделдер тизмеси `config.py`'де;
  TTS'ке берилген нускаманы модель окуп коюшу мүмкүн — s3 Whisper менен текшерет.

## Коопсуздук
- Репозиторий **ачык**. API ачкычтары кодго, логго, коммитке эч качан жазылбайт
  (GitHub Secrets / Colab Secrets гана).
- Колдонуучунун Drive'ындагы файлдарды уруксатсыз өчүрбө, жылдырба, үстүнөн жазба.
- Иштеп жаткан кодду уруксатсыз өчүрбө.

## Текшерүү
`python -m unittest discover tests` — ар өзгөртүүдөн кийин (узак тест: `tests/test_full_local.py`).
Чыныгы API'лер менен: Actions → «🎬 Видео жасоо» → test_run ✓.
Жөндөөнү текшерүү: GitHub Actions → «🔧 Жөндөөнү текшерүү».
