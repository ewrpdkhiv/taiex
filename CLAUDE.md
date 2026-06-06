# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 專案概述

台股加權指數（TAIEX）大跌日篩選工具。從 Yahoo Finance 或本地 CSV 檔案讀取 TAIEX 歷史資料，篩選單日跌幅達指定門檻的交易日，輸出文字報表與 CSV。

## 環境與套件管理

使用 `uv` 管理依賴與虛擬環境（Python ≥ 3.14）。

```bash
uv sync                              # 安裝依賴
uv run python taiex_big_drops.py     # 執行主程式
```

也可直接使用虛擬環境：

```bash
source .venv/bin/activate
python taiex_big_drops.py
```

## 執行方式

```bash
# 從 Yahoo Finance 自動下載（預設門檻 5%）
python taiex_big_drops.py

# 指定 CSV 來源（支援台灣證交所民國年格式）
python taiex_big_drops.py --csv data.csv

# 自訂門檻與起始日期
python taiex_big_drops.py --threshold 6 --start 2010-01-01

# 自訂輸出檔名
python taiex_big_drops.py --output my_results.csv
```

## 程式架構

核心邏輯全在 [taiex_big_drops.py](taiex_big_drops.py)，[main.py](main.py) 目前是占位符。

資料流：

1. `load_from_yfinance()` 或 `load_from_csv()` → DataFrame（含 Close 欄位）
2. `calculate_daily_returns()` → 新增 `change_pct` 欄位
3. `find_big_drops(threshold)` → 篩選 `change_pct <= -threshold` 的行
4. `format_report()` → 文字報表（按跌幅排序 + 年份統計）
5. `save_csv()` → 存成 CSV

## 關鍵實作細節

- **民國年解析**：CSV 日期欄位年份 < 200 時自動加 1911（例：`114/04/07` → `2025-04-07`）
- **欄位自動偵測**：同時支援證交所格式（`日期`、`收盤指數`）與標準格式（`Date`、`Close`）
- **已知事件標籤**：`KNOWN_EVENTS` dict 儲存歷史重大跌幅事件說明，在報表中自動標注
