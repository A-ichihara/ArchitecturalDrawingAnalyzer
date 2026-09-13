"""
core.ai
部屋名判定や信頼度判定を補助するAIエンジンのインターフェースを提供します。
"""

from .interface import IAiEngine, NullAiEngine

__all__ = ["IAiEngine", "NullAiEngine"]
