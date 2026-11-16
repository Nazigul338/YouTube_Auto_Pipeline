# YouTube Auto Pipeline

**GitHub Actions'та** толук автоматтык иштеген YouTube видео өндүрүү системасы
(мотивация жана психология, орус тилдүү аудитория). **Colab талап кылынбайт.**

Тема → Сценарий → Сахналар → Үн (Algenib) → Субтитр → Клиптер → Анимация → Музыка →
Монтаж → QA → **Final MP4 Google Drive'да**.

- 📱 Колдонуу: [docs/USER_GUIDE.md](docs/USER_GUIDE.md)
- 🔧 Бир жолку жөндөө (ачкычтар, Drive): [docs/GITHUB_ACTIONS_SETUP.md](docs/GITHUB_ACTIONS_SETUP.md)
- 📜 Каналдын эрежелери: [docs/VIDEO_RULES.md](docs/VIDEO_RULES.md) ·
  кодго кантип киргизилген: [docs/RULES_IMPLEMENTATION.md](docs/RULES_IMPLEMENTATION.md)

## Workflow'дор (Actions бөлүмүндө)

| Workflow | Эмне кылат |
|---|---|
| 🎬 Видео жасоо | Тема же video_id менен видео жасайт/улантат |
| 🔧 Жөндөөнү текшерүү | Ачкычтар, Gemini, Pixabay, Drive, музыка |
| 🔬 Мүмкүнчүлүктөрдү сыноо | Gemini моделдери, TTS, Whisper чынында иштейби |

## Түзүлүшү

```
pipeline/
  ci.py          — GitHub Actions'тын кирүү чекити (Video_NNN, улантуу, Drive'га сактоо)
  runner.py      — этаптарды аткаруу, кайра аракет, ар этаптан кийин сактоо
  storage.py     — Drive'дагы YouTube_Auto/ түзүлүшү жана реестр
  drive.py       — Google Drive API (OAuth)
  gemini.py      — Gemini: текст, TTS, embedding, аудио/сүрөт анализ (запас моделдер, timeout)
  asr.py         — Whisper (PyAV'сыз)
  stock.py       — Pixabay / Pexels
  music.py       — музыка китепканасы (булак папкадан)
  media.py       — FFmpeg жардамчылары
  stages/        — s0_check … s9_qa (ар этап өзүнчө модуль)
  niches/        — ниша профилдери (motivation.yaml)
tests/           — 50+ тест + толук интеграциялык тест (жалган API, чыныгы FFmpeg)
legacy/          — эски Colab блокноттору (колдонулбайт, тарых үчүн)
```

Тесттер: `python -m unittest discover tests`

## Коопсуздук

Репозиторий ачык. API ачкычтары **GitHub Secrets'те гана**; логдо email жашырылат;
видео ачык жерге (artifact) коюлбайт — Drive'га гана.
