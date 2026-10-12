# BOSFOR Restaurant OS — Render Free (танҳо барои тест)

## Барои оғоз

1. Репозитории нави **private** дар GitHub созед: `bosfor-restaurant-test`.
2. Файлҳои ин папкаро ба он Git repository бор кунед. ZIP-ро ҳамчун як файл дар repo нигоҳ надоред; `server.py`, `public/`, `bosfor/` ва `requirements.txt` бояд дар root бошанд.
3. Render → New → Blueprint → GitHub repository → `bosfor-restaurant-test` → deploy.
   Ё Render → New Web Service бо чунин параметрҳо:
   - Runtime: Python; Plan: Free; Region: Frankfurt
   - Build: `pip install -r requirements.txt`
   - Start: `python3 server.py`
   - Health: `/api/health`
   - Env: `BOSFOR_HTTPS=1`; `BOSFOR_ADMIN_PASSWORD=<пароли нави қавии шахсӣ>`
4. URL-и `https://...onrender.com`-ро кушоед; `/admin.html` барои админ аст.
5. Аввал аз админ менюи **тестӣ** илова кунед; ин deployment-и тоза ба таври пешфарз менюи воқеӣ надорад.

## Муҳим барои амният ва маълумот

- **ТАНҲО ТЕСТ**. Render Free пас аз тақрибан 15 дақиқа бе истифода spin down мешавад.
- SQLite ва uploaded images дар Render Free ба диски муваққатӣ сабт мешаванд ва ҳангоми spin down, restart ва redeploy нест мешаванд.
- Фақат ном, рақам ва маълумоти сохтаи санҷишӣ истифода кунед; маълумоти воқеии меҳмононро ворид накунед.
- `BOSFOR_ADMIN_PASSWORD`-ро ба repo ё `render.yaml` нанависед. Онро танҳо дар Render environment/secret ворид кунед.
- Барои фаъолияти ресторан server бо storage-и доимӣ, secure backups ва deploy-и ҷудогона лозим аст.

## Mac: баъд аз сохтани репозитории холӣ

```bash
cd /PATH/TO/EXTRACTED/BOSFOR-Render-Free-TEST-Deploy

git init

git add .

git commit -m 'Prepare Bosfor temporary Render test'

git branch -M main

git remote add origin https://github.com/YOUR_USERNAME/bosfor-restaurant-test.git

git push -u origin main
```

Роҳи `YOUR_USERNAME`-ро ба номи ҳақиқии GitHub-и худ иваз кунед. Барои GitHub authentication эҳтимол browser login талаб мешавад.
