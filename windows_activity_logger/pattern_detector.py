"""
Pattern Detector - 無駄な作業パターンの検出と自動化提案
"""
from collections import Counter, defaultdict
from dataclasses import dataclass

from logger import ActivityRecord


@dataclass
class PatternInsight:
    kind: str          # "waste" | "automation"
    title: str
    description: str
    apps: list[str]
    total_sec: float


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


# ------------------------------------------------------------------
# 個別の検出ロジック
# ------------------------------------------------------------------

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
