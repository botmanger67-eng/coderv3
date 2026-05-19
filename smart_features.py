import re

class SmartProjectDetector:
    @staticmethod
    def detect_language(prompt: str) -> str:
        p = prompt.lower()
        if any(x in p for x in ["python", "flask", "django", "fastapi"]):
            return "python"
        if any(x in p for x in ["php", "laravel", "codeigniter"]):
            return "php"
        if any(x in p for x in ["javascript", "node", "express", "react", "vue"]):
            return "javascript"
        return "python"  # default

    @staticmethod
    def detect_size(prompt: str) -> str:
        p = prompt.lower()
        if any(w in p for w in ["big","large","enterprise","saas","full","complete","production"]):
            return "big"
        if any(w in p for w in ["small","simple","basic","quick","chota"]):
            return "small"
        return "medium"

    @staticmethod
    def detect_type(prompt: str) -> str:
        p = prompt.lower()
        if any(w in p for w in ["web","site","frontend","react","vue","html"]):
            return "web_app"
        if any(w in p for w in ["api","rest","backend"]):
            return "api"
        if any(w in p for w in ["bot","telegram","discord"]):
            return "bot"
        if any(w in p for w in ["cli","command","tool"]):
            return "cli"
        return "general"