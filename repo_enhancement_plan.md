# Markdown Log Cleanup Enhancement Plan

## 目的

增加一個可重複使用的 Markdown 後處理功能，讓使用者可以直接修改既有的 OpenSearch 報告：

1. 移除所有指定 URL 的 log。
2. 預設支援移除 `/api/v1/esoterica/balance`。
3. 移除後重新編號剩餘 log。
4. 同步更新目錄連結、HTML anchor、Log heading 與摘要筆數。
5. 保留剩餘 log 的完整內容與原始順序。

本功能分成兩個層次：

- **產生前過濾**：查詢完成、Markdown render 之前，直接從 `RawScrapeResult.rows` 移除 balance log。
- **產生後清理**：讀取既有 Markdown，移除指定 log 並重新編號。

兩者應共用相同的精確 URL filter 規則，但不能只實作其中一種。

參考檔案：

- 原始報告：`output/qa_eso260720002_20260720T164902+0800.md`
- 清理後報告：`/Users/stephenhuang/Downloads/OVI2518_esoterica_bet_not_allow_log_20260720T164902+0800_no_balance_clean.md`

這次範例的轉換結果是 49 筆保留 20 筆，移除 29 筆 balance log。

## 產生 Markdown 前過濾 Balance Log

### 目的

讓使用者在查詢時直接排除不需要的 `/api/v1/esoterica/balance`，避免這些 log 進入 normalization、Markdown render、Google Sheets 寫入與後續輸出流程。

### 建議使用方式

在既有搜尋 CLI 增加可重複使用的 exclude option：

```bash
open-search \
  --env QA \
  --keyword eso260720002 \
  --exclude-url /api/v1/esoterica/balance
```

常用捷徑可以提供：

```bash
open-search \
  --env QA \
  --keyword eso260720002 \
  --exclude-balance
```

其中 `--exclude-balance` 等同於 `--exclude-url /api/v1/esoterica/balance`。

`--exclude-url` 可重複指定多個 URL；所有 exclude URL 都必須採完整相等比對，不使用 substring。

### 執行流程

現有流程大致為：

```text
OpenSearchScraper.run()
  -> RawScrapeResult.rows
  -> normalize_row()
  -> ScrapeResult.records
  -> render_markdown()
  -> write_markdown()
  -> Google Sheets
```

建議改為：

```text
OpenSearchScraper.run()
  -> RawScrapeResult.rows
  -> filter_rows_by_url()
  -> normalize_row()
  -> ScrapeResult.records
  -> render_markdown()
  -> write_markdown()
  -> Google Sheets
```

過濾必須發生在 `normalize_row()` 之前與 `ScrapeResult` 建立之前，確保：

- balance log 不會進入 Markdown。
- balance log 不會進入 Google Sheets。
- 剩餘 records 天然使用連續的 `1..N` 編號，不需要事後重新修正 anchor。
- 原始查詢擷取筆數仍可保留在診斷資訊中，但報告的實際輸出筆數應是過濾後數量。

### 建議程式結構

新增純函式，例如放在 `src/filtering.py`：

```python
from collections.abc import Iterable

from models import RawLogRow


def filter_rows_by_url(
    rows: Iterable[RawLogRow],
    *,
    excluded_urls: set[str],
) -> tuple[list[RawLogRow], dict[str, int]]:
    """Return rows whose exact URL is not excluded, plus removal counts."""
```

URL 取自 `RawLogRow.url`，比較前只做 `strip()`；`None` 或空 URL 必須保留並產生可追蹤的 warning，不可因 URL 缺失而誤刪。

CLI 應將 exclude 設定傳入 `run()`，而不是讓 `normalize_row()` 或 Markdown template 自己判斷。Template 只負責顯示已經決定要輸出的 records。

### 統計與摘要

產生前過濾時，建議在 `ScrapeResult` 或執行摘要新增：

```text
原始擷取筆數
排除筆數
實際輸出筆數
排除 URL
```

既有 `預期筆數` 可代表 Dashboard 查詢原始結果數；`實際擷取筆數` 建議明確改為 `實際輸出筆數`，避免使用者誤以為輸出的數量未經過濾。若為維持既有格式，至少要新增一行 `排除筆數`。

排除後為 0 筆時，仍應產生摘要 Markdown，並清楚顯示原始筆數與排除筆數；不要誤判成 OpenSearch 沒有查到資料。

### Google Sheets 行為

當使用者啟用 `--google-sheets` 且使用產生前過濾時，只能將過濾後的 records 寫入 Google Sheets。除非未來另提供明確選項，不能先寫入全部 records 再從 Sheet 刪除 balance rows。

### 產生前過濾測試

至少新增以下測試：

