# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 專案概述

台股加權指數（TAIEX）分析工具，部署為 **GitHub Pages 靜態網站**，資料由 GitHub Actions 每日自動更新。提供：

- 單日大跌／大漲日篩選（按跌幅% 與跌點排名）
- 空頭市場偵測（peak-to-trough ≥ 20%）
- 定期定額（DCA）回測模擬（含 XIRR、最大回撤、Calmar ratio）

## 環境與套件管理

使用 `uv` 管理依賴（Python ≥ 3.12，核心僅需 `pandas` + `yfinance`；`dev` 群組另含 `pytest`）。

```bash
uv sync                          # 安裝依賴
uv run python taiex_big_drops.py # CLI 模式
```

### 測試

```bash
uv run pytest                                          # 跑全部測試
uv run pytest tests/test_dca.py                        # 只跑單一檔案
uv run pytest tests/test_dca.py::TestXirr::test_zero_return  # 跑單一測試
```

測試只涵蓋不需要網路的純函式（`taiex_big_drops.py` 的日期解析／空頭偵測／統計函式、`dca.py` 的 `_xirr`／`_max_drawdown`／`_merge_extra_buys`，以及用合成價格測的 `run_yearly`）；`run_dca()`／`run_all()` 等會呼叫 yfinance 的函式沒有測試覆蓋。

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

| 輸出檔案    | 內容                                                                                                                                                                                                                         |
| ----------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `data.json` | 16 組排行（跌幅%、漲幅%、跌點、漲點 × 5y/10y/20y/all），各取前 10 名，跌幅類附 `recovery_days`（回升天數）、漲幅類附 `fallback_days`（回落天數：之後第一次收盤跌回大漲前收盤所需交易日數）；另含 `post_drop_stats`／`post_gain_stats`（單日大跌／大漲 ≥5% 後 5/20/60 交易日的平均報酬、中位數、勝率）與 `streaks`（連續上漲／下跌天數排行 top 10）；`foreign_sells_{5y,10y,20y,all}` / `foreign_buys_{5y,10y,20y,all}` 為外資單日賣超／買超金額前 10 名（買超附 `fallback_days`）（FinMind 資料，快取於 `cache/institutional/foreign_net.csv`，`foreign_net` 單位億元）；`foreign_monthly`（`foreign_monthly_net()`：外資每月買賣超合計與買超／賣超天數，首頁「外資月度」分頁的長條圖＋月份表）；`today`（`rank_latest_day()`：最新交易日漲跌幅／漲跌點在全時同方向的名次）與 `today_foreign`（`rank_latest_foreign()`：最新外資買賣超金額在全時賣超／買超排行的名次，另含 `streak` 連續買超／賣超天數與 `streak_days` 這幾天的日期／金額，首頁點天數可展開明細），顯示於首頁頂端摘要卡（`generate_static.py` 只傳 `periods={"all": None}`） |
| `dca.json`  | 5 個情境：`results_10y`、`results_5y`、`results_crash_10y`（截至 2025-04-09）、`results_crash_5y`、`results_covid`（自 2020-02-01）；另含 `dip_buy_comparison`（固定扣款 vs 大跌 ≥5% 加碼 2 倍的績效比較）；`yearly`（`run_yearly()`：近 10 個完整年度 + 今年 YTD，每年 1 月起獨立扣款 12 次、以年底收盤算 XIRR）                   |
| `bear.json` | 空頭週期列表                                                                                                                                                                                                                 |
| `ohlc.json` | OHLC + VIX 時序資料（K 線圖用）；另含 `events`（= `KNOWN_EVENTS`，完整說明，顯示於 tooltip）與 `event_short`（= `EVENT_SHORT_NAMES`，K 線事件帶上的短名稱；新增事件時兩個 dict 都要加，測試會檢查鍵一致）                                                                                                                                     |

每個函式（`generate_data` / `generate_dca` / `generate_bear`）獨立執行，其中一個失敗不影響其他；最終 `sys.exit(1)` 讓 GitHub Actions 能偵測到錯誤。

### 核心分析函式庫：[taiex_big_drops.py](taiex_big_drops.py)

所有分析邏輯的單一來源，`generate_static.py` 與 CLI 共用。

資料流：

1. `load_from_yfinance()` 或 `load_from_csv()` → DataFrame（含 `Date`、`Close`）
2. `calculate_daily_returns()` → 新增 `change_pct`、`change_pt` 欄位
3. `find_top_drops/gains()` / `find_top_point_drops/gains()` → 篩選極端交易日
4. `find_bear_markets()` → 掃描 peak-to-trough ≥ 20% 的空頭週期

另有 `load_ohlc_from_yfinance()`、`load_vix_from_yfinance()` 供 K 線圖用。

