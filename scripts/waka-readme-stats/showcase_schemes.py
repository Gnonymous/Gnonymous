"""
WakaTime Showcase 方案生成器
整合到 waka-readme-stats 部署脚本
"""
from datetime import datetime, timedelta, timezone as dt_timezone
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Any


# 进度条配置
BAR_FILLED = "█"
BAR_EMPTY = "░"
BAR_LENGTH = 25
APP_RUNTIME_LOG_REPO_PATH = "docs/wakatime_app_runtime_log.md"
APP_RUNTIME_LOG_PATH = Path(__file__).resolve().parents[2] / APP_RUNTIME_LOG_REPO_PATH

# Editor 分类映射
CATEGORY_EMOJI = {
    "Coding": "💻", "Notes/Docs": "📝",
    "Communication": "💬", "Entertainment": "🎮", "Browser": "🌐", "Other": "🧩",
}


def classify_editor(name: str) -> str:
    """分类 Editor/App"""
    raw = name or "Unknown"
    lowered = raw.lower()

    exact_map = {
        # Coding / terminals
        "antigravity": "Coding",
        "ghostty": "Coding",
        "terminal": "Coding",
        "apple terminal": "Coding",
        "orca": "Coding",
        "workbuddy": "Coding",
        # Browser-like AI/web apps stay in Browser to keep the public categories compact.
        "chrome": "Browser",
        "google chrome": "Browser",
        "chatgptatlas": "Browser",
        "chatgpt atlas": "Browser",
        "atlas": "Browser",
        # Notes and document tools
        "zotero": "Notes/Docs",
        "obsidian": "Notes/Docs",
        "notion": "Notes/Docs",
        "miaoyan": "Notes/Docs",
        "妙言": "Notes/Docs",
        "notes": "Notes/Docs",
        "apple notes": "Notes/Docs",
        "wpsoffice": "Notes/Docs",
        "wps office": "Notes/Docs",
        # Communication
        "wechat": "Communication",
        "微信": "Communication",
        "weixin": "Communication",
        "microsoftoutlook": "Communication",
        "microsoft outlook": "Communication",
        "outlook": "Communication",
        "zoom": "Communication",
        "zoom.us": "Communication",
        # Entertainment
        "music": "Entertainment",
        "apple music": "Entertainment",
        "抖音": "Entertainment",
        "douyin": "Entertainment",
        "tiktok": "Entertainment",
    }
    exact_category = exact_map.get(lowered)
    if exact_category:
        return exact_category

    def has_any(words: list) -> bool:
        return any(word in lowered for word in words)

    if has_any([
        "antigravity", "vscode", "visual studio code", "cursor",
        "intellij", "pycharm", "webstorm", "goland", "clion",
        "xcode", "vim", "neovim", "emacs", "sublime", "atom", "jetbrains",
        "terminal", "ghostty", "orca", "workbuddy", "copilot", "codeium", "tabnine",
    ]):
        return "Coding"

    if has_any(["抖音", "douyin", "tiktok", "bilibili", "youtube", "netflix", "music"]):
        return "Entertainment"

    if has_any(["notion", "obsidian", "zotero", "miaoyan", "妙言", "evernote", "roam", "logseq", "typora", "notes", "notebook", "wps", "feishu", "飞书"]):
        return "Notes/Docs"

    if has_any(["outlook", "gmail", "mail", "calendar", "teams", "zoom"]):
        return "Communication"

    if has_any(["chrome", "safari", "firefox", "edge", "arc", "brave", "atlas", "chatgpt"]):
        return "Browser"

    if has_any(["slack", "discord", "telegram", "lark", "messenger", "wechat", "微信", "weixin"]):
        return "Communication"

    return "Other"


def make_progress_bar(percent: float, length: int = BAR_LENGTH) -> str:
    filled = int(length * percent / 100)
    empty = length - filled
    return BAR_FILLED * filled + BAR_EMPTY * empty


def format_time(seconds: float) -> str:
    if seconds < 60:
        return f"{int(seconds)} secs"
    elif seconds < 3600:
        return f"{int(seconds / 60)} mins"
    else:
        hours = int(seconds / 3600)
        mins = int((seconds % 3600) / 60)
        return f"{hours} hrs {mins} mins" if mins > 0 else f"{hours} hrs"


