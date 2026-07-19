# OpenSearch Scrape

從 OpenSearch Dashboard 查詢 QA 或 staging log，將動態表格完整擷取並輸出 Markdown；Google Sheets 完成授權後可選擇同步寫入。

## 安裝

需要 Python 3.11 以上版本。建議每個環境建立獨立的 virtual environment。

### Windows CMD

在 **命令提示字元（cmd.exe）** 執行：

```cmd
cd C:\Users\<你的帳號>\Workspace2\OpenSearch_Scrape
py -3.12 -m venv .venv
.venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
python -m pip install -e .
python -m playwright install chromium
copy .env.example .env
```

看到命令列前方出現 `(.venv)` 即代表虛擬環境已啟用。

### Windows PowerShell

```powershell
Set-Location C:\Users\<你的帳號>\Workspace2\OpenSearch_Scrape
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
python -m pip install -e .
python -m playwright install chromium
Copy-Item .env.example .env
```

如果 PowerShell 阻擋啟用腳本，可只對目前使用者執行一次：

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

### macOS

macOS 會先使用 `find` 自動尋找 `OpenSearch_Scrape` 專案目錄，再執行完整安裝流程：

```bash
PROJECT_DIR="$(find "$HOME" -type d -name "OpenSearch_Scrape" -print -quit)" && \
[ -n "$PROJECT_DIR" ] || {
  echo "錯誤：找不到 OpenSearch_Scrape 專案目錄"
  exit 1
}

cd "$PROJECT_DIR" && \
python3 -m venv .venv && \
source .venv/bin/activate && \
python -m pip install --upgrade pip && \
python -m pip install -r requirements-dev.txt && \
python -m pip install -e . && \
python -m playwright install chromium && \
[ -f .env ] || cp .env.example .env
```

`-print -quit` 會使用找到的第一個同名目錄；如果電腦上有多個專案副本，
建議改用明確的 `cd` 路徑。

完成 `.env` 設定後，CLI 不需要再帶帳號或密碼參數；執行時會自動載入
`OPENSEARCH_USERNAME` 與 `OPENSEARCH_PASSWORD` 並登入 OpenSearch。`.env` 已被
`.gitignore` 排除，請勿提交到 Git。

