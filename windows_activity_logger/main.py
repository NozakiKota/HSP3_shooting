"""
Windows Activity Logger - エントリポイント
"""
import sys
from pathlib import Path

# プロジェクトルートを sys.path に追加
sys.path.insert(0, str(Path(__file__).parent))

from ui import App


def main():
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