def write_app_runtime_log(editor_totals: Dict[str, float], category_stats: Dict[str, Dict], timezone: str):
    """Write hidden app-level runtime details for local/CI audit."""
    total = sum(editor_totals.values())
    if total <= 0:
        return

    APP_RUNTIME_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    generated_at = datetime.now(dt_timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    lines = [
        "# WakaTime App Runtime Log",
        "",
        "This file is generated for audit/debugging. README only displays category totals.",
        "",
        f"- Generated at: {generated_at}",
        f"- Timezone: {timezone}",
        f"- Total tracked app time: {format_time(total)}",
        "",
        "## Category Summary",
        "",
        "| Category | Time | Percent |",
        "| --- | ---: | ---: |",
    ]

    sorted_cats = sorted(category_stats.items(), key=lambda x: x[1]["seconds"], reverse=True)
    for category, info in sorted_cats:
        percent = info["seconds"] / total * 100
        lines.append(f"| `{category}` | {format_time(info['seconds'])} | {percent:5.2f}% |")

    lines.extend(["", "## App Details", ""])
    for category, info in sorted_cats:
        apps = sorted(info["apps"], key=lambda x: x[1], reverse=True)
        category_percent = info["seconds"] / total * 100
        lines.extend([
            f"### {category}",
            "",
            f"- Category total: {format_time(info['seconds'])} ({category_percent:5.2f}%)",
            "",
            "| App | Time | Overall Percent | Category Percent |",
            "| --- | ---: | ---: | ---: |",
        ])
        for app, seconds in apps:
            overall_percent = seconds / total * 100
            category_app_percent = seconds / info["seconds"] * 100 if info["seconds"] else 0
            lines.append(f"| `{app}` | {format_time(seconds)} | {overall_percent:5.2f}% | {category_app_percent:5.2f}% |")
        lines.append("")

    APP_RUNTIME_LOG_PATH.write_text("\n".join(lines), encoding="utf-8")


def scheme_time_period(summaries_data: Dict, durations_data: List[Dict], timezone_str: str) -> str:
    """
    时段分布 (Last 7 Days)
    基于 WakaTime durations API 精确计算每个时段的工作时间
    
    :param summaries_data: WakaTime summaries API 响应
    :param durations_data: 所有 7 天的 durations 数据合并列表
    :param timezone_str: 用户时区字符串 (如 "Asia/Shanghai")
    """
    if not durations_data:
        return ""
    
    # 尝试解析时区
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(timezone_str) if timezone_str else None
    except Exception:
        tz = None
    
    # 时段定义 (参考 generate_showcase.py 的 bucket_circadian)
    periods = {
        "Morning": {"emoji": "🌞", "seconds": 0.0, "range": (6, 12)},   # 06:00-12:00
        "Daytime": {"emoji": "🌆", "seconds": 0.0, "range": (12, 18)}, # 12:00-18:00
        "Evening": {"emoji": "🌃", "seconds": 0.0, "range": (18, 24)}, # 18:00-24:00
        "Night": {"emoji": "🌙", "seconds": 0.0, "range": (0, 6)},     # 00:00-06:00
    }
    
    def to_local(ts: float):
        """将 Unix 时间戳转换为本地时间"""
        dt = datetime.fromtimestamp(ts, tz=dt_timezone.utc)
        if tz:
            return dt.astimezone(tz)
        return dt
    
    def get_period_for_hour(hour: int) -> str:
        """根据小时获取对应的时段"""
        if 0 <= hour < 6:
            return "Night"
        elif 6 <= hour < 12:
            return "Morning"
        elif 12 <= hour < 18:
            return "Daytime"
        else:
            return "Evening"
    
    # 遍历所有 durations，按小时精确分配到各时段
    for d in durations_data:
        start_ts = float(d.get("time", 0))
        dur = float(d.get("duration", 0))
        if dur <= 0:
            continue
        
        start = to_local(start_ts)
        end = to_local(start_ts + dur)
        current = start
        
        # 按小时边界切分并分配
        while current < end:
            next_hour = (current.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1))
            segment_end = min(end, next_hour)
            seconds = (segment_end - current).total_seconds()
            
            period_name = get_period_for_hour(current.hour)
            periods[period_name]["seconds"] += seconds
            
            current = segment_end
    
    total = sum(p["seconds"] for p in periods.values())
    if total == 0:
        return ""
    
    # 确定主要工作时段
    max_period = max(periods.items(), key=lambda x: x[1]["seconds"])
    titles = {
        "Morning": "**I'm an Early 🐤**",
        "Daytime": "**I'm a Daytime ☀️**",
        "Evening": "**I'm an Evening 🦉**",
        "Night": "**I'm a Night 🦇**",
    }
    
    lines = [titles[max_period[0]], "", "```text"]
    for name, info in periods.items():
        percent = (info["seconds"] / total * 100) if total > 0 else 0
        bar = make_progress_bar(percent)
        time_str = format_time(info["seconds"])
        lines.append(f"{info['emoji']} {name:20} {time_str:20} {bar}   {percent:5.2f} %")
    lines.append("```")
    return "\n".join(lines) + "\n\n"