若 macOS 找不到 `python3`，請先安裝 Python 3.11+，例如從 [python.org](https://www.python.org/downloads/macos/) 安裝，或使用 Homebrew：

```bash
brew install python@3.12
```

### 只安裝正式執行依賴

不需要執行測試時，可使用：

```text
python -m pip install -r requirements.txt
python -m pip install -e .
python -m playwright install chromium
```

`requirements.txt` 是 runtime dependencies；`requirements-dev.txt` 會額外安裝 pytest、pytest-cov 與 ruff。

編輯 `.env`，填入本機 OpenSearch 帳號、密碼。`.env` 已被 `.gitignore` 排除，實際帳密不可寫入 Git。

## 執行

### Windows CMD

```cmd
open-search-scrape --environment QA --keyword groove
open-search-scrape --environment staging --keyword groove --keyword cs20260716071044
open-search-scrape --environment QA --keyword groove or cs20260716071044
open-search-scrape --environment QA --keyword groove and cs20260716071044
open-search-scrape --environment QA --keyword groove or cs20260716071044 --dry-run
open-search-scrape --environment QA --keyword groove --google-sheets
```

多行指令使用 `^`：

```cmd
open-search-scrape ^
  --environment QA ^
  --keyword casinoGate ^
  --max-records 50 ^
  --no-open-output
```

### Windows PowerShell

```powershell
open-search-scrape --environment QA --keyword groove
open-search-scrape --environment staging --keyword groove --keyword cs20260716071044
open-search-scrape --environment QA --keyword groove or cs20260716071044 --dry-run
```

多行指令使用反引號 `` ` ``：

```powershell
open-search-scrape `
  --environment QA `
  --keyword casinoGate `
  --max-records 50 `
  --no-open-output
```

### macOS Terminal

```bash
open-search-scrape --environment QA --keyword groove
open-search-scrape --environment staging --keyword groove --keyword cs20260716071044
open-search-scrape --environment QA --keyword A or B
open-search-scrape --environment QA --keyword groove and cs20260716071044 --dry-run
open-search-scrape --environment QA --keyword groove --google-sheets
```

多行指令使用反斜線 `\`：

```bash
open-search-scrape \
  --environment QA \
  --keyword casinoGate \
  --max-records 50 \
  --no-open-output
```

常用選項：

```text
--time-from now-1w
--time-to now
--max-records 100
--headless / --no-headless
--open-output / --no-open-output
--output-dir output
--clear-log / --clear_log
--google-sheets / --no-google-sheets
--dry-run
```

多個關鍵字可以直接在同一個 `--keyword` 後指定運算子：

```text
--keyword groove or cs20260716071044
--keyword groove and cs20260716071044
```

前者會查詢任一關鍵字，後者要求同一筆 log 同時包含兩個關鍵字。
若輸入尾端是不完整的 `or`／`and`，CLI 會自動移除尾端運算子；例如
`--keyword groove or` 會視為 `--keyword groove`，`--keyword A or B or` 會視為
`--keyword A or B`。若內容只有 `or`、`and` 或 `or or`，則會回報缺少有效關鍵字。
`--dry-run` 只輸出產生的 KQL 與 OpenSearch URL，不會登入、抓取或寫入資料。
搭配 `--google-sheets` 時，會用系統預設瀏覽器開啟目標 Google Sheet，
可單獨測試 Sheet 開啟功能：

```powershell
open-search-scrape --environment QA --keyword groove --google-sheets --dry-run
```

如果 OpenSearch 明確顯示查詢結果為 0 筆，程式會回報
`OpenSearch 找不到符合條件的 log` 並以結束碼 `1` 結束；不產生 Markdown、
不寫入或開啟 Google Sheet。

CLI 查詢預設使用 headless 模式，不會顯示 Playwright 瀏覽器視窗；產生 Markdown
後會自動以系統預設瀏覽器開啟。需要觀察瀏覽器操作時，再加上
`--no-headless`；不想自動開啟輸出檔時使用 `--no-open-output`。

### Google Sheets 開關

Google Sheets **預設關閉**。一般執行只會產生 Markdown，不會連線或寫入 Google Sheet：

```powershell
open-search-scrape --environment QA --keyword groove
```

單次執行需要同步寫入時，加上 `--google-sheets`：

```powershell
open-search-scrape --environment QA --keyword groove --google-sheets
```

Google Sheets 寫入成功後，程式會自動用系統預設瀏覽器開啟該 Sheet。

若 `.env` 已設定 `GOOGLE_SHEETS_ENABLED=true`，可以用 `--no-google-sheets` 暫停單次寫入：

```powershell
open-search-scrape --environment QA --keyword groove --no-google-sheets
```

永久預設值由 `.env` 控制：

```dotenv
# 預設關閉
GOOGLE_SHEETS_ENABLED=false
```

CLI 參數優先於 `.env`：`--google-sheets` 強制開啟，`--no-google-sheets` 強制關閉。OAuth、目標工作表與 token 設定請參考 [GOOGLE_SHEETS_SETUP_GUIDE.md](GOOGLE_SHEETS_SETUP_GUIDE.md)。

### 清空 output 資料夾

`--clear-log` 會刪除目前 output 資料夾內的所有檔案及子資料夾，但保留 output 資料夾本身。刪除內容無法復原。

Windows CMD／PowerShell：

```powershell
open-search-scrape --clear-log
```

macOS Terminal：

```bash
open-search-scrape --clear-log
```

CLI 也接受底線形式 `--clear_log`。若尚未安裝 console script，Windows 或 macOS 都可使用模組方式：

```text
python -m cli --clear-log
```

指定其他輸出資料夾：

```text
open-search-scrape --clear-log --output-dir output
```

和查詢參數一起使用時，會先清空再執行抓取：

```text
open-search-scrape --clear-log --environment QA --keyword groove
```

安全保護會拒絕清空專案目前目錄、使用者家目錄、磁碟根目錄及符號連結指向的目錄。

若 CLI 指令尚未加入 PATH，Windows CMD／PowerShell 與 macOS 都可以使用模組方式：

```text
python -m cli --environment QA --keyword groove --max-records 50
```

未提供 `--environment` 或 `--keyword` 時，CLI 會進入互動輸入模式。

`--max-records` 預設為 `50`，避免一次查詢及下載過多 log。需要更多資料時，請明確指定較大的數值；仍建議搭配較窄的時間範圍使用。

登入 selector 維護請參考 [LOGIN_SELECTORS.md](LOGIN_SELECTORS.md)，完整需求請參考 [REQUIREMENTS.md](REQUIREMENTS.md)。

## 測試

```text
python -m pytest
python -m ruff check .
```

單元測試不會登入 OpenSearch，也不會讀寫 Google Sheets。
