# OpenSearch Scrape 需求規格

本文件描述目前已實作且必須維持的行為。操作方式以 `README.md` 為準，Google Sheets 設定細節以 `GOOGLE_SHEETS_SETUP_GUIDE.md` 為準。

## 1. 專案目的

OpenSearch Scrape 使用瀏覽器登入 OpenSearch Dashboard，依環境及關鍵字查詢 log，處理動態載入與虛擬化表格，將結果標準化後輸出 Markdown。Google Sheets 是可選輸出，預設關閉。

核心要求：

1. 不修改或刪除 OpenSearch 上的資料。
2. Markdown 永遠先寫入；Google Sheets 失敗時仍保留 Markdown。
3. QA 與 staging 必須使用固定白名單 index pattern，不接受任意 ID。
4. 登入憑證、Google 憑證與 token 不得寫入程式碼、報告或 Git。
5. 預設限制最多擷取 50 筆，避免對 Dashboard 造成過大負載。

## 2. 執行環境

- Python 3.11 以上。
- Windows、macOS 均須支援。
- Playwright Chromium 是 OpenSearch 擷取必要 runtime。
- CLI 名稱：`open-search-scrape`。
- 未安裝 console script 時可使用 `python -m opensearch_scrape`。

必要依賴：

```text
playwright
pydantic
jinja2
tenacity
python-dotenv
gspread
google-auth
google-auth-oauthlib
```

## 3. OpenSearch 環境

預設 Dashboard URL：

```text
https://opensearch-dashboard-dev.newnextgen.site/app/data-explorer/discover
```

環境映射：

| CLI 輸入 | 標準名稱 | Pattern | Index Pattern ID |
| --- | --- | --- | --- |
| `QA`、`qa` | `QA` | `api-request-logs-qa-*` | `53ceb180-8f5d-11ef-b9c6-73a60e0d81fe` |
| `staging`、`STAGING`、`stg` | `staging` | `api-request-logs-stg-*` | `48481400-8c6a-11ef-b9c6-73a60e0d81fe` |

未知環境必須拒絕執行。頁面實際 index pattern 與目標環境不一致時必須停止擷取。

預設時間範圍：

```text
now-1w → now
```

報告優先顯示 Super Date Picker 的人類可讀文字；讀取不到時才顯示原始時間參數。

## 4. CLI 需求

基本使用：

```text
open-search-scrape --environment QA --keyword groove
open-search-scrape --environment staging --keyword groove --keyword cs123
open-search-scrape --environment QA --keyword groove or cs123
```

支援參數：

```text
--environment / -e
--keyword / -k
--operator or|and
--time-from
--time-to
--max-records
--output-dir
--headless / --no-headless
--open-output / --no-open-output
--google-sheets / --no-google-sheets
--clear-log / --clear_log
--dry-run
```

預設值：

| 項目 | 預設值 |
| --- | --- |
| `max_records` | `50` |
| `headless` | `true` |
| `open_output` | `true` |
| `time_from` | `now-1w` |
| `time_to` | `now` |
| `output_dir` | `output` |
| Google Sheets | 關閉 |

未提供 environment 或 keyword 時，CLI 可進入互動輸入。`--dry-run` 只輸出 KQL 與 Discover URL，不登入、不擷取、不寫入報告或 Sheet。

## 5. Keyword 與 KQL

### 5.1 基本規則

- 每個 keyword 以雙引號包住。
- 預設以 `or` 串接多個 keyword。
- `--operator and` 可要求所有 keyword 同時符合。
- 雙引號與反斜線必須正確跳脫。
- 控制字元必須拒絕。
- 同一 expression 不可混用 `or` 與 `and`。
- 第一層只支援 `A or B` 或 `A and B`，不提供括號或任意 KQL 編輯器。

範例：

```text
groove       → "groove"
123 or 456   → "123" or "456"
A and B      → "A" and "B"
```

### 5.2 尾端不完整運算子

解析前必須反覆移除尾端獨立的 `or`／`and`：

```text
groove or     → "groove"
groove and    → "groove"
A or B or     → "A" or "B"
A and B and   → "A" and "B"
A or or       → "A"
```

若移除後沒有 keyword，必須回報缺少有效關鍵字：

```text
or
and
or or
```

`operatorData`、`grand` 等字串中的 `or`／`and` 不是獨立運算子，不得拆分。

## 6. 登入與頁面定位

登入 selector 必須使用穩定屬性，詳細維護規則見 `LOGIN_SELECTORS.md`：

| 元素 | 優先 selector |
| --- | --- |
| Username | `[data-test-subj="user-name"]` |
| Password | `[data-test-subj="password"]` |
| Login | `[data-test-subj="submit"]` |

不可硬編碼動態登入 ID 或完整 `resizable-panel_*` ID。表格欄位應由表頭文字建立映射，不依賴固定 `td[n]`。

CAPTCHA、MFA、OTP 或其他安全驗證不得繞過；遇到時應停止並要求人工處理。