def scheme_app_category_with_goals(summaries_data: Dict, goals_data: Dict, timezone: str) -> str:
    """App 分类统计 + 编程目标"""
    if not summaries_data or "data" not in summaries_data:
        return ""
    
    # 汇总 editors 数据
    editor_totals = defaultdict(float)
    for day_data in summaries_data["data"]:
        for editor in day_data.get("editors", []):
            name = editor.get("name", "Unknown")
            seconds = editor.get("total_seconds", 0)
            editor_totals[name] += seconds
    
    if not editor_totals:
        return ""
    
    # 按类别汇总
    category_stats = defaultdict(lambda: {"seconds": 0, "apps": []})
    for name, seconds in editor_totals.items():
        cat = classify_editor(name)
        category_stats[cat]["seconds"] += seconds
        category_stats[cat]["apps"].append((name, seconds))
    
    total = sum(c["seconds"] for c in category_stats.values())
    if total == 0:
        return ""

    write_app_runtime_log(editor_totals, category_stats, timezone)
    
    sorted_cats = sorted(category_stats.items(), key=lambda x: x[1]["seconds"], reverse=True)
    top_cat = sorted_cats[0][0]
    
    titles = {
        "Coding": "**Mostly Coding 💻**",
        "Entertainment": "**Mostly Relaxing 🎮**",
        "Communication": "**Mostly Chatting 💬**",
        "Browser": "**Mostly Browsing 🌐**",
        "Notes/Docs": "**Mostly Writing 📝**",
        "Other": "**Mostly Versatile 🌟**",
    }
    
    lines = [titles.get(top_cat, "**My Weekly Apps**"), "", "```text"]
    
    # Time Zone
    lines.append(f"🕐 Time Zone: {timezone}")
    lines.append("")
    
    # Activities
    lines.append("🔥 Activities:")
    for cat, info in sorted_cats:
        percent = (info["seconds"] / total * 100) if total > 0 else 0
        bar = make_progress_bar(percent)
        time_str = format_time(info["seconds"])
        lines.append(f"   {cat:22} {time_str:20} {bar}   {percent:5.2f} %")
    
    # Goals
    if goals_data and "data" in goals_data and goals_data["data"]:
        goals = goals_data["data"]
        
        # 使用用户时区计算当前日期
        try:
            from zoneinfo import ZoneInfo
            from datetime import timezone as dt_timezone
            tz = ZoneInfo(timezone) if timezone else None
            if tz:
                today = datetime.now(dt_timezone.utc).astimezone(tz)
            else:
                today = datetime.now()
        except Exception:
            today = datetime.now()
        
        # 计算本周一的日期（weekday(): Monday=0, Sunday=6）
        days_since_monday = today.weekday()
        monday = today - timedelta(days=days_since_monday)
        
        # 固定显示 Mon Tue Wed Thu Fri Sat Sun
        day_labels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        
        # 计算本周每一天的日期字符串（用于匹配 chart_data）
        week_dates = []
        for i in range(7):
            d = monday + timedelta(days=i)
            week_dates.append(d.strftime("%Y-%m-%d"))
        
        # 今天是本周的第几天（0=周一, 6=周日）
        today_index = days_since_monday
        today_date_str = today.strftime("%Y-%m-%d")
        
        lines.append("")
        lines.append("🎯 Goals:")
        lines.append(f"   {'Day':<14}" + " ".join(f"{d:<3}" for d in day_labels) + " | Progressing")
        
        for goal in goals[:3]:
            title = "Status"
            status = goal.get("status", "unknown")
            chart = goal.get("chart_data", [])
            
            # 构建日期到数据的映射
            chart_by_date = {}
            for day_data in chart:
                date_str = day_data.get("range", {}).get("date", "") or day_data.get("date", "")
                if date_str:
                    chart_by_date[date_str] = day_data
            
            daily_status = []
            today_percent = 0
            
            for i, date_str in enumerate(week_dates):
                if i > today_index:
                    # 未到的天数显示为空（未来）
                    daily_status.append("░░░")
                elif date_str in chart_by_date:
                    day_data = chart_by_date[date_str]
                    actual = day_data.get("actual_seconds", 0) or 0
                    target = day_data.get("goal_seconds", 1) or 1
                    percent = actual / target * 100 if target > 0 else 0
                    daily_status.append("███" if percent >= 100 else "▒▒▒" if percent >= 50 else "░░░")
                    
                    # 如果是今天，记录当天进度
                    if date_str == today_date_str:
                        today_percent = percent
                else:
                    # 本周已过但没有数据
                    daily_status.append("░░░")
            
            bar = make_progress_bar(min(100, today_percent))
            status_emoji = "✅" if today_percent >= 100 else "⏳" if today_percent >= 50 else "❌"
            lines.append(f"   {title:<14}" + " ".join(daily_status) + f" | {bar}   {today_percent:5.2f} % {status_emoji}")
    
    lines.append("```")
    return "\n".join(lines) + "\n\n"


