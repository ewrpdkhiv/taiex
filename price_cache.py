"""共用的本地價格資料快取：讀取、合併、寫回 CSV。

讓 taiex_big_drops.py / dca.py 在重複執行時只需增量抓取新資料，
歷史資料保留在 cache/ 底下並隨 repo 一併 commit。
"""

from pathlib import Path

import pandas as pd

CACHE_DIR = Path(__file__).parent / "cache"

# 每次增量抓取時，從「快取最後日期 - OVERLAP_DAYS」開始重抓，
# 覆蓋掉可能延遲定案的收盤資料（例如假日、交易所延後更新）。
OVERLAP_DAYS = 7


def _merge_frames(cached: pd.DataFrame | None, fresh: pd.DataFrame) -> pd.DataFrame:
    """依 Date 欄位合併，重疊日期以 fresh 為準，回傳依日期排序後的結果。"""
    if cached is None or cached.empty:
        combined = fresh
    elif fresh.empty:
        combined = cached
    else:
        combined = pd.concat([cached, fresh], ignore_index=True)
    return (
        combined
        .drop_duplicates(subset="Date", keep="last")
        .sort_values("Date")
        .reset_index(drop=True)
    )


def read_cache(path: Path) -> pd.DataFrame | None:
    if not path.exists():
        return None
    df = pd.read_csv(path, parse_dates=["Date"])
    return df if not df.empty else None


def write_cache(path: Path, df: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)
