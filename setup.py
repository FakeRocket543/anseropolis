#!/usr/bin/env python3
"""anseropolis setup — 一鍵安裝所有依賴。"""

import subprocess
import sys


def run(cmd, desc):
    print(f"\n{'─'*40}")
    print(f"⏳ {desc}…")
    print(f"   $ {cmd}")
    result = subprocess.run(cmd, shell=True)
    if result.returncode != 0:
        print(f"   ❌ 失敗！請手動執行上面的指令。")
        return False
    print(f"   ✅ 完成")
    return True


def main():
    print("🪿 Anseropolis 環境設定")
    print("=" * 40)

    v = sys.version_info
    if v < (3, 11):
        print(f"❌ Python {v.major}.{v.minor} 太舊，需要 3.11+")
        sys.exit(1)
    print(f"✅ Python {v.major}.{v.minor}.{v.micro}")

    run(f"{sys.executable} -m pip install mlx-lm playwright numpy jieba pyyaml", "安裝核心依賴")
    run("playwright install chromium", "安裝 Chromium")

    # Optional: CKIP
    print(f"\n{'─'*40}")
    print("⏳ 安裝 CKIP 斷詞（選配，不裝會用 jieba 替代）…")
    subprocess.run(f"{sys.executable} -m pip install ckip-transformers", shell=True)

    # Pre-download model
    print(f"\n{'─'*40}")
    print("⏳ 下載 LLM 模型（首次約 4.5GB）…")
    try:
        from mlx_lm import load
        load("mlx-community/Ministral-8B-Instruct-2412-4bit")
        print("   ✅ 模型就緒")
    except ImportError:
        print("   ⚠️  mlx-lm 未安裝，LLM 步驟可在 Claude Code 中由 AI 代勞")
    except Exception as e:
        print(f"   ⚠️  {e}")

    print(f"\n{'='*40}")
    print("🎉 設定完成！試試看：")
    print('   python3 -m src.run -i')
    print('   python3 -m src.run --theme emerald "網傳..."')


if __name__ == "__main__":
    main()
