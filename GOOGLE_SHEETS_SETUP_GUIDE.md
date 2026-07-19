# Google Sheets 設定指南

本 repo 的正式 `GoogleSheetsWriter` 支援 **Service Account** 與 **OAuth**。啟用後，CLI 會在產生 Markdown 的同一次執行中，將同一批 log 寫入 Google Sheet。

## 建議做法：Service Account

這是固定寫入同一份 Google Sheet、排程執行及無人值守執行最合適的方式。

準備項目：

1. 在 Google Cloud 專案啟用 Google Sheets API。
2. 建立 Service Account 並下載 JSON key。
3. 將目標 Google Sheet 分享給 Service Account email，權限設為「編輯者」。
4. 在目標試算表建立工作表，例如 `OpenSearch Logs`。
5. 將 JSON key 放在 repo 外或安全位置，不要提交至 Git。

`.env` 設定：

```dotenv
GOOGLE_SHEETS_ENABLED=true
GOOGLE_SPREADSHEET_ID=試算表_ID
GOOGLE_WORKSHEET_NAME=OpenSearch Logs
GOOGLE_AUTH_MODE=service-account
GOOGLE_CREDENTIALS_FILE=/path/to/google-service-account.json
GOOGLE_WRITE_MODE=upsert
GOOGLE_BATCH_SIZE=100
```

Spreadsheet ID 是網址 `/d/` 與 `/edit` 之間的內容：

```text
https://docs.google.com/spreadsheets/d/<SPREADSHEET_ID>/edit
```

執行：

```powershell
open-search --env QA --keyword groove --google-sheets
```

CLI 會先保留 Markdown，再寫入 Google Sheet。Sheet 寫入失敗不應造成 Markdown 遺失。

## Sheet 表頭

新工作表會使用以下 21 欄：

```text
recordKey, scrapedAt, environment, indexPatternName, indexPatternId, query, timeFrom, timeTo, username, gameCode, requestBody, responseBody, url, decodedUrl, operatorData, operatorResponse, operatorUrl, decodedOperatorUrl, error, timeTaken, parseWarnings
```

空白工作表會自動建立表頭。正式 writer 也相容目前既有 Sheet 的 9 欄格式：

```text
username, game code, requestBody, responseBody, url, operatorData, operatorResponse, operatorUrl, remark
```

9 欄格式會把 `recordKey`、抓取時間、request time、耗時與錯誤資訊保存到 `remark`，因此仍可使用 upsert。其他表頭格式會停止寫入，避免覆蓋錯誤資料。

`GOOGLE_WRITE_MODE`：

- `upsert`：以 `recordKey` 判斷；已存在就更新，不存在就新增。建議使用。
- `append`：每次都新增，可能產生重複資料。

單一儲存格上限為 50,000 字元。超過時會停止 Sheet 寫入並保留 Markdown。

## OAuth 設定

OAuth 適合以目前登入的 Google Workspace 使用者身分寫入 Sheet。`.env` 設定：

```dotenv
GOOGLE_SHEETS_ENABLED=true
GOOGLE_SPREADSHEET_ID=1Yi4CvzbecyTcD5-yeEU8d_8ds6qJElm_GutInG_p0gg
GOOGLE_WORKSHEET_NAME=工作表1
GOOGLE_AUTH_MODE=oauth
GOOGLE_CREDENTIALS_FILE=client_secret_733400045474-q2mnabr9jseeibv5c8oc2f099209ac55.apps.googleusercontent.com.json
GOOGLE_TOKEN_FILE=google-token.json
GOOGLE_WRITE_MODE=upsert
GOOGLE_BATCH_SIZE=100
```

第一次執行會開啟瀏覽器要求登入與授權，之後會讀取 `google-token.json`。access token 過期時，程式會自動使用 refresh token 更新，不需要再次操作瀏覽器。只有 refresh token 被撤銷、失效或 token 檔遺失時才需要重新授權。

### 查詢 OAuth consent screen 的位置

本專案使用的 Google Cloud project 是 `opensearch-log`。下次要確認 OAuth 應用程式狀態，直接開啟：

- [OAuth 目標對象（Audience）](https://console.cloud.google.com/auth/audience?project=opensearch-log)
- [OAuth 品牌（Branding）](https://console.cloud.google.com/auth/branding?project=opensearch-log)

在「目標對象」頁面確認：

- 使用者類型為 `內部（Internal）`。
- 這代表只有同一個 Google Workspace 組織內的帳號可以授權。
- Internal 應用程式不需要 Google OAuth 驗證，也不適用 `External + Testing` 常見的 7 天 refresh token 限制。

「品牌」頁面只用來查看應用程式名稱、Logo 及聯絡資訊；要確認發布狀態與使用者類型，請看「目標對象」頁面。

OAuth 使用以下檔案：

- `client_secret_*.json`：OAuth client 設定，初次授權及 refresh token 更新時使用。
- `google-token.json`：保存 access token 與 refresh token。
- `src/sheets.py`：正式 OAuth、token refresh 與 Sheet 寫入實作。

可在 [Google Cloud OAuth consent screen](https://console.cloud.google.com/auth/overview) 查看及調整應用程式的 Publishing status 與 User type。

若 OAuth consent screen 是 `External + Testing`，refresh token 可能在 7 天後失效。固定排程寫入建議使用 Service Account，或將 Workspace 應用設為合適的 Internal／正式狀態。

## 安全要求

下列檔案不得提交至 Git、貼到 Issue 或輸出到 log：

```text
.env
client_secret*.json
google-token*.json
google-service-account*.json
```

目前 `.gitignore` 已排除上述三類憑證檔；仍建議將正式憑證存放在 repo 外。

## 常見錯誤

- `Spreadsheet not found`：Spreadsheet ID 錯誤，或目前授權帳號／Service Account 沒有權限。
- `Worksheet not found`：`GOOGLE_WORKSHEET_NAME` 與工作表名稱不一致。
- 表頭不相容：將第一列改成支援的 21 欄或 9 欄格式，或改用專用工作表。
- OAuth token 失效：刪除本機 `google-token.json` 後重新執行，完成一次瀏覽器授權。
- 重複資料：確認 `GOOGLE_WRITE_MODE=upsert`；21 欄格式以第一欄、9 欄格式以 `remark` 中的 `recordKey` 判斷。

## 停用 Google Sheets

```dotenv
GOOGLE_SHEETS_ENABLED=false
```

也可以在單次執行使用：

```powershell
open-search --env QA --keyword groove --no-google-sheets
```
