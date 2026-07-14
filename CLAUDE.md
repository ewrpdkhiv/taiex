# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 專案概述

台股加權指數（TAIEX）分析工具，提供：

- 單日大跌／大漲日篩選
- 空頭市場偵測（peak-to-trough）
- 定期定額（DCA）回測模擬

有兩個入口：CLI 腳本（`taiex_big_drops.py`）與 Flask 網頁應用（`app.py`）。

## 環境與套件管理

使用 `uv` 管理依賴（Python ≥ 3.12）。

```bash
uv sync                          # 安裝依賴
uv run python taiex_big_drops.py # CLI 模式
uv run python app.py             # 啟動網頁應用（預設 port 5000）
```

## 執行方式

### CLI

```bash
# 從 Yahoo Finance 自動下載（預設門檻 5%）
python taiex_big_drops.py

# 指定 CSV 來源（支援台灣證交所民國年格式）
python taiex_big_drops.py --csv data.csv

# 自訂門檻與起始日期
python taiex_big_drops.py --threshold 6 --start 2010-01-01
```

### 網頁應用

```bash
python app.py   # 本機自動開啟瀏覽器
```

`Procfile` 中的 `web: uv run python app.py` 用於 Railway 部署。

## 程式架構

### 核心函式庫：[taiex_big_drops.py](taiex_big_drops.py)

所有分析邏輯的單一來源，供 CLI 與 `app.py` 共用。

資料流：

1. `load_from_yfinance()` 或 `load_from_csv()` → DataFrame（含 `Date`、`Close`）
2. `calculate_daily_returns()` → 新增 `change_pct`、`change_pt` 欄位
3. `find_top_drops/gains()` / `find_big_drops()` → 篩選極端交易日
4. `find_bear_markets()` → 掃描 peak-to-trough ≥ 20% 的空頭週期
5. `format_report()` / `save_csv()` → CLI 輸出

另有 `load_ohlc_from_yfinance()` 與 `load_vix_from_yfinance()` 供網頁圖表使用。

### Flask 網頁應用：[app.py](app.py)

三組相互獨立的執行緒鎖定快取（每小時背景刷新）：

| 快取變數      | 對應資料                                   | API 端點        |
| ------------- | ------------------------------------------ | --------------- |
| `_cache`      | 前 10 大跌／漲幅（%）與跌／漲點，各 4 時段 | `GET /api/data` |
| `_dca_cache`  | DCA 回測結果（5y/10y + 崩盤/COVID 情境）   | `GET /api/dca`  |
| `_bear_cache` | 空頭週期列表                               | `GET /api/bear` |
| `_ohlc_cache` | OHLC + VIX 時序資料（K 線圖用）            | `GET /api/ohlc` |

`POST /api/refresh` 可在前端觸發背景重新下載。

頁面路由：`/` → `index.html`、`/dca` → `dca.html`、`/bear` → `bear.html`（均在 [templates/](templates/)）。

### DCA 模組：[dca.py](dca.py)

`run_all(monthly_amount, years, force_start, force_end)` 對 `TICKERS` 中所有標的呼叫 `run_dca()`，回傳含以下指標的結果列表：

- 報酬率、XIRR（`_xirr()`，Newton-Raphson + Bisection 雙重求解）
- 最大回撤（`_max_drawdown()`）
- Calmar ratio

含股息再投入：除息日次交易日以當日收盤價買入小數股。

## 關鍵實作細節

- **民國年解析**：CSV 日期年份 < 200 時自動加 1911（`_parse_roc_or_ad_date()`）
- **欄位自動偵測**：同時支援證交所格式（`日期`、`收盤指數`）與標準格式（`Date`、`Close`）
- **KNOWN_EVENTS**：`dict[str, str]` 儲存歷史重大跌漲幅事件說明，報表與 API 均自動標注
- **空頭演算法**：從 `search_from` 向前滾動高點，一旦跌幅 ≥ threshold 確認空頭，再往後找低點與恢復日；每輪從低點之後繼續以捕捉次級空頭
- **VIX 欄位**：K 線圖日期對 VIX 可能無對應交易日，以 `None` 填充而非插值