## 7. 擷取與動態載入

需要擷取的 Dashboard 欄位：

```text
requestBody
responseBody
url
operatorData
operatorResponse
operatorUrl
error
timeTaken
```

擷取流程：

1. 取得預期總筆數（若頁面可提供）。
2. 找出真正可捲動的結果容器。
3. 每輪立即保存可見資料列，避免虛擬化移除舊 DOM。
4. 使用穩定 record key 去重。
5. 捲動並等待新資料。
6. 達到總筆數、`max_records`、連續無新資料門檻或 timeout 時停止。
7. 回報預期筆數、實際筆數、重複筆數及未完成原因。

OpenSearch 預設最新資料在前。輸出前必須 reverse，讓 Markdown 與 Google Sheets 由較早到較晚排列；`max_records` 仍代表頁面最前面的 N 筆搜尋結果。

## 8. 資料解析

每筆標準化資料需保留：

- `recordKey`
- 擷取時間、環境、index pattern、KQL、時間範圍
- request time
- `username`、`gameCode`
- request／response body
- URL 與 decoded URL
- operator data／response／URL
- error、time taken
- parse warnings

結構化欄位處理順序：

1. 保留原始值。
2. 嘗試直接解析 JSON。
3. 必要時執行一次 URL percent decode。
4. 再嘗試解析 JSON。
5. JSON 成功時以 2 個空白縮排輸出。
6. 失敗時保留原文並記錄 warning。

不得把一般 URL 中的 `+` 無條件轉成空白。

空值呈現：

| 狀態 | 顯示 |
| --- | --- |
| 欄位不存在 | `N/A` |
| 空字串 | `(empty)` |
| JSON null | `null` |
| 解析失敗 | 原文＋warning |

## 9. Markdown 輸出

Markdown 是必要輸出。檔名格式：

```text
output/<environment>_<query-slug>_<timestamp>.md
```

報告摘要需包含：

- 執行時間與時區
- 狀態
- 環境及 index pattern
- keyword 與實際 KQL
- 查詢時間範圍
- 預期／實際／重複筆數
- warning 數量與未完成原因

每筆 log 需包含 Record Key、Request Time、Username、Game Code、Time Taken、URL、Operator URL、Error，以及 request/response/operator 的完整內容。

Markdown code fence 必須依內容中最長反引號序列動態調整，避免 log 內容破壞文件結構。成功寫入後預設使用系統瀏覽器開啟，可用 `--no-open-output` 關閉。

## 10. 清空 output

以下參數等價：

```text
--clear-log
--clear_log
```

行為要求：

- 單獨執行時，清空設定的 output 目錄後退出，不要求 environment 或 keyword。
- 與查詢參數一起執行時，先清空再擷取。
- 刪除 output 內的檔案與子目錄，但保留 output 目錄本身。
- 支援 Windows 與 macOS，不得依賴平台限定 shell 指令。
- 必須拒絕目前工作目錄、使用者家目錄、磁碟根目錄、非資料夾路徑與符號連結。
- CLI 必須回報實際 output 路徑及移除項目數。

## 11. Google Sheets

### 11.1 開關與執行順序

Google Sheets 預設關閉：

```text
GOOGLE_SHEETS_ENABLED=false
```

啟用 Google Sheets 時，成功寫入後必須以系統預設瀏覽器開啟目標 Sheet。
使用 `--google-sheets --dry-run` 時不得抓取或寫入資料，只開啟目標 Sheet，
供開啟功能測試。

`--google-sheets` 單次強制開啟，`--no-google-sheets` 單次強制關閉，CLI 參數優先於 `.env`。

執行順序：

1. 完成擷取與標準化。
2. 寫入 Markdown。
3. Google Sheets 啟用時才驗證設定與授權。
4. 寫入同一批標準化資料。
5. 分別回報新增、更新、跳過與失敗筆數。

### 11.2 授權

正式 writer 支援：

- Service Account。
- OAuth desktop client。

OAuth 第一次執行可開啟瀏覽器授權；之後讀取 `GOOGLE_TOKEN_FILE`。access token 過期時必須使用 refresh token 自動更新，不應每次要求登入。OAuth client secret、access token、refresh token 均不得提交 Git。

設定項目：

```text
GOOGLE_SHEETS_ENABLED
GOOGLE_SPREADSHEET_ID
GOOGLE_WORKSHEET_NAME
GOOGLE_AUTH_MODE=service-account|oauth
GOOGLE_CREDENTIALS_FILE
GOOGLE_TOKEN_FILE
GOOGLE_WRITE_MODE=upsert|append
GOOGLE_BATCH_SIZE
```

### 11.3 支援表頭

空白 Sheet 自動建立標準 21 欄表頭：

```text
recordKey, scrapedAt, environment, indexPatternName, indexPatternId, query, timeFrom, timeTo, username, gameCode, requestBody, responseBody, url, decodedUrl, operatorData, operatorResponse, operatorUrl, decodedOperatorUrl, error, timeTaken, parseWarnings
```