1. `RawLogRow.url` 等於 `/api/v1/esoterica/balance` 時會被排除。
2. `/api/v1/esoterica/balance/extra` 不會被誤排除。
3. `None`、空字串與其他 URL 會保留。
4. 排除後 records 的順序不變。
5. 排除後 Markdown 目錄與 heading 從 1 連續編號，不需要後處理。
6. `--exclude-url` 可重複指定多個 endpoint。
7. `--exclude-balance` 與完整 `--exclude-url` 行為一致。
8. Google Sheets writer 只收到過濾後 records。
9. dry-run 顯示排除設定，但不執行查詢或過濾副作用。
10. `--no-open-output` 仍然不開啟瀏覽器。

## 建議使用方式

採用明確的 CLI 子命令，避免誤修改原始查詢結果：

```bash
open-search clean-markdown \
  output/qa_eso260720002_20260720T164902+0800.md \
  --remove-url /api/v1/esoterica/balance
```

預設輸出新檔案，原始 Markdown 不覆寫：

```text
output/qa_eso260720002_20260720T164902+0800_no_balance_clean.md
```

建議選項：

```text
--remove-url URL       可重複指定多個 URL
--output PATH          指定輸出檔案
--in-place             明確要求覆寫原始檔案
--dry-run              只顯示將移除與保留的筆數，不寫檔
```

也可以提供常用捷徑，但捷徑應建立在同一個 generic cleanup implementation 上：

```bash
open-search clean-markdown report.md --remove-balance
```

`--remove-balance` 等同於 `--remove-url /api/v1/esoterica/balance`。

## 功能範圍

### 必須支援

- 讀取目前 `render_markdown()` 產生的 Markdown 格式。
- 依 log 的 URL 完整比對移除項目；不可使用模糊 substring 比對。
- 保留 URL 不在移除清單中的 log。
- 保留剩餘 log 的原始順序。
- 將目錄中的：
  - `| N | <a href="#log-N">...` 更新為新編號。
  - `href="#log-N"` 更新為新 anchor。
- 將每個 log 區塊的：
  - `<a id="log-N"></a>` 更新為新編號。
  - `## Log N: ...` 更新為新編號。
- 更新摘要中的：
  - `預期筆數`
  - `實際擷取筆數`
- 保留原始報告的執行時間、環境、關鍵字、KQL、時間範圍、index pattern、ID、警告與重複筆數等 metadata。
- 對已經清理過的檔案重複執行時，結果應穩定，不應再次改變內容或編號。

### 不在第一版範圍

- 不修改 OpenSearch 原始查詢結果。
- 不重新查詢 Dashboard。
- 不依賴 log 內容中的 `requestBody`、`responseBody` 或 operator data 判斷 URL。
- 不自動刪除原始 Markdown。
- 不自動開啟清理後 Markdown；如要開啟，沿用既有 `--open-output` 行為並提供 `--no-open-output`。

## Markdown 解析策略

不建議用單一 regex 直接全檔取代，因為 log body 內可能包含 `log-N`、HTML 或類似文字。建議以既有產生格式的結構解析：

1. 找出 `## Log 目錄` 到 `## 執行摘要` 之前的目錄區段。
2. 找出所有 log 區塊起點：`<a id="log-N"></a>`。
3. 每個 log 區塊的終點是下一個 anchor 或檔案結尾。
4. 從該區塊固定的摘要行讀取 URL：

   ```text
   - URL: `/api/v1/esoterica/balance`
   ```

5. URL 命中移除清單的區塊整段移除；其餘區塊依原始順序保留。
6. 為保留區塊建立舊編號到新編號的 mapping，例如：

   ```text
   1 -> 1
   2 -> 2
   3 -> removed
   5 -> 3
   6 -> 4
   ```

7. 使用 mapping 重建目錄與 log 區塊的 anchor／heading，不要對整份 Markdown 做無條件數字取代。
8. 以實際保留區塊數量更新摘要筆數；若原報告的預期筆數與實際筆數不同，兩者都應依照 cleanup 語意更新為保留筆數，並在設計文件中明確記錄此決策。

### URL 判斷細節

- 解析 `- URL: \`...\`` 的值後再比對。
- 比對前只做前後空白 trim。
- `/api/v1/esoterica/balance` 應命中；`/api/v1/esoterica/balance/extra` 不應因 substring 而誤命中。
- 可用 `--remove-url` 重複傳入多個精確 URL。
- 若區塊缺少 URL 行，視為無法分類，預設保留並加入 warning，不應靜默刪除。

## 建議程式結構

新增獨立模組，例如 `src/markdown_cleanup.py`：

```python
class MarkdownCleanupResult(BaseModel):
    source_path: Path
    output_path: Path
    original_count: int
    removed_count: int
    remaining_count: int
    removed_urls: dict[str, int]
    warnings: list[str]


def clean_markdown(
    content: str,
    *,
    remove_urls: set[str],
) -> tuple[str, MarkdownCleanupResult]: ...
```