### DCA 模組：[dca.py](dca.py)

`run_all(monthly_amount, years, force_start, force_end)` 對 `TICKERS`（33 檔標的）逐一呼叫 `run_dca()`。`generate_static.py` 固定使用 `monthly_amount=3_000`。

`run_dip_buy_comparison()` 比較「固定扣款」與「大跌加碼」兩種策略：先用 `taiex_big_drops.find_big_drops()` 抓出台股加權指數單日跌幅 ≥ 門檻（預設 5%）的日期，於下一個交易日額外加碼 (倍數 -1) 倍的月扣款金額（預設 2 倍），再對每檔標的各跑一次 `run_dca()`（`extra_buys` 參數）與基準情境比較。加碼買點的合併邏輯抽成 `_merge_extra_buys()` 純函式，便於測試。

每個標的附有 `TICKER_TAGS`（`tw/us`、`etf/stock`、`leveraged` 等），前端用於篩選。

關鍵演算法：

- **XIRR**（`_xirr()`）：Newton-Raphson + Bisection 雙重求解，cashflow 流出為負值
- **最大回撤**（`_max_drawdown()`）：逐日重建持倉市值，追蹤 peak
- **股息再投入**：除息日次交易日以當日收盤價買入小數股；`run_dca()` 使用 `auto_adjust=False` 以取得未調整的原始股息資料（`stock.dividends`）

### 前端頁面：[docs/](docs/)

三個獨立 HTML 頁面，純靜態，無任何後端依賴：

| 頁面         | 資料來源                            | 主要功能              |
| ------------ | ----------------------------------- | --------------------- |
| `index.html` | `data/data.json`                    | 漲跌排行表 + K 線圖   |
| `dca.html`   | `data/dca.json`                     | DCA 回測比較表        |
| `bear.html`  | `data/bear.json` + `data/ohlc.json` | 空頭市場列表 + K 線圖 |

K 線圖使用 ECharts 5，PNG 匯出使用 html2canvas；兩者皆 vendored 至 `docs/vendor/`（非 CDN），供離線開啟。

三頁共用 `docs/theme.css`（色彩 token、導覽列、卡片、表格等共用元件，淺色／深色兩套）與 `docs/theme.js`（主題切換、存 localStorage；`chartTheme()` 從 CSS 變數讀出 ECharts 配色，切換主題時發出 `themechange` 事件讓圖表重繪）。新增顏色請加在 `theme.css` 的變數，不要在頁面或圖表 option 裡寫死；顏色只用 hex／rgba（html2canvas 不支援 `color-mix()`／`oklch()`）。

### 自動更新：[.github/workflows/update-data.yml](.github/workflows/update-data.yml)

每個工作日 UTC 07:00（台灣時間 15:00）觸發，另外每次 push 到 `main`（只改 `docs/data/**`、`cache/**` 的除外）也會跑一次；執行 `generate_static.py` 後 auto-commit `docs/data/*.json`。可手動從 Actions 頁面觸發（`workflow_dispatch`）。任何步驟失敗時，最後的 `Notify on failure` 步驟會自動建立（或在既有開放中的）GitHub Issue 留言通知，避免失敗被靜靜忽略。

## 關鍵實作細節

- **民國年解析**：CSV 日期年份 < 200 時自動加 1911（`_parse_roc_or_ad_date()`）
- **KNOWN_EVENTS**：`dict[str, str]` 儲存歷史重大事件說明（鍵為 `YYYY-MM-DD`），`generate_static.py` 的 `_df_to_records()` 自動標注
- **K 線事件帶**：`docs/kline-events.js`（兩頁共用）的 `addEventBand()` 在 K 線區與 VIX 區之間加一條事件帶（會改寫 option 的 grid 版面），短名稱色塊最多 3 排，依「點開的那天 > 當日漲跌幅」排位，放不下的只畫小圓點；K 線區只留淡虛線對位；縮放／拖動時由 `layoutEventLabels()` 重新排版
- **空頭演算法**：從 `search_from` 向前滾動高點，跌幅 ≥ threshold 確認空頭後找低點與恢復日；每輪從低點之後繼續以捕捉次級空頭
- **VIX 對齊**：K 線日期與 VIX 交易日不一定相同，以 `None` 填充（ECharts `connectNulls: false` 顯示斷點）
- **ohlc.json 壓縮格式**：為靜態資料檔中最大者，`dates` 存成相對 `date_epoch`（`1990-01-01`）的整數天數偏移，OHLC 四值取整數、VIX 取 1 位小數，較未壓縮格式縮小約 4 成；前端 `loadOhlc()` 載入後以 `offsetsToISODates()` 還原成 `YYYY-MM-DD` 字串再使用
