"""作業ログ（CSV）の保存・読み込み・編集と、振り返り用の集計

CSV は1行1記録で [日時, 作業内容, 実施時間] （例: 2026-10-14 09:00:00,制作,25分）。
"""

import csv
from dataclasses import dataclass
from datetime import date, datetime, timedelta
import os
from pathlib import Path
from typing import NamedTuple

import pandas as pd

DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S"
MAX_RECORD_MINUTES = 24 * 60


class Period(NamedTuple):
    """振り返りの期間"""

    tab_label: str  # 切り替えボタンの表示
    days: int
    title: str  # 合計時間の見出し


PERIODS = {
    "week": Period("週", 7, "直近7日"),
    "month": Period("月", 30, "直近30日"),
    "year": Period("年", 365, "直近12か月"),
}


@dataclass
class PeriodSummary:
    """振り返り画面に表示する、ある期間の集計結果"""

    title: str
    labels: list[str]  # グラフの横軸（日付 or 月）
    values: list[float]  # グラフの値（unit 単位）
    unit: str  # "分" or "時間"
    total_minutes: int
    active_days: int  # 記録した日数
    span_days: int  # 期間の日数
    by_task: pd.Series  # 作業内容ごとの合計（分・多い順）


# ==========================================
# 保存・読み込み
# ==========================================
def append_record_to_csv(csv_path: Path, now_str: str, task: str, duration_mins: int) -> None:
    """ローカルCSVに1行追記する(newline=""で空行を防止、utf-8-sigでExcel互換)"""
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with open(csv_path, mode="a", newline="", encoding="utf-8-sig") as f:
        csv.writer(f).writerow([now_str, task, f"{duration_mins}分"])


def parse_minutes(value) -> int:
    """「25分」「25」などの文字列から分数(int)を取り出す。取り出せなければ0"""
    digits = "".join(ch for ch in str(value) if ch.isdigit())
    return int(digits) if digits else 0


def empty_records() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "日時": pd.Series(dtype="datetime64[ns]"),
            "作業内容": pd.Series(dtype=str),
            "分": pd.Series(dtype=int),
        }
    )


def load_records(csv_path: Path) -> pd.DataFrame:
    """作業ログCSVを [日時, 作業内容, 分] の DataFrame として読み込む（ファイルが無い・空なら0件）"""
    if not csv_path.exists() or csv_path.stat().st_size == 0:
        return empty_records()
    try:
        df = pd.read_csv(
            csv_path,
            encoding="utf-8-sig",
            header=None,
            engine="python",
            on_bad_lines="skip",
        )
    except pd.errors.EmptyDataError:  # BOM や空行しかない場合
        return empty_records()
    if df.shape[1] < 3:
        raise ValueError(
            "CSVのデータ構造が正しくありません。[日時, 作業内容, 実施時間] の形式か確認してください。"
        )

    records = pd.DataFrame(
        {
            "日時": pd.to_datetime(df.iloc[:, 0], format=DATETIME_FORMAT, errors="coerce"),
            "作業内容": df.iloc[:, 1].astype(str).str.strip(),
            "分": df.iloc[:, 2].map(parse_minutes),
        }
    )
    return records.dropna(subset=["日時"])


def validate_record(task: str, minutes_text: str) -> tuple[str, int] | str:
    """入力された作業内容と時間（分）を確かめ、(作業内容, 分) を返す。正しくなければエラーメッセージを返す"""
    task = task.strip()
    minutes_text = minutes_text.strip()
    if not task:
        return "やったことを入力してください"
    if not minutes_text.isdigit() or not 1 <= int(minutes_text) <= MAX_RECORD_MINUTES:
        return f"時間は 1〜{MAX_RECORD_MINUTES} の数字で入力してください"
    return task, int(minutes_text)


# ==========================================
# 記録の一覧・修正・削除（CSV の行をそのまま扱う）
# ==========================================
@dataclass
class Record:
    """CSV の1行。row_index は CSV の何行目か（修正・削除のときに使う）"""

    row_index: int
    recorded_at: datetime
    task: str
    minutes: int


def list_records(csv_path: Path) -> list[Record]:
    """読み取れる記録を新しい順に返す（日時が読めない行は飛ばす）"""
    result = []
    for i, row in enumerate(read_rows(csv_path)):
        if len(row) < 3:
            continue
        try:
            when = datetime.strptime(row[0], DATETIME_FORMAT)
        except ValueError:
            continue
        result.append(Record(i, when, row[1].strip(), parse_minutes(row[2])))
    return sorted(result, key=lambda r: (r.recorded_at, r.row_index), reverse=True)


def update_record(csv_path: Path, row_index: int, task: str, minutes: int) -> None:
    rows = read_rows(csv_path)
    rows[row_index][1:3] = [task, f"{minutes}分"]
    write_rows(csv_path, rows)