建議將純文字轉換邏輯設計成不依賴檔案系統的 function，讓單元測試可以直接傳入 Markdown 字串；CLI 層只負責讀檔、決定輸出路徑與寫檔。

CLI parser 建議使用 subparser，保留既有搜尋指令完全不變：

```text
open-search clean-markdown INPUT [options]
```

既有 `open-search --env ... --keyword ...` 的 argument parsing、查詢、Google Sheets 與自動開啟行為不可受影響。

## 輸出檔命名與安全性

- 預設輸出檔名使用原始 stem 加上 `_clean`。
- 若指定 `--remove-balance`，可使用 `_no_balance_clean` 作為人類可讀的命名，但 generic `--remove-url` 建議統一使用 `_clean`。
- 若目標檔已存在，預設拒絕覆寫並提示使用者指定 `--output` 或 `--in-place`。
- `--in-place` 必須是明確選項，不能由預設行為觸發。
- 清理前先驗證檔案存在、是一般檔案且編碼為 UTF-8。
- 寫檔採暫存檔後 atomic replace，避免中途失敗破壞原始報告。
- 不把報告內容、request body 或 response body 寫入 log；錯誤訊息只顯示路徑與統計數字。

## 參考結果的相容性

參考清理檔相較原始檔還移除了 `## Log 目錄` 標題上的 OpenSearch discover link。第一版建議不要把這個行為當成必要規則：

- 預設保留既有 OpenSearch link，因為它仍可追溯原始查詢。
- 若未來需要讓清理檔不再連回原始查詢，另增明確選項，例如 `--remove-discover-link`。
- 這個選項不可和刪除 log、重新編號邏輯耦合。

## 測試計畫

### 單元測試

新增 `tests/test_markdown_cleanup.py`，至少涵蓋：

1. 移除單一 `/api/v1/esoterica/balance` log。
2. 移除多個 balance log，確認 1、2、5 會變成 1、2、3。
3. 目錄 anchor 與 heading 都重新編號。
4. URL 完整比對，避免 `/balance/extra` 被誤刪。
5. 多個 `--remove-url` 同時生效。
6. 保留剩餘 log 的原始順序與完整 body 內容。
7. 摘要 `預期筆數`、`實際擷取筆數` 更新為保留筆數。
8. 無 log 可移除時輸出內容保持穩定。
9. 已清理檔案重複清理具備 idempotency。
10. 缺少 URL 行的 log 預設保留並產生 warning。
11. 空檔、非報告 Markdown、缺少 anchor 或格式不完整時給出可理解錯誤。
12. 預設不覆寫原始檔；`--in-place` 才可覆寫。

### 整合測試

以兩份參考檔建立 fixture，確認：

- 原始 49 筆報告清理後保留 20 筆。
- 所有 `/api/v1/esoterica/balance` 不再出現在目錄或 log 區塊。
- 最後一筆為 `## Log 20` 且存在 `<a id="log-20"></a>`。
- `href="#log-1"` 到 `href="#log-20"` 都能對應到唯一 anchor。
- 非 balance 的 request、response、operator data 與 error 內容不被修改。
- 輸出可被預設瀏覽器開啟；開啟失敗不影響清理檔產生。

## 驗收標準

- 使用一條 CLI 指令可完成 balance log 清理。
- 使用既有搜尋 CLI 的 `--exclude-balance` 或 `--exclude-url` 時，可在 Markdown 產生前排除 log。
- 產生前過濾與產生後清理使用相同的 URL 精確比對規則。
- 清理後目錄、anchor、heading 編號連續且一致。
- 參考報告中的 49 -> 20 結果可重現。
- 原始檔預設保留。
- 既有搜尋 CLI 與 55 個既有測試不受影響，並新增 cleanup 測試全部通過。
- `ruff check .` 通過。
- README 補上 cleanup CLI 範例、輸出檔命名、`--in-place` 安全說明與 `--no-open-output` 行為。

## 實作順序

1. 抽出共用的 URL 精確比對與 exclusion 設定資料結構。
2. 實作產生前 `filter_rows_by_url()`，接在 scraper rows 與 `normalize_row()` 之間。
3. 新增搜尋 CLI 的 `--exclude-url`、`--exclude-balance` 與摘要統計。
4. 建立 Markdown fixture 與 cleanup parser 的資料結構。
5. 實作純函式產生後 cleanup、編號 mapping 與摘要更新。
6. 新增 CLI `clean-markdown` 子命令與安全輸出策略。
7. 加入產生前單元測試、產生後單元測試及兩份參考檔整合測試。
8. 更新 README 使用說明。
9. 執行 `pytest`、`ruff check .`，再以參考報告做手動 smoke test。
