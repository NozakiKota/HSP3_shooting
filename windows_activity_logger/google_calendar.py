"""
Google Calendar Integration Module
操作ログと Google カレンダーイベントを紐付ける (Feature #9)
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

try:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
    GOOGLE_AVAILABLE = True
except ImportError:
    GOOGLE_AVAILABLE = False

from logger import ActivityRecord

# カレンダーの読み取り専用スコープ
SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]

# 設定ファイルの保存先
CONFIG_DIR = Path.home() / ".windows_activity_logger"
CREDENTIALS_PATH = CONFIG_DIR / "credentials.json"
TOKEN_PATH = CONFIG_DIR / "token.json"


@dataclass
class CalendarEvent:
    event_id: str
    title: str
    start: datetime
    end: datetime
    description: str = ""
    is_all_day: bool = False

    @property
    def duration_min(self) -> float:
        return (self.end - self.start).total_seconds() / 60


@dataclass
class LinkedActivity:
    record: ActivityRecord
    event: Optional[CalendarEvent]
    overlap_sec: float


@dataclass
class EventSummary:
    """カレンダーイベント単位の作業サマリー"""
    event: CalendarEvent
    app_times: dict[str, float] = field(default_factory=dict)   # app_name -> 秒数
    category_times: dict[str, float] = field(default_factory=dict)

    @property
    def total_sec(self) -> float:
        return sum(self.app_times.values())


class CalendarClient:
    """Google Calendar API クライアント"""

    def __init__(self) -> None:
        self._service = None
        self._creds = None

    # ------------------------------------------------------------------
    # 状態確認
    # ------------------------------------------------------------------

    def is_available(self) -> bool:
        """google-api-python-client がインストール済みか"""
        return GOOGLE_AVAILABLE

    def is_configured(self) -> bool:
        """credentials.json が存在するか"""
        return CREDENTIALS_PATH.exists()

    def is_authenticated(self) -> bool:
        """有効なアクセストークンが存在するか"""
        if not GOOGLE_AVAILABLE:
            return False
        creds = self._load_token()
        return creds is not None and creds.valid

    # ------------------------------------------------------------------
    # 認証
    # ------------------------------------------------------------------

    def authenticate(self) -> tuple[bool, str]:
        """
        OAuth2 認証フローを実行する。
        ブラウザが開いてユーザーの承認が必要。

        Returns:
            (成功フラグ, エラーメッセージ)
        """
        if not GOOGLE_AVAILABLE:
            return False, (
                "google-api-python-client がインストールされていません。\n\n"
                "以下のコマンドでインストールしてください:\n"
                "pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib"
            )

        if not CREDENTIALS_PATH.exists():
            return False, (
                f"認証情報ファイルが見つかりません。\n\n"
                f"【セットアップ手順】\n"
                f"1. Google Cloud Console でプロジェクトを作成\n"
                f"2. Google Calendar API を有効化\n"
                f"3. OAuth 2.0 クライアント ID を作成 (種類: デスクトップアプリ)\n"
                f"4. 認証情報 JSON を以下に配置:\n"
                f"   {CREDENTIALS_PATH}"
            )

        try:
            creds = self._load_token()

            if not creds or not creds.valid:
                if creds and creds.expired and creds.refresh_token:
                    creds.refresh(Request())
                else:
                    flow = InstalledAppFlow.from_client_secrets_file(
                        str(CREDENTIALS_PATH), SCOPES
                    )
                    creds = flow.run_local_server(port=0)

                TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
                with open(TOKEN_PATH, "w", encoding="utf-8") as f:
                    f.write(creds.to_json())

            self._creds = creds
            self._service = build("calendar", "v3", credentials=creds)
            return True, ""

        except Exception as e:
            return False, f"認証中にエラーが発生しました:\n{e}"

    # ------------------------------------------------------------------
    # イベント取得
    # ------------------------------------------------------------------

    def get_events(self, start: datetime, end: datetime) -> list[CalendarEvent]:
        """
        指定期間のカレンダーイベントを取得する。
        未認証の場合は空リストを返す。

        Args:
            start: 取得開始日時（ローカルタイム）
            end:   取得終了日時（ローカルタイム）
        """
        if not self._service:
            return []

        try:
            start_utc = start.astimezone(timezone.utc).isoformat()
            end_utc = end.astimezone(timezone.utc).isoformat()

            result = (
                self._service.events()
                .list(
                    calendarId="primary",
                    timeMin=start_utc,
                    timeMax=end_utc,
                    singleEvents=True,
                    orderBy="startTime",
                    maxResults=250,
                )
                .execute()
            )

            events = []
            for item in result.get("items", []):
                event = _parse_event(item)
                if event:
                    events.append(event)
            return events

        except Exception:
            return []

    def get_today_events(self) -> list[CalendarEvent]:
        """今日（0:00〜23:59）のイベントを取得する"""
        now = datetime.now().astimezone()
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)
        return self.get_events(start, end)

    def get_date_events(self, date: datetime) -> list[CalendarEvent]:
        """指定日のイベントを取得する"""
        start = date.replace(hour=0, minute=0, second=0, microsecond=0)
        if start.tzinfo is None:
            start = start.astimezone()
        end = start + timedelta(days=1)
        return self.get_events(start, end)

    # ------------------------------------------------------------------
    # 内部処理
    # ------------------------------------------------------------------

    def _load_token(self):
        if not GOOGLE_AVAILABLE or not TOKEN_PATH.exists():
            return None
        try:
            return Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
        except Exception:
            return None


# ------------------------------------------------------------------
# モジュールレベル関数
# ------------------------------------------------------------------

def _parse_event(item: dict) -> Optional[CalendarEvent]:
    """Google Calendar API レスポンスの辞書から CalendarEvent を生成する"""
    try:
        start_data = item.get("start", {})
        end_data = item.get("end", {})
        is_all_day = "date" in start_data and "dateTime" not in start_data

        if is_all_day:
            start = datetime.fromisoformat(start_data["date"])
            end = datetime.fromisoformat(end_data["date"])
        else:
            start = datetime.fromisoformat(start_data["dateTime"])
            end = datetime.fromisoformat(end_data["dateTime"])
            # tzinfo を除去してローカル時刻に変換
            if start.tzinfo:
                start = start.astimezone().replace(tzinfo=None)
            if end.tzinfo:
                end = end.astimezone().replace(tzinfo=None)

        return CalendarEvent(
            event_id=item.get("id", ""),
            title=item.get("summary", "(タイトルなし)"),
            start=start,
            end=end,
            description=item.get("description", ""),
            is_all_day=is_all_day,
        )
    except (KeyError, ValueError):
        return None


def link_activities_to_events(
    records: list[ActivityRecord],
    events: list[CalendarEvent],
) -> list[LinkedActivity]:
    """
    操作ログとカレンダーイベントを時間的重複で紐付ける。
    重複時間が最も長いイベントと紐付ける。
    """
    linked = []

    for record in records:
        try:
            record_start = datetime.strptime(record.timestamp, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            linked.append(LinkedActivity(record=record, event=None, overlap_sec=0.0))
            continue

        record_end = record_start + timedelta(seconds=record.duration_sec)
        best_event: Optional[CalendarEvent] = None
        best_overlap = 0.0

        for event in events:
            if event.is_all_day:
                continue
            overlap_start = max(record_start, event.start)
            overlap_end = min(record_end, event.end)
            overlap = (overlap_end - overlap_start).total_seconds()
            if overlap > best_overlap:
                best_overlap = overlap
                best_event = event

        linked.append(LinkedActivity(
            record=record,
            event=best_event,
            overlap_sec=round(best_overlap, 1),
        ))

    return linked


def build_event_summaries(
    events: list[CalendarEvent],
    linked: list[LinkedActivity],
) -> list[EventSummary]:
    """
    イベントごとに、その時間帯の操作ログを集計した EventSummary を生成する。
    """
    summaries: dict[str, EventSummary] = {e.event_id: EventSummary(event=e) for e in events}

    for la in linked:
        if la.event is None or la.event.event_id not in summaries:
            continue
        summary = summaries[la.event.event_id]
        app = la.record.app_name
        cat = la.record.category
        summary.app_times[app] = summary.app_times.get(app, 0.0) + la.overlap_sec
        summary.category_times[cat] = summary.category_times.get(cat, 0.0) + la.overlap_sec

    return [s for s in summaries.values() if not s.event.is_all_day]