def delete_record(csv_path: Path, row_index: int) -> None:
    rows = read_rows(csv_path)
    del rows[row_index]
    write_rows(csv_path, rows)


def read_rows(csv_path: Path) -> list[list[str]]:
    """CSV の行をそのまま読む（日時が読めない行も含む。修正・削除・同期で使う）"""
    if not csv_path.exists():
        return []
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        return [row for row in csv.reader(f)]


def write_rows(csv_path: Path, rows: list[list[str]]) -> None:
    """CSV をまるごと書き直す"""
    # 書き込み途中でアプリが終了しても作業ログが壊れないよう、一時ファイルから置き換える
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = csv_path.with_suffix(".tmp")
    with open(tmp_path, "w", newline="", encoding="utf-8-sig") as f:
        csv.writer(f).writerows(rows)
    os.replace(tmp_path, csv_path)


# ==========================================
# 集計
# ==========================================
def recent_tasks(records: pd.DataFrame, limit: int = 5) -> list[str]:
    """最近やった作業内容を、新しい順に重複なしで返す（記録画面の候補に使う）"""
    tasks = records.sort_values("日時", ascending=False)["作業内容"]
    return [task for task in tasks.drop_duplicates() if task][:limit]


def today_minutes(records: pd.DataFrame, today: datetime | None = None) -> int:
    today_date = (today or datetime.now()).date()
    return int(records.loc[records["日時"].dt.date == today_date, "分"].sum())


def streak_days(records: pd.DataFrame, today: datetime | None = None) -> int:
    """何日続けて記録しているか（今日まだ記録していなくても、昨日まで続いていれば数える）"""
    today_date = (today or datetime.now()).date()
    days = set(records.loc[records["分"] > 0, "日時"].dt.date)
    day = today_date if today_date in days else today_date - timedelta(days=1)
    streak = 0
    while day in days:
        streak += 1
        day -= timedelta(days=1)
    return streak
def summarize_by_task(records: pd.DataFrame) -> pd.Series:
    summary = records.groupby("作業内容")["分"].sum()
    return summary[summary > 0].sort_values(ascending=False)


def summarize_by_day(records: pd.DataFrame, days: int = 7, today: datetime | None = None) -> pd.Series:
    """直近 days 日分の日別合計（記録がない日も0分として含める）"""
    today_date = (today or datetime.now()).date()
    index = pd.date_range(today_date - timedelta(days=days - 1), today_date).date
    daily = records.groupby(records["日時"].dt.date)["分"].sum()
    return daily.reindex(index, fill_value=0)


def summarize_period(records: pd.DataFrame, period: str, today: datetime | None = None) -> PeriodSummary:
    """振り返りの期間（"week" / "month" / "year"）ごとの集計

    week は直近7日・month は直近30日を日別（分）で、year は直近12か月を月別（時間）で返す。
    """
    today_date = (today or datetime.now()).date()
    if period == "year":
        months = pd.period_range(end=pd.Period(today_date, freq="M"), periods=12, freq="M")
        start = months[0].start_time.date()
    else:
        start = today_date - timedelta(days=PERIODS[period].days - 1)

    in_range = _records_between(records, start, today_date)
    daily = summarize_by_day(
        in_range, days=(today_date - start).days + 1, today=datetime.combine(today_date, datetime.min.time())
    )

    if period == "year":
        monthly = in_range.groupby(in_range["日時"].dt.to_period("M"))["分"].sum().reindex(months, fill_value=0)
        labels = [f"{p.month}月" for p in months]
        values = [round(mins / 60, 1) for mins in monthly.values]
        unit = "時間"
    else:
        labels = [f"{d.month}/{d.day}" for d in daily.index]
        values = [int(mins) for mins in daily.values]
        unit = "分"

    return PeriodSummary(
        title=PERIODS[period].title,
        labels=labels,
        values=values,
        unit=unit,
        total_minutes=int(in_range["分"].sum()),
        active_days=int((daily > 0).sum()),
        span_days=len(daily),
        by_task=summarize_by_task(in_range),
    )


def _records_between(records: pd.DataFrame, start: date, end: date) -> pd.DataFrame:
    """start 〜 end（両端を含む）の日の記録だけを取り出す"""
    dates = records["日時"].dt.date
    return records[(dates >= start) & (dates <= end)]


def format_hours_mins(total_mins: int) -> str:
    """「1時間 20分」の形にする（1時間未満は「41分」、ちょうどの時間は「2時間」）"""
    hours, mins = divmod(int(total_mins), 60)
    if hours == 0:
        return f"{mins}分"
    return f"{hours}時間" if mins == 0 else f"{hours}時間 {mins}分"
