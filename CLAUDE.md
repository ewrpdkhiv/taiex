# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 專案概述

台股加權指數（TAIEX）分析工具，部署為 **GitHub Pages 靜態網站**，資料由 GitHub Actions 每日自動更新。提供：

- 單日大跌／大漲日篩選（按跌幅% 與跌點排名）
- 空頭市場偵測（peak-to-trough ≥ 20%）
- 定期定額（DCA）回測模擬（含 XIRR、最大回撤、Calmar ratio）

## 環境與套件管理

使用 `uv` 管理依賴（Python ≥ 3.12，僅需 `pandas` + `yfinance`）。

```bash
uv sync                          # 安裝依賴
uv run python taiex_big_drops.py # CLI 模式
```

## 本機開發

```bash
# 1. 產生靜態資料 JSON（約需 5～10 分鐘，連線 Yahoo Finance）
uv run python scripts/generate_static.py

# 2. 在 docs/ 啟動本地 HTTP server（不能直接用 file:// 開啟，fetch() 會被封鎖）
cd docs && python -m http.server 8080
# 開啟 http://localhost:8080
```

### CLI 工具

```bash
# 從 Yahoo Finance 下載，預設門檻 5%
uv run python taiex_big_drops.py

# 指定 CSV 來源（支援台灣證交所民國年格式）
uv run python taiex_big_drops.py --csv data.csv --threshold 6 --start 2010-01-01
```

## 程式架構

### 靜態資料產生：[scripts/generate_static.py](scripts/generate_static.py)

唯一的「後端」入口，輸出四個 JSON 至 `docs/data/`：

| 輸出檔案    | 內容                                       |
| ----------- | ------------------------------------------ |
| `data.json` | 前 10 大跌／漲幅（%）與跌／漲點，各 4 時段 |
| `dca.json`  | DCA 回測結果（5y/10y + 崩盤/COVID 情境）   |
| `bear.json` | 空頭週期列表                               |
| `ohlc.json` | OHLC + VIX 時序資料（K 線圖用）            |

每個函式（`generate_data` / `generate_dca` / `generate_bear`）獨立執行，其中一個失敗不影響其他；最終 `sys.exit(1)` 讓 GitHub Actions 能偵測到錯誤。

### 核心分析函式庫：[taiex_big_drops.py](taiex_big_drops.py)

所有分析邏輯的單一來源，`generate_static.py` 與 CLI 共用。

資料流：

1. `load_from_yfinance()` 或 `load_from_csv()` → DataFrame（含 `Date`、`Close`）
2. `calculate_daily_returns()` → 新增 `change_pct`、`change_pt` 欄位
3. `find_top_drops/gains()` / `find_top_point_drops/gains()` → 篩選極端交易日
4. `find_bear_markets()` → 掃描 peak-to-trough ≥ 20% 的空頭週期

另有 `load_ohlc_from_yfinance()` 與 `load_vix_from_yfinance()` 供 K 線圖用。

### DCA 模組：[dca.py](dca.py)

`run_all(monthly_amount, years, force_start, force_end)` 對 `TICKERS`（33 檔標的）逐一呼叫 `run_dca()`。`generate_static.py` 固定使用 `monthly_amount=3_000`。

關鍵演算法：

- **XIRR**（`_xirr()`）：Newton-Raphson + Bisection 雙重求解，cashflow 流出為負值
- **最大回撤**（`_max_drawdown()`）：逐日重建持倉市值，追蹤 peak
- **股息再投入**：除息日次交易日以當日收盤價買入小數股

### 前端頁面：[docs/](docs/)

三個獨立 HTML 頁面，純靜態，無任何後端依賴：

| 頁面         | 資料來源                            | 主要功能              |
| ------------ | ----------------------------------- | --------------------- |
| `index.html` | `data/data.json`                    | 漲跌排行表 + K 線圖   |
| `dca.html`   | `data/dca.json`                     | DCA 回測比較表        |
| `bear.html`  | `data/bear.json` + `data/ohlc.json` | 空頭市場列表 + K 線圖 |

K 線圖使用 ECharts 5（CDN），PNG 匯出使用 html2canvas（CDN）。

### 自動更新：[.github/workflows/update-data.yml](.github/workflows/update-data.yml)

每個工作日 UTC 07:00（台灣時間 15:00）觸發，執行 `generate_static.py` 後 auto-commit `docs/data/*.json`。可手動從 Actions 頁面觸發（`workflow_dispatch`）。

## 關鍵實作細節

- **民國年解析**：CSV 日期年份 < 200 時自動加 1911（`_parse_roc_or_ad_date()`）
- **KNOWN_EVENTS**：`dict[str, str]` 儲存歷史重大事件說明（鍵為 `YYYY-MM-DD`），`generate_static.py` 的 `_df_to_records()` 自動標注
- **空頭演算法**：從 `search_from` 向前滾動高點，跌幅 ≥ threshold 確認空頭後找低點與恢復日；每輪從低點之後繼續以捕捉次級空頭
- **VIX 對齊**：K 線日期與 VIX 交易日不一定相同，以 `None` 填充（ECharts `connectNulls: false` 顯示斷點）
- **ohlc.json 大小**：約 1～2 MB（含 1990 年至今逾 9,000 個交易日），為最大的靜態資料檔