同時相容既有 9 欄格式：

```text
username, game code, requestBody, responseBody, url, operatorData, operatorResponse, operatorUrl, remark
```

9 欄格式將 record key 與抓取資訊放在 `remark`，並以其中的 record key upsert。其他表頭必須拒絕，避免覆蓋未知資料。

### 11.4 寫入規則

- 預設 `upsert`；既有 record key 更新，不存在才新增。
- `append` 必須由使用者明確設定。
- 批次大小可設定，預設 100。
- API 暫時錯誤採最多 3 次指數退避重試。
- 單一儲存格超過 50,000 字元時停止 Sheet 寫入，不得靜默截斷。
- Sheet 寫入失敗時保留 Markdown，CLI 回報失敗。

## 12. 設定與安全

本機 `.env` 至少包含：

```dotenv
OPENSEARCH_USERNAME=
OPENSEARCH_PASSWORD=
OPENSEARCH_DASHBOARD_URL=https://opensearch-dashboard-dev.newnextgen.site/app/data-explorer/discover
OPENSEARCH_HEADLESS=true
OPENSEARCH_SCROLL_WAIT_MS=1000
OPENSEARCH_NO_NEW_DATA_LIMIT=3
OPENSEARCH_TIMEOUT_SECONDS=300
OPENSEARCH_OUTPUT_DIR=output
GOOGLE_SHEETS_ENABLED=false
```

不得提交或記錄：

```text
.env
client_secret*.json
google-token*.json
google-service-account*.json
瀏覽器 cookie／session／profile
OpenSearch 或 Google 密碼及 Authorization header
```

Markdown 與 Sheet 可能包含使用者資料、token、URL 或營運資訊，均視為敏感資料。Google Sheet 不可設為公開連結存取。

## 13. 錯誤與狀態

必須明確處理：

- OpenSearch 憑證缺少或登入失敗。
- CAPTCHA／MFA／OTP。
- Dashboard timeout 或頁面結構改變。
- 未知環境、無效 keyword 或混合運算子。
- 找不到表格、表頭或捲動容器。
- OpenSearch 明確顯示結果為 0 筆時，回報 `OpenSearch 找不到符合條件的 log`，
  以結束碼 `1` 結束，且不得產生 Markdown、寫入 Google Sheets 或開啟 Google Sheet。
- 總筆數無法解析時，依實際擷取結果處理。
- 擷取筆數少於預期。
- JSON／URL decode warning。
- Markdown 寫入失敗。
- Google Sheets 未啟用、設定不完整、授權失敗、工作表不存在、表頭不相容或 API 失敗。
- 不安全的 clear-log 目標路徑。

部分擷取需標示 `partial` 並回傳非零結束碼。Google Sheets 寫入失敗時 Markdown 已保留，CLI 回傳失敗但不可刪除本機報告。

## 14. 驗收條件

1. `groove` 產生 KQL `"groove"`。
2. `123 or 456` 產生 KQL `"123" or "456"`。
3. 尾端 `or`／`and` 按第 5.2 節移除，只有運算子時拒絕。
4. QA、staging、stg 使用正確固定 index pattern。
5. 未提供 `--max-records` 時最多取得 50 筆。
6. 虛擬化表格可持續捲動、保存、去重，並在輸出前反轉為較早到較晚。
7. JSON、URL encoded、空值、非法內容及 code fence 均可安全輸出。
8. Markdown 檔名及摘要包含環境、查詢與執行時間。
9. Google Sheets 預設不連線；`--google-sheets` 才單次開啟。
10. OAuth token 過期可由 refresh token 自動更新。
11. 標準 21 欄與既有 9 欄 Sheet 均可 upsert，相同資料重送不產生重複列。
12. Sheet 失敗不刪除 Markdown。
13. `--clear-log` 與 `--clear_log` 在 Windows/macOS 均可用，且危險路徑會被拒絕。
14. `--dry-run` 不登入、不擷取、不寫入外部系統。
15. 單元測試不得真的登入 OpenSearch 或修改 Google Sheet；live integration 必須由使用者明確要求。

## 15. 必要測試案例

- 0、1、多筆與超過一個畫面的結果。
- 虛擬化捲動、重複列、慢速載入及 session 過期。
- QA／qa、staging／STAGING／stg 與未知環境。
- 單一 keyword、多 keyword、OR、AND、混用運算子及尾端運算子。
- `or`、`and`、`or or` 等無有效 keyword。
- JSON、URL encoded JSON、雙重編碼、非法 JSON、Unicode、換行及反引號。
- Markdown 空結果、部分成功、時間範圍與輸出順序。
- Google Sheets 關閉、OAuth refresh、21 欄、9 欄、upsert、append、表頭錯誤及儲存格過大。
- clear-log 空目錄、巢狀目錄、指定 output dir、單獨退出及危險路徑。
