"""
Windows Activity Logger - tkinter UI
4タブ構成:
  [ログ一覧] [サマリー] [インサイト] [カレンダー]
"""
import os
import subprocess
import sys
import threading
import tkinter as tk
from collections import defaultdict
from datetime import datetime, timedelta
from tkinter import messagebox, ttk

from google_calendar import (
    CalendarClient,
    build_event_summaries,
    link_activities_to_events,
)
from logger import DEFAULT_OUTPUT_DIR, ActivityLogger, load_from_csv
from pattern_detector import (
    PatternInsight,
    analyze,
    calc_context_switch_cost,
    detect_peak_hours,
    detect_work_sessions,
    score_productivity,
)


# --------------------------------------------------------
# カラーパレット
# --------------------------------------------------------
CLR = {
    "bg":      "#1e1e2e",
    "surface": "#2a2a3e",
    "primary": "#7c3aed",
    "success": "#22c55e",
    "warning": "#f59e0b",
    "danger":  "#ef4444",
    "text":    "#e2e8f0",
    "muted":   "#94a3b8",
    "border":  "#374151",
}

CATEGORY_COLORS = {
    "browser":       "#3b82f6",
    "communication": "#8b5cf6",
    "development":   "#22c55e",
    "office":        "#f59e0b",
    "file_manager":  "#06b6d4",
    "terminal":      "#ec4899",
    "meeting":       "#ef4444",
    "other":         "#6b7280",
}


# --------------------------------------------------------
# メインアプリ
# --------------------------------------------------------

