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

GitHub'дын серверине сиздин Drive'ка кирүүгө уруксат керек (OAuth). Алынат:
`GDRIVE_CLIENT_ID`, `GDRIVE_CLIENT_SECRET`, `GDRIVE_REFRESH_TOKEN`.

> Бардык шилтемелерде долбоор ID'си `youtube-auto-514818` деп берилген.
> Өзүңүздүн ID'иңиз башка болсо, `?project=` бөлүгүн алмаштырыңыз.
> Бар болгон башка долбоорлордогу OAuth колдонмолорго (мис. Claude Colab Connector) тийбеңиз.

### B1. Өзүнчө долбоор
https://console.cloud.google.com/projectcreate → аты `youtube-auto` → **Create**.
Жогорку тилкеде долбоор аты `youtube-auto` экенин текшериңиз.

### B2. Drive API
https://console.cloud.google.com/apis/library/drive.googleapis.com?project=youtube-auto-514818 → **Enable**.

### B3. OAuth экраны (Google Auth Platform)
https://console.cloud.google.com/auth/overview?project=youtube-auto-514818 → **Get started**:
1. App name: `Video Auto Pipeline`.
   ⚠️ Атта **«YouTube» / «Google»** деген сөз болбосун, Google четке кагат
   («app name does not comply with Google's requirements»).
2. Audience: **External**. Contact email: өз Gmail'иңиз → **Create**.
3. **Branding** бетинде (милдеттүү эмес, бирок Publish'ке жардам берет):
   - Home page: `https://github.com/Nazigul338/YouTube_Auto_Pipeline`
   - Privacy policy: GitHub Pages иштесе
     `https://nazigul338.github.io/YouTube_Auto_Pipeline/#privacy`,
     болбосо `https://github.com/Nazigul338/YouTube_Auto_Pipeline/blob/claude/youtube-auto-pipeline-87d41t/docs/PRIVACY.md`
   - Authorized domain: `github.com` (кабыл албаса, бош калтырыңыз)
   > Pages күйгүзүү: репозиторий → Settings → Pages → Source: *Deploy from a branch*
   > → Branch: `claude/youtube-auto-pipeline-87d41t` / `(root)` → Save.
4. **Audience → Test users → Add users** → өз Gmail'иңиз → Save.
5. **Audience → Publish app → Confirm** (статус «In production» болсун).
   - Баскыч боз болсо: бетти жаңыртыңыз, Branding'ди Save кылыңыз.
   - Баары бир болбосо, **Testing** режиминде улантыңыз. Бирок бул режимде
     refresh token **7 күндөн кийин өчөт** (кийин 5 мүнөттө жаңыртылат,
     системанын эскертмеси «refresh token эскирген» деп чыгат).

### B4. Client ID жана Secret
**Clients → Create client** → *Web application* → Name: `pipeline` →
**Authorized redirect URIs**: `https://developers.google.com/oauthplayground` → **Create**.
GitHub Secrets'ке: `GDRIVE_CLIENT_ID`, `GDRIVE_CLIENT_SECRET`.

### B5. Refresh token
1. https://developers.google.com/oauthplayground ачыңыз.
2. ⚙️ → **Use your own OAuth credentials** → Client ID жана Secret киргизиңиз.
3. Step 1: `https://www.googleapis.com/auth/drive` → **Authorize APIs**.
4. Gmail тандаңыз. «Google hasn't verified this app» → **Advanced → Go to … (unsafe) → Allow**.
5. Step 2: **Exchange authorization code for tokens** → **Refresh token** көчүрүңүз.
6. GitHub Secrets'ке `GDRIVE_REFRESH_TOKEN`.
   ⚠️ Токен Client ID/Secret менен **бир эле клиенттен** алынышы керек.

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
