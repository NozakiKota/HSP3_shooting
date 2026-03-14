"""
Pattern Detector - 無駄な作業パターンの検出・自動化提案・ML的統計分析 (Feature #10)
"""
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from logger import ActivityRecord


# ==================================================================
# データクラス
# ==================================================================

@dataclass
class PatternInsight:
    kind: str          # "waste" | "automation"
    title: str
    description: str
    apps: list[str]
    total_sec: float


@dataclass
class WorkSession:
    """
    連続した操作ログを1つの作業セッションとして表したもの。
    セッション間のギャップが gap_minutes 以上の場合に分割される。
    """
    start: datetime
    end: datetime
    records: list[ActivityRecord] = field(default_factory=list)

    @property
    def duration_sec(self) -> float:
        return (self.end - self.start).total_seconds()

    @property
    def primary_app(self) -> str:
        """セッション内で最も長く使ったアプリ名"""
        app_times: dict[str, float] = defaultdict(float)
        for r in self.records:
            app_times[r.app_name] += r.duration_sec
        return max(app_times, key=lambda k: app_times[k]) if app_times else ""

    @property
    def focus_score(self) -> float:
        """
        集中度スコア (0〜100)。
        アプリの多様性が低い（＝少ないアプリに集中している）ほど高スコア。
        """
        if not self.records:
            return 0.0
        unique_apps = len({r.app_name for r in self.records})
        diversity = unique_apps / len(self.records)
        return round((1.0 - diversity) * 100, 1)


# ==================================================================
# ルールベースパターン検出 (既存機能)
# ==================================================================

def analyze(records: list[ActivityRecord]) -> list[PatternInsight]:
    """レコードリストを解析してインサイトを返す"""
    if not records:
        return []

    insights: list[PatternInsight] = []
    insights.extend(_detect_frequent_switches(records))
    insights.extend(_detect_long_sessions(records))
    insights.extend(_detect_repetitive_titles(records))
    insights.extend(_suggest_automation(records))
    return insights


def _detect_frequent_switches(records: list[ActivityRecord]) -> list[PatternInsight]:
    """短時間で同じアプリ間を行き来している場合を検出"""
    insights = []
    window = 10  # 直近N件を見る

    for i in range(len(records) - window):
        chunk = records[i:i + window]
        apps = [r.app_name for r in chunk]
        short_switches = sum(1 for r in chunk if r.duration_sec < 30)

        if short_switches >= 6:
            counter = Counter(apps)
            top_apps = [app for app, _ in counter.most_common(3)]
            total = sum(r.duration_sec for r in chunk)
            insights.append(PatternInsight(
                kind="waste",
                title="頻繁なアプリ切り替え",
                description=(
                    f"{window}操作中に{short_switches}回、30秒未満の短い操作が続いています。"
                    " マルチタスクによる集中力の分散が疑われます。"
                ),
                apps=top_apps,
                total_sec=round(total, 1),
            ))
            break  # 重複を避けるため最初の1件のみ

    return insights


def _detect_long_sessions(records: list[ActivityRecord]) -> list[PatternInsight]:
    """同一アプリへの長時間連続利用を検出"""
    insights = []
    app_totals: dict[str, float] = defaultdict(float)

    for r in records:
        app_totals[r.app_name] += r.duration_sec

    for app, total in app_totals.items():
        if total >= 3600:  # 1時間以上
            insights.append(PatternInsight(
                kind="waste",
                title=f"長時間の連続利用: {app}",
                description=(
                    f"{app} を合計 {total/3600:.1f} 時間使用しています。"
                    " 定期的な休憩や作業の分割を検討してください。"
                ),
                apps=[app],
                total_sec=round(total, 1),
            ))

    return insights


def _detect_repetitive_titles(records: list[ActivityRecord]) -> list[PatternInsight]:
    """同じウィンドウタイトルへの繰り返しアクセスを検出"""
    insights = []
    title_counts: Counter = Counter(r.window_title for r in records if r.window_title)

    for title, count in title_counts.most_common(5):
        if count >= 5 and title:
            apps = list({r.app_name for r in records if r.window_title == title})
            total = sum(r.duration_sec for r in records if r.window_title == title)
            insights.append(PatternInsight(
                kind="waste",
                title=f"繰り返しアクセス: {title[:40]}",
                description=(
                    f"同じ画面に {count} 回アクセスしています。"
                    " ブックマークやショートカットで素早くアクセスできるか確認してください。"
                ),
                apps=apps,
                total_sec=round(total, 1),
            ))

    return insights