class App(tk.Tk):
    POLL_MS = 3000  # UI更新間隔(ms)

    def __init__(self):
        super().__init__()
        self.title("Windows Activity Logger")
        self.geometry("960x680")
        self.configure(bg=CLR["bg"])
        self.resizable(True, True)

        self.logger = ActivityLogger(interval=5)
        self.cal_client = CalendarClient()
        self._cal_events: list = []          # キャッシュ済みカレンダーイベント
        self._cal_date: datetime = datetime.now()

        self._build_ui()
        self._load_past_records()            # 起動時に過去ログを復元
        self._schedule_refresh()

    # ----------------------------------------------------------
    # UI 構築
    # ----------------------------------------------------------

    def _build_ui(self):
        # ヘッダー
        header = tk.Frame(self, bg=CLR["primary"], pady=10)
        header.pack(fill="x")
        tk.Label(header, text="Windows Activity Logger",
                 font=("Segoe UI", 16, "bold"),
                 bg=CLR["primary"], fg="white").pack(side="left", padx=16)

        btn_frame = tk.Frame(header, bg=CLR["primary"])
        btn_frame.pack(side="right", padx=16)
        self.btn_toggle = tk.Button(btn_frame, text="▶ 記録開始",
                                    command=self._toggle_logging,
                                    bg=CLR["success"], fg="white",
                                    font=("Segoe UI", 11, "bold"),
                                    relief="flat", padx=12, pady=4, cursor="hand2")
        self.btn_toggle.pack(side="left", padx=6)
        tk.Button(btn_frame, text="📂 ログを開く",
                  command=self._open_log_folder,
                  bg=CLR["surface"], fg=CLR["text"],
                  font=("Segoe UI", 11),
                  relief="flat", padx=12, pady=4, cursor="hand2").pack(side="left", padx=6)

        # ステータスバー
        self.status_var = tk.StringVar(value="停止中")
        status_bar = tk.Frame(self, bg=CLR["surface"], pady=4)
        status_bar.pack(fill="x")
        self.status_dot = tk.Label(status_bar, text="●", fg=CLR["muted"],
                                   bg=CLR["surface"], font=("Segoe UI", 10))
        self.status_dot.pack(side="left", padx=(12, 4))
        tk.Label(status_bar, textvariable=self.status_var,
                 bg=CLR["surface"], fg=CLR["muted"],
                 font=("Segoe UI", 10)).pack(side="left")
        self.record_count_var = tk.StringVar(value="記録数: 0")
        tk.Label(status_bar, textvariable=self.record_count_var,
                 bg=CLR["surface"], fg=CLR["muted"],
                 font=("Segoe UI", 10)).pack(side="right", padx=12)

        # タブ
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TNotebook", background=CLR["bg"], borderwidth=0)
        style.configure("TNotebook.Tab", background=CLR["surface"],
                        foreground=CLR["muted"], padding=(14, 6),
                        font=("Segoe UI", 10))
        style.map("TNotebook.Tab",
                  background=[("selected", CLR["primary"])],
                  foreground=[("selected", "white")])

        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True, padx=8, pady=8)

        self.tab_log      = tk.Frame(self.nb, bg=CLR["bg"])
        self.tab_summary  = tk.Frame(self.nb, bg=CLR["bg"])
        self.tab_insights = tk.Frame(self.nb, bg=CLR["bg"])
        self.tab_calendar = tk.Frame(self.nb, bg=CLR["bg"])

        self.nb.add(self.tab_log,      text="  ログ一覧  ")
        self.nb.add(self.tab_summary,  text="  サマリー  ")
        self.nb.add(self.tab_insights, text="  インサイト  ")
        self.nb.add(self.tab_calendar, text="  カレンダー  ")

        self.nb.bind("<<NotebookTabChanged>>", self._on_tab_changed)

        self._build_log_tab()
        self._build_summary_tab()
        self._build_insights_tab()
        self._build_calendar_tab()

    # ---- ログ一覧タブ ----
    def _build_log_tab(self):
        cols    = ("timestamp", "app", "title", "duration", "category")
        headers = ("タイムスタンプ", "アプリ", "ウィンドウタイトル", "秒数", "カテゴリ")
        widths  = (150, 120, 330, 70, 90)

        style = ttk.Style()
        style.configure("Log.Treeview",
                        background=CLR["surface"], foreground=CLR["text"],
                        fieldbackground=CLR["surface"], rowheight=26,
                        font=("Segoe UI", 10))
        style.configure("Log.Treeview.Heading",
                        background=CLR["bg"], foreground=CLR["muted"],
                        font=("Segoe UI", 10, "bold"))
        style.map("Log.Treeview", background=[("selected", CLR["primary"])])

        frame = tk.Frame(self.tab_log, bg=CLR["bg"])
        frame.pack(fill="both", expand=True, padx=4, pady=4)

        self.tree = ttk.Treeview(frame, columns=cols, show="headings",
                                 style="Log.Treeview")
        for col, hdr, w in zip(cols, headers, widths):
            self.tree.heading(col, text=hdr)
            self.tree.column(col, width=w, anchor="w")

        vsb = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

    # ---- サマリータブ ----
    def _build_summary_tab(self):
        self.summary_frame = tk.Frame(self.tab_summary, bg=CLR["bg"])
        self.summary_frame.pack(fill="both", expand=True, padx=12, pady=12)

    def _refresh_summary(self, records):
        for w in self.summary_frame.winfo_children():
            w.destroy()

        if not records:
            tk.Label(self.summary_frame, text="まだ記録がありません",
                     bg=CLR["bg"], fg=CLR["muted"],
                     font=("Segoe UI", 12)).pack(pady=40)
            return

        canvas = tk.Canvas(self.summary_frame, bg=CLR["bg"], highlightthickness=0)
        vsb = ttk.Scrollbar(self.summary_frame, orient="vertical",
                            command=canvas.yview)
        inner = tk.Frame(canvas, bg=CLR["bg"])
        inner.bind("<Configure>",
                   lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=vsb.set)
        canvas.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        # --- カテゴリ別使用時間 ---
        cat_totals: dict[str, float] = defaultdict(float)
        app_totals: dict[str, float] = defaultdict(float)
        for r in records:
            cat_totals[r.category] += r.duration_sec
            app_totals[r.app_name] += r.duration_sec
        total_all = sum(cat_totals.values())

        _section(inner, "カテゴリ別 使用時間")
        for cat, sec in sorted(cat_totals.items(), key=lambda x: -x[1]):
            pct   = sec / total_all * 100 if total_all else 0
            color = CATEGORY_COLORS.get(cat, "#6b7280")
            row = tk.Frame(inner, bg=CLR["bg"])
            row.pack(fill="x", pady=3)
            tk.Label(row, text=f"{cat:<15}", bg=CLR["bg"], fg=CLR["text"],
                     font=("Consolas", 11), width=15, anchor="w").pack(side="left")
            bar_bg = tk.Frame(row, bg=CLR["border"], height=18, width=300)
            bar_bg.pack(side="left", padx=8)
            bar_bg.pack_propagate(False)
            tk.Frame(bar_bg, bg=color, height=18,
                     width=max(2, int(300 * pct / 100))).place(x=0, y=0)
            tk.Label(row, text=f"{_fmt_sec(sec)}  ({pct:.1f}%)",
                     bg=CLR["bg"], fg=CLR["muted"],
                     font=("Segoe UI", 10)).pack(side="left")

        tk.Label(inner, text=f"合計: {_fmt_sec(total_all)}",
                 bg=CLR["bg"], fg=CLR["muted"],
                 font=("Segoe UI", 10)).pack(anchor="w", pady=(4, 0))

        # --- アプリ Top5 ---
        _section(inner, "アプリ Top 5")
        for app, sec in sorted(app_totals.items(), key=lambda x: -x[1])[:5]:
            tk.Label(inner, text=f"  {app:<25} {_fmt_sec(sec)}",
                     bg=CLR["bg"], fg=CLR["text"],
                     font=("Consolas", 11)).pack(anchor="w")

        # --- 生産性スコア (Feature #10) ---
        _section(inner, "時間帯別 生産性スコア")
        prod_scores = score_productivity(records)
        peak_hours  = detect_peak_hours(records)
        if prod_scores:
            for hour in sorted(prod_scores.keys()):
                score = prod_scores[hour]
                is_peak = hour in peak_hours
                color = CLR["success"] if is_peak else CLR["border"]
                bar_w = max(2, int(200 * score / 100))
                row = tk.Frame(inner, bg=CLR["bg"])
                row.pack(fill="x", pady=2)
                peak_mark = " ★" if is_peak else "  "
                tk.Label(row, text=f"{hour:02d}:00{peak_mark}",
                         bg=CLR["bg"], fg=CLR["text"] if is_peak else CLR["muted"],
                         font=("Consolas", 10), width=10, anchor="w").pack(side="left")
                bar_bg = tk.Frame(row, bg=CLR["border"], height=14, width=200)
                bar_bg.pack(side="left", padx=8)
                bar_bg.pack_propagate(False)
                tk.Frame(bar_bg, bg=color, height=14, width=bar_w).place(x=0, y=0)
                tk.Label(row, text=f"{score:.0f}",
                         bg=CLR["bg"], fg=CLR["muted"],
                         font=("Consolas", 10)).pack(side="left")
            if peak_hours:
                peak_str = "、".join(f"{h:02d}時台" for h in sorted(peak_hours))
                tk.Label(inner, text=f"★ 最も生産的な時間帯: {peak_str}",
                         bg=CLR["bg"], fg=CLR["success"],
                         font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(6, 0))
        else:
            tk.Label(inner, text="  データ不足（記録を続けると表示されます）",
                     bg=CLR["bg"], fg=CLR["muted"],
                     font=("Segoe UI", 10)).pack(anchor="w")

        # --- 作業セッション (Feature #10) ---
        _section(inner, "作業セッション")
        sessions = detect_work_sessions(records)
        cost = calc_context_switch_cost(records)
        if sessions:
            tk.Label(inner,
                     text=f"  セッション数: {len(sessions)}  |  "
                          f"コンテキストスイッチ: {int(cost['switch_count'])}回  |  "
                          f"損失時間推定: {_fmt_sec(cost['lost_sec'])}",
                     bg=CLR["bg"], fg=CLR["muted"],
                     font=("Segoe UI", 10)).pack(anchor="w", pady=(0, 6))
            for i, sess in enumerate(sessions[:5], 1):
                line = (
                    f"  #{i}  {sess.start.strftime('%H:%M')}〜{sess.end.strftime('%H:%M')}"
                    f"  ({_fmt_sec(sess.duration_sec)})  主なアプリ: {sess.primary_app}"
                    f"  集中度: {sess.focus_score:.0f}"
                )
                tk.Label(inner, text=line,
                         bg=CLR["bg"], fg=CLR["text"],
                         font=("Consolas", 10)).pack(anchor="w")
            if len(sessions) > 5:
                tk.Label(inner, text=f"  ... 他 {len(sessions)-5} セッション",
                         bg=CLR["bg"], fg=CLR["muted"],
                         font=("Segoe UI", 9)).pack(anchor="w")
        else:
            tk.Label(inner, text="  まだセッションデータがありません",
                     bg=CLR["bg"], fg=CLR["muted"],
                     font=("Segoe UI", 10)).pack(anchor="w")

    # ---- インサイトタブ ----
    def _build_insights_tab(self):
        self.insights_frame = tk.Frame(self.tab_insights, bg=CLR["bg"])
        self.insights_frame.pack(fill="both", expand=True, padx=12, pady=12)

    def _refresh_insights(self, records):
        for w in self.insights_frame.winfo_children():
            w.destroy()

        insights = analyze(records)

        if not insights:
            tk.Label(self.insights_frame,
                     text="まだ分析できるデータが不足しています。\n記録を続けるとインサイトが表示されます。",
                     bg=CLR["bg"], fg=CLR["muted"],
                     font=("Segoe UI", 12),
                     justify="center").pack(pady=60)
            return

        canvas = tk.Canvas(self.insights_frame, bg=CLR["bg"], highlightthickness=0)
        scrollbar = ttk.Scrollbar(self.insights_frame, orient="vertical",
                                  command=canvas.yview)
        scroll_frame = tk.Frame(canvas, bg=CLR["bg"])
        scroll_frame.bind("<Configure>",
                          lambda e: canvas.configure(
                              scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=scroll_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        for insight in insights:
            self._render_insight_card(scroll_frame, insight)

    def _render_insight_card(self, parent, insight: PatternInsight):
        color = CLR["warning"] if insight.kind == "waste" else CLR["success"]
        icon  = "⚠" if insight.kind == "waste" else "💡"
        label = "無駄パターン" if insight.kind == "waste" else "自動化提案"

        card = tk.Frame(parent, bg=CLR["surface"],
                        highlightbackground=color, highlightthickness=1)
        card.pack(fill="x", pady=6, padx=2)

        hdr = tk.Frame(card, bg=color)
        hdr.pack(fill="x")
        tk.Label(hdr, text=f"{icon} {label}",
                 bg=color, fg="white",
                 font=("Segoe UI", 9, "bold"),
                 padx=10, pady=3).pack(side="left")
        tk.Label(hdr, text=f"合計: {_fmt_sec(insight.total_sec)}",
                 bg=color, fg="white",
                 font=("Segoe UI", 9),
                 padx=10, pady=3).pack(side="right")

        body = tk.Frame(card, bg=CLR["surface"], padx=12, pady=8)
        body.pack(fill="x")
        tk.Label(body, text=insight.title,
                 bg=CLR["surface"], fg=CLR["text"],
                 font=("Segoe UI", 11, "bold"), anchor="w").pack(fill="x")
        tk.Label(body, text=insight.description,
                 bg=CLR["surface"], fg=CLR["muted"],
                 font=("Segoe UI", 10),
                 wraplength=720, justify="left", anchor="w").pack(fill="x", pady=(4, 0))
        if insight.apps:
            tk.Label(body, text="関連アプリ: " + ", ".join(insight.apps),
                     bg=CLR["surface"], fg=CLR["muted"],
                     font=("Segoe UI", 9, "italic")).pack(anchor="w", pady=(4, 0))

    # ---- カレンダータブ (Feature #9) ----
    def _build_calendar_tab(self):
        top = tk.Frame(self.tab_calendar, bg=CLR["bg"])
        top.pack(fill="x", padx=12, pady=(12, 6))

        # 日付選択
        tk.Label(top, text="日付:", bg=CLR["bg"], fg=CLR["text"],
                 font=("Segoe UI", 10)).pack(side="left")
        self.cal_date_var = tk.StringVar(value=datetime.now().strftime("%Y-%m-%d"))
        date_entry = tk.Entry(top, textvariable=self.cal_date_var, width=12,
                              bg=CLR["surface"], fg=CLR["text"],
                              insertbackground=CLR["text"],
                              font=("Segoe UI", 10), relief="flat")
        date_entry.pack(side="left", padx=6)

        self.btn_cal_refresh = tk.Button(top, text="更新",
                                         command=self._fetch_calendar_events,
                                         bg=CLR["primary"], fg="white",
                                         font=("Segoe UI", 10),
                                         relief="flat", padx=10, cursor="hand2")
        self.btn_cal_refresh.pack(side="left", padx=6)

        self.btn_cal_auth = tk.Button(top, text="Google カレンダーと連携する",
                                      command=self._authenticate_calendar,
                                      bg=CLR["surface"], fg=CLR["text"],
                                      font=("Segoe UI", 10),
                                      relief="flat", padx=10, cursor="hand2")
        self.btn_cal_auth.pack(side="right", padx=6)

        # ステータスラベル
        self.cal_status_var = tk.StringVar(value="")
        tk.Label(top, textvariable=self.cal_status_var,
                 bg=CLR["bg"], fg=CLR["muted"],
                 font=("Segoe UI", 9)).pack(side="right", padx=8)

        # イベント表示エリア
        self.calendar_body = tk.Frame(self.tab_calendar, bg=CLR["bg"])
        self.calendar_body.pack(fill="both", expand=True, padx=12, pady=6)

        self._render_calendar_setup_guide()

    def _render_calendar_setup_guide(self):
        for w in self.calendar_body.winfo_children():
            w.destroy()

        if not self.cal_client.is_available():
            msg = (
                "Google Calendar 連携を使用するには追加パッケージが必要です。\n\n"
                "pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib\n\n"
                "インストール後、アプリを再起動してください。"
            )
        elif not self.cal_client.is_configured():
            msg = (
                "【Google カレンダー連携のセットアップ手順】\n\n"
                "1. Google Cloud Console (console.cloud.google.com) でプロジェクトを作成\n"
                "2. 「APIとサービス」→「ライブラリ」で Google Calendar API を有効化\n"
                "3. 「認証情報」→「OAuth 2.0 クライアント ID」を作成 (種類: デスクトップアプリ)\n"
                "4. 認証情報 JSON をダウンロードし、以下に配置:\n\n"
                f"   {self.cal_client.__class__.__module__}\n\n"
                "5. 「Google カレンダーと連携する」ボタンを押して認証を完了"
            )
        elif not self.cal_client.is_authenticated():
            msg = "「Google カレンダーと連携する」ボタンを押してブラウザで認証してください。"
        else:
            msg = ""

        if msg:
            tk.Label(self.calendar_body, text=msg,
                     bg=CLR["bg"], fg=CLR["muted"],
                     font=("Segoe UI", 11),
                     justify="left", anchor="nw",
                     wraplength=700).pack(pady=40, padx=20, anchor="w")

    def _refresh_calendar(self, records=None):
        """カレンダーイベントと操作ログのリンクを再描画する"""
        for w in self.calendar_body.winfo_children():
            w.destroy()

        if not self.cal_client.is_authenticated():
            self._render_calendar_setup_guide()
            return

        if records is None:
            records = self.logger.get_records()

        events = self._cal_events
        if not events:
            tk.Label(self.calendar_body,
                     text="「更新」ボタンを押してカレンダーを読み込んでください。",
                     bg=CLR["bg"], fg=CLR["muted"],
                     font=("Segoe UI", 11)).pack(pady=40)
            return

        # リンク計算
        linked = link_activities_to_events(records, events)
        summaries = build_event_summaries(events, linked)

        # テーブルヘッダー
        hdr = tk.Frame(self.calendar_body, bg=CLR["surface"])
        hdr.pack(fill="x", pady=(0, 4))
        for txt, w in [("時刻", 120), ("イベント名", 260), ("主な使用アプリ", 340), ("操作時間", 80)]:
            tk.Label(hdr, text=txt, bg=CLR["surface"], fg=CLR["muted"],
                     font=("Segoe UI", 10, "bold"),
                     width=w // 8, anchor="w").pack(side="left", padx=6, pady=4)

        # スクロール可能なイベントリスト
        canvas = tk.Canvas(self.calendar_body, bg=CLR["bg"], highlightthickness=0)
        vsb = ttk.Scrollbar(self.calendar_body, orient="vertical",
                            command=canvas.yview)
        body_frame = tk.Frame(canvas, bg=CLR["bg"])
        body_frame.bind("<Configure>",
                        lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=body_frame, anchor="nw")
        canvas.configure(yscrollcommand=vsb.set)
        canvas.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        for summary in sorted(summaries, key=lambda s: s.event.start):
            event = summary.event
            time_str = f"{event.start.strftime('%H:%M')}〜{event.end.strftime('%H:%M')}"

            # 上位3アプリを表示
            top_apps = sorted(summary.app_times.items(), key=lambda x: -x[1])[:3]
            apps_str = "  ".join(f"{app}({_fmt_sec(sec)})" for app, sec in top_apps) or "—"

            row = tk.Frame(body_frame, bg=CLR["surface"])
            row.pack(fill="x", pady=2)

            # 時刻
            tk.Label(row, text=time_str,
                     bg=CLR["surface"], fg=CLR["muted"],
                     font=("Consolas", 10), width=14, anchor="w").pack(side="left", padx=6)
            # イベント名
            tk.Label(row, text=event.title[:35],
                     bg=CLR["surface"], fg=CLR["text"],
                     font=("Segoe UI", 10, "bold"), width=30, anchor="w").pack(side="left")
            # アプリ
            tk.Label(row, text=apps_str,
                     bg=CLR["surface"], fg=CLR["muted"],
                     font=("Consolas", 9), width=42, anchor="w").pack(side="left")
            # 合計操作時間
            tk.Label(row, text=_fmt_sec(summary.total_sec) if summary.total_sec else "—",
                     bg=CLR["surface"], fg=CLR["muted"],
                     font=("Consolas", 10), width=8, anchor="w").pack(side="left")

        # リンクなし操作を一覧表示
        unlinked = [la.record for la in linked if la.event is None]
        if unlinked:
            unlinked_sec = sum(r.duration_sec for r in unlinked)
            tk.Label(body_frame,
                     text=f"\n※ カレンダーイベントと紐付けられない操作: {len(unlinked)}件 / {_fmt_sec(unlinked_sec)}",
                     bg=CLR["bg"], fg=CLR["muted"],
                     font=("Segoe UI", 9)).pack(anchor="w", pady=4)

    # ----------------------------------------------------------
    # コントロールロジック
    # ----------------------------------------------------------

    def _toggle_logging(self):
        if self.logger.is_running():
            self.logger.stop()
            self.btn_toggle.config(text="▶ 記録開始", bg=CLR["success"])
            self.status_var.set("停止中")
            self.status_dot.config(fg=CLR["muted"])
        else:
            self.logger.start()
            self.btn_toggle.config(text="⏹ 記録停止", bg=CLR["danger"])
            self.status_var.set(f"記録中... → {self.logger.get_csv_path()}")
            self.status_dot.config(fg=CLR["success"])

    def _open_log_folder(self):
        path = str(self.logger.get_csv_path().parent.resolve())
        if sys.platform == "win32":
            os.startfile(path)
        else:
            subprocess.Popen(["xdg-open", path])

    def _load_past_records(self):
        """
        起動時に DEFAULT_OUTPUT_DIR 内の最新 CSV を読み込んで
        メモリに復元する。(Limitation #7 対応)
        """
        log_dir = DEFAULT_OUTPUT_DIR
        if not log_dir.exists():
            return
        csv_files = sorted(
            log_dir.glob("activity_*.csv"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        # 最新ファイル（現セッション）は除外して、その1つ前を読む
        if len(csv_files) > 1:
            past_records = load_from_csv(csv_files[1])
            if past_records:
                self.logger.load_records(past_records)

    def _authenticate_calendar(self):
        """別スレッドで Google Calendar OAuth2 認証を実行する"""
        self.btn_cal_auth.config(state="disabled", text="認証中... (ブラウザを確認)")

        def _run():
            ok, msg = self.cal_client.authenticate()
            if ok:
                self.after(0, self._on_auth_success)
            else:
                self.after(0, self._on_auth_failure, msg)

        threading.Thread(target=_run, daemon=True).start()

    def _on_auth_success(self):
        self.btn_cal_auth.config(state="normal", text="再認証")
        self.cal_status_var.set("✓ 認証済み")
        self._fetch_calendar_events()

    def _on_auth_failure(self, msg: str):
        self.btn_cal_auth.config(state="normal", text="Google カレンダーと連携する")
        messagebox.showerror("Google Calendar 認証エラー", msg)

    def _fetch_calendar_events(self):
        """選択日のカレンダーイベントを取得してキャッシュ・再描画する"""
        if not self.cal_client.is_authenticated():
            self._render_calendar_setup_guide()
            return

        try:
            date = datetime.strptime(self.cal_date_var.get(), "%Y-%m-%d")
        except ValueError:
            self.cal_status_var.set("日付の形式が正しくありません (YYYY-MM-DD)")
            return

        self.cal_status_var.set("取得中...")
        self.btn_cal_refresh.config(state="disabled")

        def _run():
            events = self.cal_client.get_date_events(date)
            self.after(0, self._on_events_fetched, events)

        threading.Thread(target=_run, daemon=True).start()

    def _on_events_fetched(self, events):
        self._cal_events = events
        count = len(events)
        self.cal_status_var.set(f"{count}件のイベントを取得")
        self.btn_cal_refresh.config(state="normal")
        self._refresh_calendar()

    def _on_tab_changed(self, event):
        """カレンダータブを開いたとき、認証済みならイベントを自動取得する"""
        idx = self.nb.index(self.nb.select())
        if idx == 3 and self.cal_client.is_authenticated() and not self._cal_events:
            self._fetch_calendar_events()

    # ----------------------------------------------------------
    # 定期更新
    # ----------------------------------------------------------

    def _schedule_refresh(self):
        self._refresh_ui()
        self.after(self.POLL_MS, self._schedule_refresh)

    def _refresh_ui(self):
        records = self.logger.get_records()
        self.record_count_var.set(f"記録数: {len(records)}")

        # ログ一覧（直近200件を新しい順に表示）
        self.tree.delete(*self.tree.get_children())
        for r in reversed(records[-200:]):
            self.tree.insert("", "end", values=(
                r.timestamp, r.app_name,
                r.window_title[:60], r.duration_sec, r.category,
            ))

        # サマリー・インサイトは tkinter のメインスレッドで更新
        threading.Thread(target=self._bg_refresh, args=(records,),
                         daemon=True).start()

    def _bg_refresh(self, records):
        self.after(0, self._refresh_summary, records)
        self.after(0, self._refresh_insights, records)


# ----------------------------------------------------------
# ユーティリティ
# ----------------------------------------------------------

def _fmt_sec(sec: float) -> str:
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = int(sec % 60)
    if h:
        return f"{h}h {m:02d}m"
    if m:
        return f"{m}m {s:02d}s"
    return f"{s}s"


def _section(parent: tk.Frame, title: str):
    """セクションヘッダーを生成する"""
    tk.Label(parent, text=title,
             bg=CLR["bg"], fg=CLR["text"],
             font=("Segoe UI", 13, "bold")).pack(anchor="w", pady=(16, 6))
