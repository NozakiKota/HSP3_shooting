# Windows Activity Logger — 詳細仕様書

**バージョン**: 1.0.0-prototype
**最終更新**: 2026-03-14
**対象環境**: Windows 10/11 (Python 3.10+)、非 Windows では開発用モックで動作

---

## 目次

1. [システム概要](#1-システム概要)
2. [アーキテクチャ概要](#2-アーキテクチャ概要)
3. [データフロー図](#3-データフロー図)
4. [モジュール仕様](#4-モジュール仕様)
   - 4.1 [logger.py — コアロギングモジュール](#41-loggerpy--コアロギングモジュール)
   - 4.2 [pattern_detector.py — パターン検出モジュール](#42-pattern_detectorpy--パターン検出モジュール)
   - 4.3 [ui.py — UIモジュール](#43-uipy--uiモジュール)
   - 4.4 [main.py — エントリポイント](#44-mainpy--エントリポイント)
5. [データ構造仕様](#5-データ構造仕様)
6. [CSV出力仕様](#6-csv出力仕様)
7. [カテゴリ分類仕様](#7-カテゴリ分類仕様)
8. [パターン検出仕様](#8-パターン検出仕様)
9. [スレッドモデル](#9-スレッドモデル)
10. [依存関係](#10-依存関係)
11. [制限事項・既知の問題](#11-制限事項既知の問題)

---

## 1. システム概要

Windows のアクティブウィンドウを定期的に監視し、操作ログ（タイムスタンプ・アプリ名・ウィンドウタイトル・滞在時間・カテゴリ）を CSV ファイルへ記録するデスクトップアプリケーション。収集したデータをもとに、無駄な作業パターンの検出と自動化提案をリアルタイムで表示する。

### 機能一覧

| # | 機能 | 実装状態 |
|---|------|----------|
| 1 | アクティブウィンドウのポーリング監視 | ✅ 実装済み |
| 2 | ウィンドウ切り替え検出と滞在時間計測 | ✅ 実装済み |
| 3 | カテゴリ自動分類 | ✅ 実装済み |
| 4 | CSV ファイル出力（UTF-8 BOM付き） | ✅ 実装済み |
| 5 | リアルタイムログ一覧表示 | ✅ 実装済み |
| 6 | カテゴリ別・アプリ別サマリー（バーグラフ） | ✅ 実装済み |
| 7 | 無駄パターン検出（3種） | ✅ 実装済み |
| 8 | 自動化提案（3種） | ✅ 実装済み |
| 9 | Google カレンダー連携 | 🔜 未実装 |
| 10 | ML ベースのパターン検出 | 🔜 未実装 |

---

## 2. アーキテクチャ概要

```
┌─────────────────────────────────────────────────────────────┐
│                        main.py                              │
│               App() を生成して mainloop() 起動               │
└──────────────────────────┬──────────────────────────────────┘
                           │ 生成・制御
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                         ui.py (App)                         │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────────┐  │
│  │  ログ一覧タブ │  │ サマリータブ  │  │  インサイトタブ    │  │
│  └──────────────┘  └──────────────┘  └───────────────────┘  │
│              ↑ 3000ms ごとに UI 更新 (after ループ)           │
└──────────┬──────────────────────────┬───────────────────────┘
           │ start()/stop()           │ get_records()
           │ get_csv_path()           │ → list[ActivityRecord]
           ▼                          ▼
┌──────────────────────┐    ┌─────────────────────────────────┐
│   logger.py          │    │   pattern_detector.py           │
│   ActivityLogger     │    │   analyze(records)              │
│                      │    │                                 │
│  ┌────────────────┐  │    │  _detect_frequent_switches()    │
│  │  監視スレッド   │  │    │  _detect_long_sessions()        │
│  │  (_loop)       │  │    │  _detect_repetitive_titles()    │
│  └───────┬────────┘  │    │  _suggest_automation()          │
│          │           │    └─────────────────────────────────┘
│    win32gui/psutil   │
│    でウィンドウ取得   │
│          │           │
│    _save_record()    │
│    ┌─────┴────────┐  │
│    │ メモリ保持   │  │
│    │ CSV 書き込み │  │
│    └─────────────┘  │
└──────────────────────┘
           │
           ▼
    logs/activity_YYYYMMDD_HHMMSS.csv
```

---

## 3. データフロー図

```
  [OS: Windows API]
       │
       │ win32gui.GetForegroundWindow()
       │ win32process.GetWindowThreadProcessId()
       │ psutil.Process(pid).name()
       ▼
  _get_active_window_info()
       │
       │ returns (app_name: str, window_title: str)
       ▼
  ActivityLogger._loop()   ←── threading.Event.wait(5s) ──┐
       │                                                    │
       │ ウィンドウ変化を検出したとき                          │
       │                                                    │
       ├── _categorize(app_name, window_title)              │
       │       │ returns category: str                      │
       │       ▼                                            │
       ├── ActivityRecord を生成                             │
       │       │                                            │
       ├── _save_record(record)                             │
       │       ├── self._records.append(record)  [メモリ]   │
       │       └── CSV ファイルに1行追記          [ディスク]  │
       │                                                    │
       └────────────────────────────────────────────────────┘

  [UI スレッド (tkinter mainloop)]
       │
       │ App.after(3000ms) → _refresh_ui()
       ▼
  ActivityLogger.get_records()
       │ returns list[ActivityRecord]  (スレッドセーフコピー)
       │
       ├──→ ログ一覧タブ: Treeview に直近200件を表示
       │
       ├──→ サマリータブ: _refresh_summary(records)
       │         │ カテゴリ別・アプリ別に集計してバーグラフ描画
       │
       └──→ インサイトタブ: _refresh_insights(records)
                 │
                 └──→ pattern_detector.analyze(records)
                           │
                           ├── _detect_frequent_switches()
                           ├── _detect_long_sessions()
                           ├── _detect_repetitive_titles()
                           └── _suggest_automation()
                                    │
                                    └── list[PatternInsight] → カード表示
```

---

## 4. モジュール仕様

---

### 4.1 `logger.py` — コアロギングモジュール

**役割**: Windows API を通じてアクティブウィンドウを監視し、操作ログをメモリと CSV に記録する。

---

#### データクラス: `ActivityRecord`

```python
@dataclass
class ActivityRecord:
    timestamp:    str    # 操作開始時刻 "YYYY-MM-DD HH:MM:SS"
    app_name:     str    # 実行ファイル名（.exe 除去済み）
    window_title: str    # ウィンドウタイトル文字列
    duration_sec: float  # そのウィンドウにいた秒数（小数点1桁）
    category:     str    # 分類カテゴリ（後述）
```

---

#### プライベート関数: `_get_active_window_info()`

| 項目 | 内容 |
|------|------|
| **目的** | 現在フォアグラウンドにあるウィンドウの情報を取得する |
| **入力** | なし |
| **出力** | `tuple[str, str]` — `(app_name, window_title)` |
| **Windows** | `win32gui.GetForegroundWindow()` → HWND 取得 → `win32gui.GetWindowText()` でタイトル取得 → `win32process.GetWindowThreadProcessId()` で PID 取得 → `psutil.Process(pid).name()` でプロセス名取得し `.exe` を除去 |
| **非 Windows** | `("MockApp", "Mock Window Title")` を返す（開発用モック） |
| **例外処理** | 取得失敗時は `("Unknown", "")` を返す（クラッシュしない） |

---

#### プライベート関数: `_categorize(app_name, title)`

| 項目 | 内容 |
|------|------|
| **目的** | アプリ名とウィンドウタイトルからカテゴリを推定する |
| **入力** | `app_name: str`, `title: str` |
| **出力** | `str` — カテゴリ名（詳細は [第7章](#7-カテゴリ分類仕様) 参照） |
| **照合方法** | キーワードリストに対して部分一致（大文字小文字無視）。最初にマッチしたカテゴリを返す。どれにもマッチしなければ `"other"` |

---

#### クラス: `ActivityLogger`

**コンストラクタ**

```python
ActivityLogger(output_dir: str = "logs", interval: int = 5)
```

| パラメータ | 型 | デフォルト | 説明 |
|-----------|-----|-----------|------|
| `output_dir` | `str` | `"logs"` | CSV 保存先ディレクトリ（なければ自動作成） |
| `interval` | `int` | `5` | ポーリング間隔（秒） |

初期化時の副作用:
- `output_dir` ディレクトリを `mkdir -p` で作成
- `activity_YYYYMMDD_HHMMSS.csv` をヘッダー行付きで新規作成
- `threading.Lock` と `threading.Event` を初期化

---

**公開メソッド一覧**

| メソッド | 入力 | 出力 | 説明 |
|---------|------|------|------|
| `start()` | なし | `None` | 監視スレッドを起動。すでに動作中なら無視 |
| `stop()` | なし | `None` | `_stop_event` をセットしスレッド終了を待機（タイムアウト: `interval + 2` 秒） |
| `get_records()` | なし | `list[ActivityRecord]` | `_lock` 保護下でリストのコピーを返す（スレッドセーフ） |
| `get_csv_path()` | なし | `pathlib.Path` | 現在のセッションの CSV ファイルパスを返す |
| `is_running()` | なし | `bool` | 監視スレッドが生存しているか返す |

---

**内部メソッド: `_loop()`**

監視スレッドのメインループ。フロー:

```
初期化: prev_app = "", prev_title = "", prev_time = now

while not stop_event:
    (app, title) = _get_active_window_info()
    now = datetime.now()

    if app != prev_app or title != prev_title:  # ウィンドウ切り替え検出
        if prev_app != "":                       # 初回は記録しない
            duration = (now - prev_time).total_seconds()
            record = ActivityRecord(
                timestamp  = prev_time.strftime("%Y-%m-%d %H:%M:%S"),
                app_name   = prev_app,
                window_title = prev_title,
                duration_sec = round(duration, 1),
                category   = _categorize(prev_app, prev_title)
            )
            _save_record(record)
        prev_app, prev_title, prev_time = app, title, now

    stop_event.wait(interval)   # ← ここで interval 秒スリープ（停止信号で即起床）
```

> **設計上の注意**: 記録は「離れた瞬間」に行う。現在のウィンドウは `duration_sec=0` で pending 状態となり、次の切り替えで確定記録される。

---

**内部メソッド: `_save_record(record)`**

| 処理 | 詳細 |
|------|------|
| メモリ保持 | `threading.Lock` 保護下で `self._records` リストに `append` |
| ディスク書き込み | CSV ファイルに `csv.writer` で1行追記（`encoding="utf-8-sig"` = UTF-8 BOM付き、Excel対応） |

---

### 4.2 `pattern_detector.py` — パターン検出モジュール

**役割**: `ActivityRecord` リストを受け取り、無駄パターン・自動化提案を `PatternInsight` リストとして返す。副作用なし（純粋関数群）。

---

#### データクラス: `PatternInsight`

```python
@dataclass
class PatternInsight:
    kind:        str        # "waste" | "automation"
    title:       str        # インサイトの短いタイトル
    description: str        # 詳細説明文
    apps:        list[str]  # 関連するアプリ名リスト
    total_sec:   float      # 対象操作の合計秒数
```

---

#### 公開関数: `analyze(records)`

| 項目 | 内容 |
|------|------|
| **入力** | `records: list[ActivityRecord]` |
| **出力** | `list[PatternInsight]` |
| **空入力** | `records` が空の場合 `[]` を返す |
| **処理内容** | 以下4つの検出関数を順に呼び出し、結果を結合して返す |

呼び出し順:
1. `_detect_frequent_switches(records)`
2. `_detect_long_sessions(records)`
3. `_detect_repetitive_titles(records)`
4. `_suggest_automation(records)`

---

#### プライベート関数: `_detect_frequent_switches(records)`

**目的**: 短時間で頻繁にアプリを行き来するマルチタスクパターンを検出する。

| 項目 | 内容 |
|------|------|
| **入力** | `list[ActivityRecord]` |
| **出力** | `list[PatternInsight]`（最大1件） |
| **アルゴリズム** | スライディングウィンドウ（サイズ10）で走査。ウィンドウ内に `duration_sec < 30` のレコードが **6件以上**あれば検出 |
| **検出時の内容** | 上位3アプリ、ウィンドウ内合計時間を集計 |
| **重複回避** | 最初の1件のみ返す（`break`） |

**発火条件**:
```
連続10操作中に、30秒未満の操作が6回以上
```

---

#### プライベート関数: `_detect_long_sessions(records)`

**目的**: 同一アプリへの長時間連続利用を検出する。

| 項目 | 内容 |
|------|------|
| **入力** | `list[ActivityRecord]` |
| **出力** | `list[PatternInsight]`（アプリ数分） |
| **アルゴリズム** | アプリ名をキーに `duration_sec` を合計。合計が **3600秒（1時間）以上**なら検出 |
| **発火条件** | `app_total >= 3600.0` |

---

#### プライベート関数: `_detect_repetitive_titles(records)`

**目的**: 同一ウィンドウタイトルへの繰り返しアクセスを検出する。

| 項目 | 内容 |
|------|------|
| **入力** | `list[ActivityRecord]` |
| **出力** | `list[PatternInsight]`（最大5件） |
| **アルゴリズム** | `Counter` でウィンドウタイトルの出現回数を集計。上位5タイトルから **5回以上**出現したものを検出 |
| **発火条件** | `title_count >= 5` かつタイトルが空文字でない |

---

#### プライベート関数: `_suggest_automation(records)`

**目的**: カテゴリ別利用時間からスクリプト化・効率化を提案する。

| 項目 | 内容 |
|------|------|
| **入力** | `list[ActivityRecord]` |
| **出力** | `list[PatternInsight]`（最大3件） |
| **アルゴリズム** | カテゴリ別に `duration_sec` を合計し、以下の閾値で判定 |

提案の発火条件:

| 提案タイトル | 条件 |
|-------------|------|
| ファイル整理の自動化 | `file_manager >= 600秒`（10分） |
| コミュニケーション対応の効率化 | `communication >= 3600秒`（1時間） |
| 情報収集の効率化 | `browser >= 1800秒`（30分） **かつ** `development < 600秒`（10分） |

---

### 4.3 `ui.py` — UI モジュール

**役割**: tkinter ベースのデスクトップ GUI。3タブ構成で、`ActivityLogger` からデータを取得して表示し、`pattern_detector.analyze()` でインサイトを生成・表示する。

---

#### 定数: `CLR`

ダークテーマのカラーパレット（dict）。

| キー | 値（hex） | 用途 |
|------|-----------|------|
| `bg` | `#1e1e2e` | ウィンドウ背景 |
| `surface` | `#2a2a3e` | カード・ステータスバー背景 |
| `primary` | `#7c3aed` | ヘッダー・選択中タブ・選択行 |
| `success` | `#22c55e` | 開始ボタン・記録中インジケータ |
| `warning` | `#f59e0b` | 無駄パターンカードの色 |
| `danger` | `#ef4444` | 停止ボタン・meeting カテゴリ |
| `text` | `#e2e8f0` | メインテキスト |
| `muted` | `#94a3b8` | 補助テキスト・ステータス |
| `border` | `#374151` | バーグラフ背景 |

---

#### クラス: `App(tk.Tk)`

**コンストラクタ**

| 処理 | 詳細 |
|------|------|
| ウィンドウ設定 | タイトル・サイズ(900×640)・背景色・リサイズ可 |
| `ActivityLogger` 生成 | `output_dir="logs"`, `interval=5` |
| UI 構築 | `_build_ui()` 呼び出し |
| 更新ループ開始 | `_schedule_refresh()` 呼び出し |

---

**UI 構成要素**

```
┌──────────────────────────────────────────────────────┐
│ [ヘッダー]  Windows Activity Logger   [▶記録開始] [📂ログを開く] │
├──────────────────────────────────────────────────────┤
│ [ステータスバー] ● 停止中                     記録数: 0 │
├──────────────────────────────────────────────────────┤
│ [  ログ一覧  ] [  サマリー  ] [  インサイト  ]          │
├──────────────────────────────────────────────────────┤
│                                                      │
│              タブコンテンツ                            │
│                                                      │
└──────────────────────────────────────────────────────┘
```

---

**メソッド: `_build_log_tab()`**

ログ一覧タブを構築する。

| 要素 | 仕様 |
|------|------|
| ウィジェット | `ttk.Treeview` + 縦スクロールバー |
| 表示列 | タイムスタンプ(150px)・アプリ(120px)・ウィンドウタイトル(330px)・秒数(70px)・カテゴリ(90px) |
| 表示件数 | 最新順で直近 **200件** |
| スタイル | `Log.Treeview`（ダークテーマ、選択行は primary 色） |

---

**メソッド: `_refresh_summary(records)`**

サマリータブを再描画する（既存ウィジェットを全削除してから再生成）。

| 処理 | 詳細 |
|------|------|
| カテゴリ別集計 | `defaultdict(float)` で `duration_sec` を合計 |
| バーグラフ | 横幅 300px の背景 Frame に、割合に応じた幅の色付き Frame を `place()` で重ね描き |
| パーセント計算 | `pct = カテゴリ合計 / 全合計 × 100` |
| アプリ Top5 | `app_totals` を降順ソートし上位5件を表示 |

---

**メソッド: `_refresh_insights(records)`**

インサイトタブを再描画する。`pattern_detector.analyze()` を呼び出してカードを生成。

スクロール可能領域の構成:
```
Canvas (fill, expand)
  └── scroll_frame (Frame)
        └── カード × N  (_render_insight_card で生成)
```

---

**メソッド: `_render_insight_card(parent, insight)`**

| 入力 | 型 |
|------|-----|
| `parent` | `tk.Frame` — スクロール内コンテナ |
| `insight` | `PatternInsight` |

カード構造:
```
┌─────────────────────────────────────────────┐  ← border (warning or success)
│ [ヘッダー行: アイコン + ラベル]   [合計時間]  │  ← 色付き背景
├─────────────────────────────────────────────┤
│ タイトル（太字）                              │
│ 説明文（wraplength=700）                     │
│ 関連アプリ（斜体）                            │
└─────────────────────────────────────────────┘
```

| `kind` 値 | 色 | アイコン |
|-----------|-----|---------|
| `"waste"` | warning (`#f59e0b`) | ⚠️ |
| `"automation"` | success (`#22c55e`) | 💡 |

---

**メソッド: `_toggle_logging()`**

記録開始・停止のトグル制御。

| 状態 | 操作 | UI変化 |
|------|------|--------|
| 停止中 → 記録中 | `logger.start()` | ボタン「⏹ 記録停止」(danger色)、ステータスドット成功色 |
| 記録中 → 停止中 | `logger.stop()` | ボタン「▶ 記録開始」(success色)、ステータスドットミュート色 |

---

**メソッド: `_schedule_refresh()` / `_refresh_ui()`**

```
_schedule_refresh()
  └── _refresh_ui()
        ├── logger.get_records()  → records
        ├── ログ一覧: Treeview 全行削除 → 直近200件を再挿入
        └── threading.Thread(_bg_refresh) → daemon スレッド起動
              └── after(0, _refresh_summary, records)
              └── after(0, _refresh_insights, records)

  └── after(3000ms) → _schedule_refresh()  ← 再帰スケジュール
```

> **注意**: `_refresh_summary` / `_refresh_insights` は `after(0, ...)` で tkinter メインスレッドに委譲するため、スレッドセーフ。

---

**ユーティリティ関数: `_fmt_sec(sec)`**

| 入力 | `sec: float` — 秒数 |
|------|------|
| **出力** | 人間が読みやすい文字列 |

| 条件 | 出力例 |
|------|--------|
| `sec >= 3600` | `"2h 05m"` |
| `60 <= sec < 3600` | `"15m 30s"` |
| `sec < 60` | `"45s"` |

---

### 4.4 `main.py` — エントリポイント

| 項目 | 内容 |
|------|------|
| **役割** | `sys.path` にプロジェクトディレクトリを追加し `App` を起動する |
| **入力** | コマンドライン引数なし |
| **出力** | なし（GUI イベントループ） |
| **終了条件** | ウィンドウを閉じると `mainloop()` が返り、プロセス終了 |

```python
def main():
    app = App()
    app.mainloop()
```

---

## 5. データ構造仕様

### `ActivityRecord` フィールド詳細

| フィールド | 型 | 形式 | 例 |
|-----------|-----|------|----|
| `timestamp` | `str` | `"YYYY-MM-DD HH:MM:SS"` | `"2026-03-14 09:23:45"` |
| `app_name` | `str` | `.exe` 除去済みのプロセス名 | `"chrome"`, `"Code"` |
| `window_title` | `str` | OS から取得したウィンドウタイトル | `"Google - Chrome"` |
| `duration_sec` | `float` | 小数点1桁に丸め済み | `42.5` |
| `category` | `str` | カテゴリ識別子（7種 + other） | `"browser"` |

### `PatternInsight` フィールド詳細

| フィールド | 型 | 値域 | 説明 |
|-----------|-----|------|------|
| `kind` | `str` | `"waste"` \| `"automation"` | インサイト種別 |
| `title` | `str` | 任意 | UI カードのタイトル |
| `description` | `str` | 任意 | 詳細説明文 |
| `apps` | `list[str]` | 0件以上 | 関連アプリ名リスト |
| `total_sec` | `float` | 0.0 以上 | 対象操作の合計秒数 |

---

## 6. CSV 出力仕様

### ファイル命名規則

```
logs/activity_YYYYMMDD_HHMMSS.csv
```

- セッション開始時（`ActivityLogger.__init__`）に1ファイル生成
- 複数セッションを実行した場合は複数ファイルが生成される

### カラム定義

| 列番号 | カラム名 | 型 | 説明 |
|--------|---------|-----|------|
| 0 | `timestamp` | 文字列 | 操作開始時刻 |
| 1 | `app_name` | 文字列 | アプリケーション名 |
| 2 | `window_title` | 文字列 | ウィンドウタイトル |
| 3 | `duration_sec` | 数値 | 滞在時間（秒） |
| 4 | `category` | 文字列 | カテゴリ |

### エンコーディング

`utf-8-sig`（UTF-8 BOM付き） — Excel で直接開いても文字化けしない。

### サンプル

```csv
timestamp,app_name,window_title,duration_sec,category
2026-03-14 09:00:05,chrome,Google ドライブ - Google Chrome,125.3,browser
2026-03-14 09:02:10,Code,SPEC.md - Windows Activity Logger,310.0,development
2026-03-14 09:07:20,Teams,Microsoft Teams,45.2,communication
```

---

## 7. カテゴリ分類仕様

### 分類ロジック

アプリ名とウィンドウタイトルをそれぞれ小文字化し、以下のキーワードリストと部分一致で照合。**最初にマッチしたカテゴリを採用**（優先順位 = 定義順）。

### カテゴリ一覧

| カテゴリ | キーワード | UI カラー |
|---------|-----------|-----------|
| `browser` | chrome, firefox, edge, safari, opera | `#3b82f6`（青） |
| `communication` | teams, slack, zoom, outlook, thunderbird, discord | `#8b5cf6`（紫） |
| `development` | code, pycharm, idea, vim, notepad++, sublime, cursor | `#22c55e`（緑） |
| `office` | excel, word, powerpoint, onenote, libreoffice | `#f59e0b`（黄） |
| `file_manager` | explorer, finder | `#06b6d4`（シアン） |
| `terminal` | cmd, powershell, terminal, bash, wsl | `#ec4899`（ピンク） |
| `meeting` | teams, zoom, webex, meet | `#ef4444`（赤） |
| `other` | （上記にマッチしない全て） | `#6b7280`（グレー） |

> **注意**: `teams` と `zoom` は `communication` と `meeting` の両方にキーワードが含まれる。`communication` が先に定義されているため、これらは常に `communication` に分類される。

---

## 8. パターン検出仕様

### 検出フロー

```
analyze(records)
  │
  ├── [1] _detect_frequent_switches
  │       閾値: 10操作ウィンドウ内に duration_sec < 30 が 6件以上
  │       出力: 最大1件の "waste" インサイト
  │
  ├── [2] _detect_long_sessions
  │       閾値: 同一アプリの累計 >= 3600秒
  │       出力: 該当アプリ数分の "waste" インサイト
  │
  ├── [3] _detect_repetitive_titles
  │       閾値: 同一タイトルへのアクセス >= 5回（上位5タイトルを対象）
  │       出力: 最大5件の "waste" インサイト
  │
  └── [4] _suggest_automation
          条件A: file_manager >= 600秒  → "ファイル整理の自動化"
          条件B: communication >= 3600秒 → "コミュニケーション対応の効率化"
          条件C: browser >= 1800秒 AND development < 600秒 → "情報収集の効率化"
          出力: 最大3件の "automation" インサイト
```

### 検出閾値一覧

| 検出名 | 指標 | 閾値 | 種別 |
|--------|-----|------|------|
| 頻繁な切り替え | 10操作内の短操作数 | ≥ 6件 (各 < 30秒) | waste |
| 長時間利用 | 同一アプリ合計時間 | ≥ 3600秒 (1時間) | waste |
| 繰り返しアクセス | 同一タイトルアクセス回数 | ≥ 5回 | waste |
| ファイル整理提案 | file_manager カテゴリ合計 | ≥ 600秒 (10分) | automation |
| コミュニケーション提案 | communication カテゴリ合計 | ≥ 3600秒 (1時間) | automation |
| 情報収集提案 | browser合計 AND NOT development | browser ≥ 1800秒 かつ development < 600秒 | automation |

---

## 9. スレッドモデル

```
プロセス
├── [Main Thread] tkinter mainloop
│     │ UI イベント処理
│     │ after(3000ms) → _refresh_ui()
│     │   └── after(0, _refresh_summary)
│     │   └── after(0, _refresh_insights)
│     └── ユーザー操作イベント
│
└── [Daemon Thread] ActivityLogger._loop
      │ win32 API ポーリング（5秒間隔）
      │ _save_record() — Lock でメモリ保護
      └── CSV 書き込み
```

**スレッドセーフ設計**:

| 共有リソース | 保護方法 |
|-------------|---------|
| `ActivityLogger._records` | `threading.Lock` で read/write を保護 |
| tkinter ウィジェット操作 | `after(0, fn)` でメインスレッドに委譲（tkinter はスレッドセーフでないため） |
| CSV ファイル | 監視スレッドのみが書き込むため排他制御不要 |
| `_stop_event` | `threading.Event`（スレッドセーフ） |

---

## 10. 依存関係

### Python 標準ライブラリ（追加インストール不要）

| モジュール | 用途 |
|-----------|------|
| `csv` | CSV 読み書き |
| `threading` | バックグラウンドスレッド・Lock・Event |
| `datetime` | タイムスタンプ生成・経過時間計算 |
| `pathlib` | ファイルパス操作 |
| `dataclasses` | `ActivityRecord`, `PatternInsight` 定義 |
| `collections` | `Counter`, `defaultdict` |
| `tkinter` / `tkinter.ttk` | GUI フレームワーク |
| `subprocess` | Linux でのフォルダ open |
| `sys` | `sys.path` 操作・プラットフォーム判定 |

### サードパーティライブラリ（要インストール）

| パッケージ | バージョン | 用途 | 備考 |
|-----------|-----------|------|------|
| `pywin32` | ≥ 306 | `win32gui`, `win32process` — フォアグラウンドウィンドウ取得 | Windows のみ |
| `psutil` | ≥ 5.9.0 | PID からプロセス名取得 | Windows のみ必須 |

### インストール

```bash
pip install -r windows_activity_logger/requirements.txt
```

---

## 11. 制限事項・既知の問題

| # | 制限 | 影響 | 将来対応案 |
|---|------|------|-----------|
| 1 | ポーリング間隔が5秒のため、5秒未満のウィンドウ切り替えは記録されない | 瞬間的なウィンドウ切り替えが欠落する可能性 | `SetWinEventHook` によるイベント駆動方式に変更 |
| 2 | カテゴリ分類はキーワード前方一致のみ | 未登録アプリは全て `other` になる | ユーザー定義カテゴリ設定の追加 |
| 3 | `teams` / `zoom` は `communication` に固定分類（`meeting` にはならない） | 会議時間を `meeting` として区別できない | カテゴリ優先順位の設定、またはウィンドウタイトルでの詳細判定 |
| 4 | UI の `_refresh_summary` / `_refresh_insights` はウィジェットを毎回全削除・再生成する | レコード数が増えると UI 更新がわずかに重くなる | 差分更新またはキャッシュの導入 |
| 5 | ログは `logs/` ディレクトリへの相対パスで保存 | `main.py` の実行ディレクトリ依存 | 絶対パス（`~/.windows_activity_logger/`）に変更 |
| 6 | 非 Windows 環境ではモックデータ `("MockApp", "Mock Window Title")` が固定で返る | 実際の操作ログは収集できない | X11/Wayland 対応や macOS 対応の追加 |
| 7 | CSV は追記専用で、過去セッションのデータは UI に読み込まれない | アプリを再起動すると過去ログが表示されない | 起動時に既存 CSV を読み込む機能の追加 |
