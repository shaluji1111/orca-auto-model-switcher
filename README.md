# 🔄 Orca Smart Model Switcher & Auto-Failover Guardian

Ek multi-model orchestration tool jo Orca IDE ke andar aapke AI models (**Anthropic Claude, OpenAI Codex GPT-6, Google Antigravity Gemini, aur SpaceXAI Grok**) ka token quota monitor karta hai, task ke hisaab se best model suggest karta hai, aur tokens khatam hone par backup model par switch karne me madad karta hai.

> Security audit ke baad ka version. Kya-kya badla, ye [CHANGES.md](CHANGES.md) me hai.

## 🚀 Ye System Kya Karta Hai?

### 🔴 Auto-Failover jab tokens khatam ho jayein
- Agar kisi worktree me agent **usage limit / rate limit** ki wajah se ruk jata hai, Guardian sabse zyada free quota wala backup model dhoondhta hai.
- **Switch karne se pehle aapse Yes/No poochta hai** aur batata hai ki aapka task kis company (provider) ko bheja jayega.
- Naya agent **usi worktree me** start hota hai, original task ke saath, aur use bola jata hai ki pehle `git status` / `git diff` dekh kar wahin se aage badhe.
- Ek switch ke baad 10 minute ka cooldown, aur ek baar me sirf ek switch.
- Sirf quota khatam hone par (jab koi agent fail nahi hua) Guardian **sirf notification** deta hai, koi agent launch nahi karta.

### 🎯 Smart "Best Model" Task Matcher
- Task likhein, router keywords (poore words) aur live quota dekh kar best model batata hai.
- Agar Orca se quota data nahi milta, toh numbers "Unknown" dikhte hain, "100% free" nahi, aur auto-launch nahi hota.

### 📊 Live Token Health Dashboard
- Har provider ka session % used, status, aur reset countdown.

### ⚡ Fast Manual Switcher
- Menu se kisi bhi model par switch: Codex (GPT-6.1 Sol / GPT-6 Astra), Claude (Sonnet / Opus / Haiku 5.5), Antigravity (Gemini 3.8 Flash), Grok 4.7.

## 📁 Files

| File | Kaam |
|---|---|
| `1_Check_Model_Tokens.bat` | Live token quota aur reset countdown dashboard. |
| `2_Recommend_Best_Model.bat` | Task likhein, best model dekhein, chahein toh usi waqt launch karein. |
| `3_Switch_Active_Model.bat` | Menu se kisi bhi model par turant switch. |
| `4_Run_Auto_Failover_Guardian.bat` | Guardian ko is console window me chalata hai (Ctrl+C se band). |
| `5_Enable_Guardian_Auto_Start.bat` | Guardian ko har Windows login par background me chalane ke liye. |
| `6_Disable_Guardian_Auto_Start.bat` | Auto-start hatata hai aur sirf Guardian process band karta hai. |
| `orca_model_router.py` | Core Python engine jo `orca` CLI se baat karta hai. |

### Auto-start kaise kaam karta hai (5 / 6)
- Ye **Task Scheduler use nahi karta.** Ye `%LOCALAPPDATA%\OrcaSmartRouter\` me script ki **local copy** rakhta hai aur aapke **Windows Startup folder** me `Orca Smart Router Guardian.lnk` shortcut banata hai, jo `pythonw.exe` se Guardian chalata hai (koi window nahi dikhti).
- Local copy isliye, taaki agar ye folder Google Drive / OneDrive se sync hota hai, toh folder me koi bhi badlaav login par apne aap na chale. Script update karne ke baad `5_...bat` dobara chalayein.
- Installer purane version ka `Orca_Auto_Failover_Guardian.lnk` shortcut bhi hata deta hai.
- Hatane ke liye `6_...bat`, ya manually Startup folder (`Win+R` → `shell:startup`) se shortcut delete karein.

## 💻 CLI Commands

```bash
# 1. Live status check
python orca_model_router.py status

# 2. Task ke liye best model (task na dein toh poochega)
python orca_model_router.py best "Fix react state re-render bug and optimize query"
python orca_model_router.py best "Build large database schema" --launch
python orca_model_router.py best --interactive

# 3. Direct switch (worktree: jis worktree me aap ho, warna list se chunein, ya --worktree dein)
python orca_model_router.py switch codex --model gpt-6.1-sol
python orca_model_router.py switch claude --model opus --worktree name:"My Task"

# 4. Guardian (default: switch se pehle poochta hai)
python orca_model_router.py guard
python orca_model_router.py guard --allow claude,codex      # sirf in providers par switch
python orca_model_router.py guard --auto                    # bina pooche switch (task text apne aap backup ko jayega)
python orca_model_router.py guard --interval 15 --threshold 95 --cooldown 600

# 5. Auto-start on / off (Windows), same guard options ke saath
python orca_model_router.py install-autostart --allow claude,codex
python orca_model_router.py uninstall-autostart
```

| Option | Default | Matlab |
|---|---|---|
| `--threshold` | 95 | Session % used jis par provider "exhausted" mana jata hai. Dashboard, recommender aur Guardian sab yahi use karte hain. |
| `--interval` | 15 | Guardian kitne seconds me check karta hai. |
| `--cooldown` | 600 | Do automatic switches ke beech kam se kam itne seconds. |
| `--allow` | sab | Guardian kin providers par switch kar sakta hai. Company code ke liye isse limit karein. |
| `--auto` | off | Bina pooche switch. Isse on karne ka matlab hai task text bina confirmation ke doosri company ko jayega. |
| `--worktree` | current | (`switch` / `best`) Kis Orca worktree me launch karein: id, ya `name:<naam>`, `branch:<branch>`, `path:<path>`. `.bat` se chalane par list se chun sakte hain. |

## 🔒 Privacy & Logs
- Log: `%LOCALAPPDATA%\OrcaSmartRouter\failover_history.log` (sync hone wale folder me nahi). 1 MB ke baad rotate hota hai.
- Prompts / task text **log nahi hote**, sirf unki length.
- Is folder ko share karte waqt `failover_history.log` aur `__pycache__\` share na karein.

## ⚙️ Requirements
- Windows, Python 3.8+ (python.org wala, taaki `pythonw.exe` mile), aur Orca IDE jiska `orca.exe` PATH par ho.
- Agar `orca.exe` PATH par nahi hai, `ORCA_CLI_PATH` environment variable me uska poora path set karein.

## 🧠 Model Suitability Guide

| Model | Provider | Best For |
|---|---|---|
| GPT-6.1 Sol | OpenAI Codex | Fullstack coding, bug fixing, APIs, database |
| GPT-6 Astra | OpenAI Codex | Frontier reasoning, tough mathematical logic |
| Claude Sonnet 5.5 | Anthropic | Clean code, refactoring, routine everyday dev |
| Claude Opus 5.5 | Anthropic | Complex system architecture, high-stakes design |
| Claude Haiku 5.5 | Anthropic | Ultra-fast simple edits, JSON formatting |
| Gemini 3.8 Flash | Antigravity | 1M+ massive context, entire repo audit, file search |
| Grok 4.7 | SpaceXAI | Live internet search, social media & competitor ads |

Live quota ke liye `1_Check_Model_Tokens.bat` chalayein. Is table me koi % nahi hai, kyunki wo hamesha badalta rehta hai.
