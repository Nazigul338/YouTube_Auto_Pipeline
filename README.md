# YouTube Auto Pipeline

Google Colab'да **бир баскыч** менен 8 мүнөттүк YouTube видео жасоочу система.
Тема киргизилет → Сценарий → Үн → Субтитр → Видеоклиптер → Музыка → Монтаж → Даяр MP4.

## Колдонуу

1. Colab'да ачыңыз:
   [notebooks/RUN_PIPELINE.ipynb](https://colab.research.google.com/github/Nazigul338/YouTube_Auto_Pipeline/blob/claude/youtube-auto-pipeline-87d41t/notebooks/RUN_PIPELINE.ipynb)
   → **File → Save a copy in Drive** (бир жолу).
2. 🔑 Secrets: `GOOGLE_API_KEY`, `PIXABAY_API_KEY` (кааласаңыз `PEXELS_API_KEY`).
3. Музыка: YouTube Studio → Audio Library'ден 3–5 трек жүктөп,
   `MyDrive/YouTube_Auto/Music/` папкасына салыңыз.
4. TOPIC жазып, ▶️ басыңыз.

## Этаптардын абалы

| # | Этап | Абалы |
|---|---|---|
| 0 | Чөйрөнү текшерүү | ✅ даяр |
| 1 | Сценарий (Gemini) | ⏳ |
| 2 | Сахналарга бөлүү | ⏳ |
| 3 | Үн (Gemini TTS, Algenib) | ⏳ |
| 4 | Субтитрлер (Whisper) | ⏳ |
| 5 | Видеоклиптер (Pixabay/Pexels) | ⏳ |
| 6 | Фондук музыка | ⏳ |
| 7 | Монтаж (FFmpeg, 1080p) | ⏳ |
| 8 | Сапатты текшерүү | ⏳ |

## Түзүлүшү

```
pipeline/
  config.py      — жөндөөлөр (моделдер, үн, резолюция)
  state.py       — state.json: ар бир этаптын абалы
  project.py     — ар бир видеого өзүнчө папка, файлдарды үстүнөн жазбоо
  runner.py      — этаптарды ирети менен иштетүү, ката/улантуу
  stages/        — ар бир этап өзүнчө модуль
  niches/        — ниша профилдери (motivation.yaml, ...)
notebooks/RUN_PIPELINE.ipynb — Colab блокноту
legacy/          — эски блокноттун көчүрмөсү
docs/            — анализ жана документация
tests/           — тесттер: python -m unittest discover tests
```

## Коопсуздук

Репозиторий ачык (public). API ачкычтары **эч качан** кодго жазылбайт —
алар Colab Secrets'те гана сакталат.