def _suggest_automation(records: list[ActivityRecord]) -> list[PatternInsight]:
    """自動化できる作業を提案"""
    insights = []
    category_totals: dict[str, float] = defaultdict(float)

    for r in records:
        category_totals[r.category] += r.duration_sec

    # ファイル操作が多い場合
    if category_totals.get("file_manager", 0) >= 600:
        insights.append(PatternInsight(
            kind="automation",
            title="ファイル整理の自動化",
            description=(
                "ファイルマネージャーの使用時間が長いです。"
                " フォルダ整理・命名規則のスクリプト化や、"
                " ファイル監視による自動仕分けを検討してください。"
            ),
            apps=["explorer"],
            total_sec=round(category_totals["file_manager"], 1),
        ))

    # メール/コミュニケーションが多い場合
    comm_total = category_totals.get("communication", 0)
    if comm_total >= 3600:
        insights.append(PatternInsight(
            kind="automation",
            title="コミュニケーション対応の効率化",
            description=(
                f"コミュニケーションツールに {comm_total/3600:.1f} 時間使用しています。"
                " 通知の一括確認時間を設ける、定型文テンプレートを活用するなど"
                " 対応を効率化できます。"
            ),
            apps=["teams", "slack", "outlook"],
            total_sec=round(comm_total, 1),
        ))

    # ブラウザが多く開発ツールが少ない場合
    if (category_totals.get("browser", 0) >= 1800
            and category_totals.get("development", 0) < 600):
        insights.append(PatternInsight(
            kind="automation",
            title="情報収集の効率化",
            description=(
                "ブラウザ使用時間が長い割に開発作業時間が少ない傾向があります。"
                " RSS リーダーや AI 要約ツールで情報収集を効率化できます。"
            ),
            apps=["chrome", "edge", "firefox"],
            total_sec=round(category_totals["browser"], 1),
        ))

    return insights


# ==================================================================
# ML的統計分析 (Feature #10)
# ==================================================================

# カテゴリごとの生産性重み (0.0〜1.0)
_PRODUCTIVITY_WEIGHTS: dict[str, float] = {
    "development":   1.0,
    "terminal":      1.0,
    "office":        0.8,
    "meeting":       0.6,
    "communication": 0.4,
    "browser":       0.3,
    "file_manager":  0.3,
    "other":         0.2,
}


def detect_work_sessions(
    records: list[ActivityRecord],
    gap_minutes: int = 15,
) -> list[WorkSession]:
    """
    連続する操作ログを「作業セッション」にグループ化する。

    Args:
        records:     ActivityRecord のリスト（時系列順を想定）
        gap_minutes: この時間（分）以上の空白があれば別セッションとみなす

    Returns:
        WorkSession のリスト
    """
    if not records:
        return []

    sessions: list[WorkSession] = []
    session_records: list[ActivityRecord] = [records[0]]

    for prev, curr in zip(records, records[1:]):
        try:
            prev_start = datetime.strptime(prev.timestamp, "%Y-%m-%d %H:%M:%S")
            curr_start = datetime.strptime(curr.timestamp, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            session_records.append(curr)
            continue

        gap_sec = (curr_start - prev_start).total_seconds()
        if gap_sec > gap_minutes * 60:
            session = _finalize_session(session_records)
            if session:
                sessions.append(session)
            session_records = [curr]
        else:
            session_records.append(curr)

    # 最後のセッションを確定
    session = _finalize_session(session_records)
    if session:
        sessions.append(session)

    return sessions


def _finalize_session(records: list[ActivityRecord]) -> WorkSession | None:
    """レコードリストから WorkSession を生成する"""
    if not records:
        return None
    try:
        start = datetime.strptime(records[0].timestamp, "%Y-%m-%d %H:%M:%S")
        last = records[-1]
        last_start = datetime.strptime(last.timestamp, "%Y-%m-%d %H:%M:%S")
        end = last_start + timedelta(seconds=last.duration_sec)
        return WorkSession(start=start, end=end, records=list(records))
    except ValueError:
        return None


def score_productivity(records: list[ActivityRecord]) -> dict[int, float]:
    """
    時間帯別の生産性スコアを計算する。

    カテゴリごとの重みで加重平均を取り、0〜100 のスコアを返す。
    スコアが高いほど生産的な作業が多かったことを示す。

    Returns:
        {hour (0〜23): score (0.0〜100.0)} の辞書。記録がない時間帯はキーなし。
    """
    hour_total: dict[int, float] = defaultdict(float)
    hour_weighted: dict[int, float] = defaultdict(float)

    for r in records:
        try:
            hour = datetime.strptime(r.timestamp, "%Y-%m-%d %H:%M:%S").hour
        except ValueError:
            continue
        weight = _PRODUCTIVITY_WEIGHTS.get(r.category, 0.2)
        hour_total[hour] += r.duration_sec
        hour_weighted[hour] += r.duration_sec * weight

    return {
        hour: round(hour_weighted[hour] / hour_total[hour] * 100, 1)
        for hour in hour_total
        if hour_total[hour] > 0
    }


def detect_peak_hours(records: list[ActivityRecord], top_n: int = 3) -> list[int]:
    """
    最も生産性が高い時間帯を返す（上位 top_n 時間）。

    Returns:
        生産性スコアの高い順に並んだ時刻（0〜23）のリスト
    """
    scores = score_productivity(records)
    if not scores:
        return []
    return [h for h, _ in sorted(scores.items(), key=lambda x: -x[1])[:top_n]]


def calc_context_switch_cost(records: list[ActivityRecord]) -> dict[str, float]:
    """
    コンテキストスイッチのコストを推定する。

    「直前と異なるカテゴリへ切り替えた回数」と
    「切り替え直後の短時間操作（<30秒）の合計時間」を返す。

    Returns:
        {
            "switch_count": int,      # カテゴリをまたいだ切り替え回数
            "lost_sec": float,        # 切り替え直後の短時間操作の合計秒数
        }
    """
    switch_count = 0
    lost_sec = 0.0

    for i in range(1, len(records)):
        prev_cat = records[i - 1].category
        curr = records[i]
        if curr.category != prev_cat:
            switch_count += 1
            if curr.duration_sec < 30:
                lost_sec += curr.duration_sec

    return {
        "switch_count": float(switch_count),
        "lost_sec": round(lost_sec, 1),
    }
