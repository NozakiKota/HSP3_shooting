"""
Windows Activity Logger - tkinter UI
シンプルな3タブ構成:
  [ログ一覧] [サマリー] [インサイト]
"""
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import messagebox, ttk
from collections import defaultdict

from logger import ActivityLogger
from pattern_detector import PatternInsight, analyze


# --------------------------------------------------------
# カラーパレット
# --------------------------------------------------------
CLR = {
    "bg": "#1e1e2e",
    "surface": "#2a2a3e",
    "primary": "#7c3aed",
    "success": "#22c55e",
    "warning": "#f59e0b",
    "danger": "#ef4444",
    "text": "#e2e8f0",
    "muted": "#94a3b8",
    "border": "#374151",
}


class App(tk.Tk):
    POLL_MS = 3000  # UI更新間隔(ms)

    def __init__(self):
        super().__init__()
        self.title("Windows Activity Logger")
        self.geometry("900x640")
        self.configure(bg=CLR["bg"])
        self.resizable(True, True)

        self.logger = ActivityLogger(output_dir="logs", interval=5)
        self._build_ui()
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

        # コントロールボタン
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

        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=8, pady=8)

        self.tab_log = tk.Frame(nb, bg=CLR["bg"])
        self.tab_summary = tk.Frame(nb, bg=CLR["bg"])
        self.tab_insights = tk.Frame(nb, bg=CLR["bg"])

        nb.add(self.tab_log, text="  ログ一覧  ")
        nb.add(self.tab_summary, text="  サマリー  ")
        nb.add(self.tab_insights, text="  インサイト  ")

        self._build_log_tab()
        self._build_summary_tab()
        self._build_insights_tab()

    # --- ログ一覧タブ ---
    def _build_log_tab(self):
        cols = ("timestamp", "app", "title", "duration", "category")
        headers = ("タイムスタンプ", "アプリ", "ウィンドウタイトル", "秒数", "カテゴリ")
        widths = (150, 120, 330, 70, 90)

        style = ttk.Style()
        style.configure("Log.Treeview",
                        background=CLR["surface"],
                        foreground=CLR["text"],
                        fieldbackground=CLR["surface"],
                        rowheight=26,
                        font=("Segoe UI", 10))
        style.configure("Log.Treeview.Heading",
                        background=CLR["bg"],
                        foreground=CLR["muted"],
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

    # --- サマリータブ ---
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

        # カテゴリ別合計
        cat_totals: dict[str, float] = defaultdict(float)
        app_totals: dict[str, float] = defaultdict(float)
        for r in records:
            cat_totals[r.category] += r.duration_sec
            app_totals[r.app_name] += r.duration_sec

        total_all = sum(cat_totals.values())

        tk.Label(self.summary_frame, text="カテゴリ別 使用時間",
                 bg=CLR["bg"], fg=CLR["text"],
                 font=("Segoe UI", 13, "bold")).pack(anchor="w", pady=(0, 8))

        CATEGORY_COLORS = {
            "browser": "#3b82f6",
            "communication": "#8b5cf6",
            "development": "#22c55e",
            "office": "#f59e0b",
            "file_manager": "#06b6d4",
            "terminal": "#ec4899",
            "meeting": "#ef4444",
            "other": "#6b7280",
        }

        for cat, sec in sorted(cat_totals.items(), key=lambda x: -x[1]):
            pct = sec / total_all * 100 if total_all else 0
            color = CATEGORY_COLORS.get(cat, "#6b7280")
            row = tk.Frame(self.summary_frame, bg=CLR["bg"])
            row.pack(fill="x", pady=3)
            tk.Label(row, text=f"{cat:<15}", bg=CLR["bg"], fg=CLR["text"],
                     font=("Consolas", 11), width=15, anchor="w").pack(side="left")
            # バーグラフ
            bar_bg = tk.Frame(row, bg=CLR["border"], height=18, width=300)
            bar_bg.pack(side="left", padx=8)
            bar_bg.pack_propagate(False)
            bar_fill = tk.Frame(bar_bg, bg=color, height=18,
                                width=max(2, int(300 * pct / 100)))
            bar_fill.place(x=0, y=0)
            tk.Label(row, text=f"{_fmt_sec(sec)}  ({pct:.1f}%)",
                     bg=CLR["bg"], fg=CLR["muted"],
                     font=("Segoe UI", 10)).pack(side="left")

        tk.Label(self.summary_frame, text=f"\n合計記録時間: {_fmt_sec(total_all)}",
                 bg=CLR["bg"], fg=CLR["text"],
                 font=("Segoe UI", 11)).pack(anchor="w", pady=(12, 0))

        # アプリ Top5
        tk.Label(self.summary_frame, text="\nアプリ Top 5",
                 bg=CLR["bg"], fg=CLR["text"],
                 font=("Segoe UI", 13, "bold")).pack(anchor="w", pady=(12, 6))

        for app, sec in sorted(app_totals.items(), key=lambda x: -x[1])[:5]:
            tk.Label(self.summary_frame,
                     text=f"  {app:<25} {_fmt_sec(sec)}",
                     bg=CLR["bg"], fg=CLR["text"],
                     font=("Consolas", 11)).pack(anchor="w")

    # --- インサイトタブ ---
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

        canvas = tk.Canvas(self.insights_frame, bg=CLR["bg"],
                           highlightthickness=0)
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
        icon = "⚠️" if insight.kind == "waste" else "💡"
        label = "無駄パターン" if insight.kind == "waste" else "自動化提案"

        card = tk.Frame(parent, bg=CLR["surface"],
                        highlightbackground=color,
                        highlightthickness=1)
        card.pack(fill="x", pady=6, padx=2)

        header = tk.Frame(card, bg=color)
        header.pack(fill="x")
        tk.Label(header, text=f"{icon} {label}",
                 bg=color, fg="white",
                 font=("Segoe UI", 9, "bold"),
                 padx=10, pady=3).pack(side="left")
        tk.Label(header, text=f"合計: {_fmt_sec(insight.total_sec)}",
                 bg=color, fg="white",
                 font=("Segoe UI", 9),
                 padx=10, pady=3).pack(side="right")

        body = tk.Frame(card, bg=CLR["surface"], padx=12, pady=8)
        body.pack(fill="x")
        tk.Label(body, text=insight.title,
                 bg=CLR["surface"], fg=CLR["text"],
                 font=("Segoe UI", 11, "bold"),
                 anchor="w").pack(fill="x")
        tk.Label(body, text=insight.description,
                 bg=CLR["surface"], fg=CLR["muted"],
                 font=("Segoe UI", 10),
                 wraplength=700, justify="left",
                 anchor="w").pack(fill="x", pady=(4, 0))
        if insight.apps:
            tk.Label(body, text="関連アプリ: " + ", ".join(insight.apps),
                     bg=CLR["surface"], fg=CLR["muted"],
                     font=("Segoe UI", 9, "italic")).pack(anchor="w", pady=(4, 0))

    # ----------------------------------------------------------
    # ロジック
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
        import os
        path = str(self.logger.get_csv_path().parent.resolve())
        if sys.platform == "win32":
            os.startfile(path)
        else:
            subprocess.Popen(["xdg-open", path])

    def _schedule_refresh(self):
        self._refresh_ui()
        self.after(self.POLL_MS, self._schedule_refresh)

    def _refresh_ui(self):
        records = self.logger.get_records()
        self.record_count_var.set(f"記録数: {len(records)}")

        # ログ一覧
        self.tree.delete(*self.tree.get_children())
        for r in reversed(records[-200:]):  # 直近200件
            self.tree.insert("", "end", values=(
                r.timestamp, r.app_name,
                r.window_title[:60], r.duration_sec, r.category,
            ))

        # サマリー・インサイト（軽量スレッドで更新）
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