def scheme_activity_categories(stats_data: Dict) -> str:
    """活动类别分布"""
    if not stats_data or "data" not in stats_data:
        return ""
    
    categories = stats_data["data"].get("categories", [])
    if not categories:
        return ""
    
    category_emoji_map = {
        "Coding": "💻", "Writing Docs": "📝", "Writing Tests": "🧪",
        "Debugging": "🐛", "Browsing": "🌐", "Building": "🔨", "Code Reviewing": "👀",
    }
    
    lines = ["📊 **Activity Categories (Last 7 Days)**", "", "```text"]
    for cat in categories[:6]:
        name = cat.get("name", "Unknown")
        percent = cat.get("percent", 0)
        text = cat.get("text", "0 mins")
        emoji = category_emoji_map.get(name, "📌")
        bar = make_progress_bar(percent)
        lines.append(f"{emoji} {name:18} {text:16} {bar}   {percent:5.2f} %")
    lines.append("```")
    return "\n".join(lines) + "\n\n"


def scheme_projects(summaries_data: Dict) -> str:
    """项目时间追踪"""
    if not summaries_data or "data" not in summaries_data:
        return ""
    
    # 汇总项目数据
    project_totals = defaultdict(float)
    for day_data in summaries_data["data"]:
        for project in day_data.get("projects", []):
            name = project.get("name", "Unknown")
            seconds = project.get("total_seconds", 0)
            project_totals[name] += seconds
    
    if not project_totals:
        return ""
    
    total = sum(project_totals.values())
    sorted_projects = sorted(project_totals.items(), key=lambda x: x[1], reverse=True)
    
    lines = ["📁 **Projects (Last 7 Days)**", "", "```text"]
    for name, seconds in sorted_projects[:5]:
        percent = (seconds / total * 100) if total > 0 else 0
        time_str = format_time(seconds)
        bar = make_progress_bar(percent)
        if len(name) > 18:
            name = name[:16] + ".."
        lines.append(f"{name:18} {time_str:16} {bar}   {percent:5.2f} %")
    lines.append("```")
    return "\n".join(lines) + "\n\n"


def scheme_languages(stats_data: Dict) -> str:
    """编程语言分布"""
    if not stats_data or "data" not in stats_data:
        return ""
    
    languages = stats_data["data"].get("languages", [])
    if not languages:
        return ""
    
    lines = ["💬 **Languages (Last 7 Days)**", "", "```text"]
    for lang in languages[:8]:
        name = lang.get("name", "Unknown")
        if len(name) > 16:
            name = name[:14] + ".."
        percent = lang.get("percent", 0)
        text = lang.get("text", "0 mins")
        bar = make_progress_bar(percent)
        lines.append(f"{name:18} {text:16} {bar}   {percent:5.2f} %")
    lines.append("```")
    return "\n".join(lines) + "\n\n"


def scheme_best_day(stats_data: Dict) -> str:
    """最佳编程日"""
    if not stats_data or "data" not in stats_data:
        return ""
    
    best_day = stats_data["data"].get("best_day", {})
    if not best_day:
        return ""
    
    date = best_day.get("date", "N/A")
    text = best_day.get("text", "N/A")
    
    lines = [
        "🏆 **Best Day Record**",
        "",
        f"> 📅 **{date}** - {text}",
    ]
    return "\n".join(lines) + "\n\n"


def scheme_global_rank(leaders_data: Dict) -> str:
    """全球排行榜"""
    if not leaders_data or "current_user" not in leaders_data:
        return ""
    
    user = leaders_data["current_user"]
    rank = user.get("rank", "N/A")
    total = leaders_data.get("total_pages", 0) * leaders_data.get("page_size", 100)
    
    lines = [
        "🌍 **Global Ranking**",
        "",
        f"> 🏅 #{rank} / {total:,}+ developers worldwide",
    ]
    return "\n".join(lines) + "\n\n"
