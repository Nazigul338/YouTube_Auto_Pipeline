# GitHub Actions жөндөө колдонмосу (Android телефондон)

Бир жолу жасалат, болжол менен 20–30 мүнөт. Андан кийин видео жасоо:
**GitHub → Actions → «🎬 Видео жасоо» → Run workflow → тема жазуу.**
Телефон өчүк болсо да иштейт.

> Google Cloud Console'дун интерфейси өзгөрүп турат. Меню аттары бир аз башкача
> болушу мүмкүн — ката кетсе, экрандын сүрөтүн жөнөтүңүз, бирге табабыз.
> Телефондон оңой болушу үчүн браузердин **«Desktop site»** (компьютер версиясы)
> режимин күйгүзүңүз.

## A. GitHub Secrets (ачкычтар)

Репозиторий → **Settings → Secrets and variables → Actions → New repository secret**

| Аты | Мааниси |
|---|---|
| `GOOGLE_API_KEY` | Gemini API ачкычыңыз (Colab Secrets'теги эле) |
| `PIXABAY_API_KEY` | Pixabay API ачкычыңыз |
| `PEXELS_API_KEY` | милдеттүү эмес |

⚠️ Репозиторий **ачык (public)**. Ачкычтарды эч качан кодго, issue'га же чатка жазбаңыз —
Secrets'ке гана салыңыз.

## B. Google Drive'ка кирүү (3 маани)

GitHub'дын серверине сиздин Drive'ка кирүүгө уруксат керек. Муну OAuth менен жасайбыз.

### B1. Google Cloud долбоору
1. https://console.cloud.google.com → жогорудан **New Project** → аты: `youtube-auto` → Create.
2. **APIs & Services → Library** → «Google Drive API» → **Enable**.

### B2. OAuth экраны
1. **APIs & Services → OAuth consent screen** (же «Google Auth platform»).
2. User type: **External** → App name: `youtube-auto`, email: өзүңүздүн → Save.
3. **Test users** бөлүмүнө өз Gmail'иңизди кошуңуз.
4. ⚠️ **МААНИЛҮҮ:** «Publishing status» **Testing** болсо, токен **7 күндөн кийин өчөт**.
   **«Publish app» / «In production»** кылыңыз. Google «verification керек» деп эскертет —
   бул сиздин жеке колдонууңуз үчүн милдеттүү эмес, жөн эле улантыңыз.

### B3. OAuth клиент ID
1. **Credentials → Create credentials → OAuth client ID**.
2. Application type: **Web application**.
3. **Authorized redirect URIs** → кошуңуз:
   `https://developers.google.com/oauthplayground`
4. Create → **Client ID** жана **Client secret** көрүнөт.
   Аларды GitHub Secrets'ке кошуңуз: `GDRIVE_CLIENT_ID`, `GDRIVE_CLIENT_SECRET`.

### B4. Refresh token алуу
1. https://developers.google.com/oauthplayground ачыңыз.
2. Жогорку оң бурчтагы ⚙️ → **Use your own OAuth credentials** күйгүзүп, Client ID жана Secret киргизиңиз.
3. Сол жактагы талаага (Step 1) жазыңыз: `https://www.googleapis.com/auth/drive` → **Authorize APIs**.
4. Gmail'иңизди тандап, уруксат бериңиз («unverified app» → Advanced → Continue).
5. **Step 2 → Exchange authorization code for tokens** → **Refresh token** көчүрүңүз.
6. GitHub Secrets'ке `GDRIVE_REFRESH_TOKEN` деп кошуңуз.

## C. Drive'дагы папкалар

`MyDrive/YouTube_Auto/Music/` ичине YouTube Studio → **Audio Library**'ден жүктөлгөн
3–5 мотивациялык тректи салыңыз (mp3).
Каалаган тректи колдонуудан мурун анын шарттарын (attribution талабы бар-жогун) караңыз.

`Videos/` папкасын система өзү түзөт.

## D. Текшерүү

**Actions → «🔧 Жөндөөнү текшерүү» → Run workflow.**
Ачылган иштин **Summary** бетинде таблица чыгат:
✅ ачкычтар, ✅ Gemini, ✅ Pixabay, ✅ Google Drive, ✅ музыка.
Кызыл ❌ болсо — «Эскертүү» мамычасында себеби жазылат.

## E. Видео жасоо

**Actions → «🎬 Видео жасоо» → Run workflow** → `topic` жазыңыз → **Run workflow**.
- Жыйынтык: Drive → `YouTube_Auto/Videos/<дата>_<тема>/`
- Ката болсо да, логдор ошол папкага жүктөлөт.
- Видео жалпыга ачык жерге (GitHub artifact) **коюлбайт**, анткени репозиторий ачык.

## Чектөөлөр
- Бир иштетүү максимум 3 саат (бизге ≈ 1 саат жетет).
- Бир убакта бир гана видео жасалат.
- Ачык репозиторийде Actions мүнөттөрү бекер.
