"""
GitHub Stats Dashboard - SVG Generator
基于原始设计模板的完整复刻版本
集成到 waka-readme-stats 工作流中
"""

import os
from datetime import datetime, timedelta, timezone as dt_timezone
try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo

from httpx import AsyncClient
from manager_debug import DebugManager as DBM

# --- 配置 ---
GRAPHQL_URL = "https://api.github.com/graphql"

# --- 颜色主题 ---
COLORS = {
    "header": "rgba(236, 72, 153, 1)",      # 粉红色
    "issue_primary": "#61adf4",              # Issues 浅蓝
    "issue_secondary": "#406CC4",            # Issues 深蓝
    "pr_primary": "#cf54fc",                 # PR 浅紫
    "pr_secondary": "#7B58C9",               # PR 深紫
    "commit_primary": "#ff7a35",             # Commits 橙色
    "commit_secondary": "#BA473E",           # Commits 红色
    "contributor": "#487B41",                # Contributors 绿色
    "trend_up": "#459631",                   # 上升趋势
    "trend_down": "#CF3E3E",                 # 下降趋势
    "muted": "#777",                         # 灰色文字
}

# --- GraphQL Queries ---
QUERY_USER_STATS = """
query($user: String!, $from: DateTime!, $to: DateTime!) {
  user(login: $user) {
    login
    contributionsCollection(from: $from, to: $to) {
      totalCommitContributions
      totalIssueContributions
      totalPullRequestContributions
      contributionCalendar {
        totalContributions
        weeks { contributionDays { date contributionCount } }
      }
      issueContributions(first: 100) {
        nodes { occurredAt }
      }
      pullRequestContributions(first: 100) {
        nodes { occurredAt }
      }
      commitContributionsByRepository(maxRepositories: 100) {
        repository {
          name
          isPrivate
        }
        contributions(first: 100) {
          nodes { occurredAt commitCount }
        }
      }
    }
    openIssues: issues(states: OPEN) { totalCount }
    closedIssues: issues(states: CLOSED) { totalCount }
    openPullRequests: pullRequests(states: OPEN) { totalCount }
    mergedPullRequests: pullRequests(states: MERGED) { totalCount }
    repositories(first: 5, orderBy: {field: STARGAZERS, direction: DESC}, isFork: false) {
      nodes { name stargazerCount }
    }
  }
}
"""

QUERY_PREV_MONTH = """
query($user: String!, $from: DateTime!, $to: DateTime!) {
  user(login: $user) {
    contributionsCollection(from: $from, to: $to) {
      totalCommitContributions
      totalIssueContributions
      totalPullRequestContributions
    }
  }
}
"""


class GitHubGraphQLClient:
    def __init__(self, token):
        self.client = AsyncClient(timeout=30.0)
        self.headers = {"Authorization": f"Bearer {token}"} if token else {}
    
    async def query(self, query, variables):
        resp = await self.client.post(GRAPHQL_URL, json={"query": query, "variables": variables}, headers=self.headers)
        if resp.status_code == 200:
            data = resp.json()
            if "errors" in data:
                raise Exception(f"GraphQL Error: {data['errors']}")
            return data["data"]
        raise Exception(f"HTTP {resp.status_code}")
    
    async def close(self):
        await self.client.aclose()


async def fetch_dashboard_data(username: str, token: str, timezone_str: str = "UTC") -> dict:
    """
    从 GitHub GraphQL API 获取 Dashboard 数据
    
    :param username: GitHub 用户名
    :param token: GitHub Token
    :param timezone_str: 用户时区 (e.g. "Asia/Shanghai")
    :returns: Dashboard 数据字典
    """
    client = GitHubGraphQLClient(token)
    
    # 1. 确定当前时间 (基准)
    try:
        user_tz = ZoneInfo(timezone_str)
    except Exception as e:
        DBM.w(f"Invalid timezone '{timezone_str}', falling back to UTC. Error: {e}")
        user_tz = dt_timezone.utc

    # GitHub API 需要 UTC 时间范围
    # 为了防止时区差异导致漏掉最近几小时的数据，我们将 API 查询范围设宽一点 (结束时间设为 UTC Now)
    utc_now = datetime.now(dt_timezone.utc)
    to_date = utc_now.strftime("%Y-%m-%dT%H:%M:%SZ")
    
    # 30天前 (多查一天 buffer，确保覆盖本地时区的"30天前")
    from_date = (utc_now - timedelta(days=32)).strftime("%Y-%m-%dT%H:%M:%SZ") 
    
    prev_to = from_date
    prev_from = (utc_now - timedelta(days=64)).strftime("%Y-%m-%dT%H:%M:%SZ")
    
    # 生成本地时区的"过去30天"日期列表 (含今天)
    local_now = utc_now.astimezone(user_tz)
    date_list = [(local_now - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(29, -1, -1)]
    today_str = date_list[-1]
    
    # 辅助函数: 将 UTC ISO 时间转为 本地日期字符串
    def to_local_date_str(iso_str):
        if not iso_str: return ""
        # GitHub 返回格式通常为 "2023-01-01T12:00:00Z"
        # 简单处理 Z
        if iso_str.endswith('Z'):
            dt = datetime.fromisoformat(iso_str[:-1]).replace(tzinfo=dt_timezone.utc)
        else:
            dt = datetime.fromisoformat(iso_str)
        return dt.astimezone(user_tz).strftime("%Y-%m-%d")
    
    try:
        curr = await client.query(QUERY_USER_STATS, {"user": username, "from": from_date, "to": to_date})
        prev = await client.query(QUERY_PREV_MONTH, {"user": username, "from": prev_from, "to": prev_to})
        
        user = curr["user"]
        contrib = user["contributionsCollection"]
        prev_contrib = prev["user"]["contributionsCollection"]
        
        # 解析日历 (总贡献)
        # 注意: contributionCalendar 是按用户 GitHub 设置的时区聚合的，或者是 UTC
        # 但我们主要用它的 totalContributions 做 KPI。weeks 数据如果用的话，也最好对齐。
        # 这里为了简单，日历热力图我们依赖 API 返回的 weeks 结构，不做深度时区重算(因为 API 已聚合)
        # 但为了柱状图准确，后面的 issue/pr/commit nodes 我们会手动重算。
        
        all_days = []
        for week in contrib["contributionCalendar"]["weeks"]:
            for day in week["contributionDays"]:
                all_days.append({"date": day["date"], "count": day["contributionCount"]})
        recent = sorted(all_days, key=lambda x: x["date"], reverse=True)[:30]
        daily = [d["count"] for d in reversed(recent)]
        
        
        # 解析 Issue 每日数据 (使用本地时区重算)
        issue_by_date = {d: 0 for d in date_list}
        for node in contrib.get("issueContributions", {}).get("nodes", []):
            local_date = to_local_date_str(node["occurredAt"])
            if local_date in issue_by_date:
                issue_by_date[local_date] += 1
        issue_daily = [issue_by_date[d] for d in date_list]
        
        # 解析 PR 每日数据
        pr_by_date = {d: 0 for d in date_list}
        for node in contrib.get("pullRequestContributions", {}).get("nodes", []):
            local_date = to_local_date_str(node["occurredAt"])
            if local_date in pr_by_date:
                pr_by_date[local_date] += 1
        pr_daily = [pr_by_date[d] for d in date_list]
        
        # 解析 Commit 每日数据 & Top Repos (按 Commit 数排序)
        commit_by_date = {d: 0 for d in date_list}
        repo_stats = []

        for repo in contrib.get("commitContributionsByRepository", []):
            repo_name = repo["repository"]["name"]
            is_private = repo["repository"].get("isPrivate", False)
            
            # 隐私保护
            if is_private:
                repo_name = "Private Repo"
            
            repo_daily = {d: 0 for d in date_list}
            total_repo_commits = 0
            
            for node in repo.get("contributions", {}).get("nodes", []):
                local_date = to_local_date_str(node["occurredAt"])
                count = node.get("commitCount", 1)
                
                # 更新总表
                if local_date in commit_by_date:
                    commit_by_date[local_date] += count
                
                # 更新分仓库表
                if local_date in repo_daily:
                    repo_daily[local_date] += count
                    total_repo_commits += count
            
            if total_repo_commits > 0:
                # 转为 30 天数组
                daily_arr = [repo_daily[d] for d in date_list]
                repo_stats.append({
                    "name": repo_name,
                    "total_commits": total_repo_commits,
                    "daily": daily_arr
                })

        commit_daily = [commit_by_date[d] for d in date_list]
        
        # Top 5 Repos by Commits
        top_repos = sorted(repo_stats, key=lambda x: x["total_commits"], reverse=True)[:5]
        
        # 计算统计
        curr_issue = contrib["totalIssueContributions"]
        prev_issue = prev_contrib["totalIssueContributions"]
        issue_change = curr_issue - prev_issue
        
        total_prs = contrib["totalPullRequestContributions"]
        prev_prs = prev_contrib["totalPullRequestContributions"]
        pr_change = total_prs - prev_prs
        
        total_commits = contrib["totalCommitContributions"]
        prev_commits = prev_contrib["totalCommitContributions"]
        commits_change = total_commits - prev_commits
        
        return {
            "username": username,
            "total_contributions": contrib["contributionCalendar"]["totalContributions"],
            "daily": daily,
            "issue_daily": issue_daily,
            "pr_daily": pr_daily,
            "commit_daily": commit_daily,
            "issue_count": curr_issue,
            "issue_change": issue_change,
            "issue_change_pct": round((issue_change / max(prev_issue, 1)) * 100, 2) if prev_issue else 0,
            "prs": total_prs,
            "pr_change": pr_change,
            "pr_change_pct": round((pr_change / max(prev_prs, 1)) * 100, 1) if prev_prs else 0,
            "commits": total_commits,
            "commits_change": commits_change,
            "commits_change_pct": round((commits_change / max(prev_commits, 1)) * 100, 1) if prev_commits else 0,
            "top_repos": top_repos,
        }
    finally:
        await client.close()


def generate_dashboard_svg(data: dict) -> str:
    """
    生成完全复刻原始设计的 SVG
    
    :param data: Dashboard 数据字典
    :returns: SVG 字符串
    """
    
    # --- 生成 30 天热力图方块 ---
    max_daily = max(data["daily"]) if data["daily"] else 1
    heatmap_rects = ""
    for i, count in enumerate(data["daily"][:30]):
        x = 533.5 + i * 9
        opacity = 0.2 + (count / max_daily) * 0.8 if max_daily > 0 else 0.2
        heatmap_rects += f'<rect x="{x}" y="20" width="8" height="8" rx="1.5" opacity="{opacity:.2f}" fill="{COLORS["header"]}" />\n'
    
    # --- 生成柱状图 (单色) ---
    def gen_bar_chart(daily_data, color, chart_height=50):
        bars = ""
        bar_width = 7.7
        max_val = max(daily_data) if daily_data else 1
        base_y = 119.5
        
        for i, val in enumerate(daily_data[:30]):
            x = 1 + i * 8.755
            if max_val > 0:
                h = int((val / max_val) * chart_height)
            else:
                h = 0
            
            y = base_y - h
            bars += f'<rect x="{x}" y="{y}" width="{bar_width}" height="{h}" rx="1" fill="{color}" />\n'
        
        return bars
    
    issue_bars = gen_bar_chart(data["issue_daily"], COLORS["issue_primary"])
    pr_bars = gen_bar_chart(data["pr_daily"], COLORS["pr_primary"])
    commit_bars = gen_bar_chart(data["commit_daily"], COLORS["commit_primary"])
    
    # --- 生成 Top Repos 热力网格 ---
    def gen_contributor_grid(repo_name, daily_commits, x_offset):
        grid = f'<g transform="translate({x_offset}, 0)">\n'
        grid += f'<text x="0" y="19" class="mono bold smaller" fill="{COLORS["contributor"]}">{repo_name[:13]:<13}</text>\n'
        
        max_c = max(daily_commits) if daily_commits else 1
        
        # 生成 2x15 的网格 (按列填充: col 0 -> days 0,1; col 1 -> days 2,3 ...)
        for col in range(15):
            for row in range(2):
                day_idx = col * 2 + row
                if day_idx < len(daily_commits):
                    count = daily_commits[day_idx]
                    
                    gx = col * 6
                    gy = 28 + row * 6
                    
                    if count > 0:
                        opacity = 0.3 + (count / max_c) * 0.7
                    else:
                        opacity = 0.1
                        
                    grid += f'<rect x="{gx}" y="{gy}" width="5" height="5" opacity="{opacity:.2f}" fill="{COLORS["contributor"]}" />\n'
        
        grid += '</g>\n'
        return grid
    
    repos_grids = ""
    repo_positions = [190, 320, 450, 580, 710]
    for i, repo in enumerate(data["top_repos"][:5]):
        repos_grids += gen_contributor_grid(repo["name"], repo["daily"], repo_positions[i])
    
    # --- 趋势箭头 ---
    def trend_arrow(change):
        if change == 0:
            return f'''<svg width="10" height="12" viewBox="0 0 10 12" fill="none" xmlns="http://www.w3.org/2000/svg">
                <rect x="0" y="5" width="10" height="2" rx="1" fill="{COLORS["muted"]}" />
            </svg>'''
        elif change > 0:
            return '''<svg width="9" height="11" viewBox="0 0 9 11" fill="none" xmlns="http://www.w3.org/2000/svg">
                <path d="M7.96107 4.28933L7.96102 4.28929L4.83602 1.16433L4.83598 1.16423C4.74692 1.07533 4.62619 1.02533 4.50031 1.02533C4.37444 1.02533 4.25371 1.07533 4.16465 1.16423L4.1646 1.16433L1.04078 4.28811C0.994735 4.33135 0.957786 4.38333 0.932076 4.44103C0.906116 4.4993 0.892156 4.5622 0.891026 4.62597C0.889906 4.68975 0.901636 4.7531 0.925526 4.81225C0.949416 4.8714 0.984975 4.92512 1.03008 4.97023C1.07519 5.01533 1.12892 5.05089 1.18806 5.07478C1.24721 5.09867 1.31056 5.11041 1.37434 5.10928C1.43812 5.10816 1.50102 5.0942 1.55928 5.06823C1.61698 5.04253 1.66896 5.00557 1.7122 4.95954L4.02531 2.64642L4.02531 9.625C4.02531 9.75098 4.07536 9.8718 4.16444 9.96088C4.25352 10.05 4.37434 10.1 4.50031 10.1C4.62629 10.1 4.74711 10.05 4.83619 9.96088C4.92527 9.8718 4.97531 9.75098 4.97531 9.625L4.97531 2.64642L7.2896 4.96071L7.28965 4.96075C7.37871 5.04971 7.49944 5.09967 7.62531 5.09967C7.75119 5.09967 7.87192 5.04971 7.96098 4.96075L7.89031 4.89L7.96107 4.96067C8.05002 4.8716 8.09998 4.75087 8.09998 4.625C8.09998 4.49912 8.05002 4.3784 7.96107 4.28933Z" fill="#459631" stroke="#459631" stroke-width="0.5"/>
            </svg>'''
        else:
            return '''<svg width="12" height="12" viewBox="0 0 12 12" fill="none" xmlns="http://www.w3.org/2000/svg">
                <path d="M2.02989 7.836L2.02994 7.83604L5.15494 10.961L5.15498 10.9611C5.24404 11.05 5.36477 11.1 5.49065 11.1C5.61652 11.1 5.73725 11.05 5.82631 10.9611L5.82636 10.961L8.95018 7.83722C8.99622 7.79398 9.03317 7.742 9.05888 7.6843C9.08484 7.62603 9.0988 7.56313 9.09993 7.49936C9.10105 7.43558 9.08932 7.37223 9.06543 7.31308C9.04154 7.25393 9.00598 7.20021 8.96088 7.1551C8.91577 7.11 8.86204 7.07444 8.8029 7.05055C8.74375 7.02666 8.6804 7.01492 8.61662 7.01605C8.55284 7.01717 8.48994 7.03113 8.43168 7.0571C8.37398 7.0828 8.322 7.11976 8.27876 7.16579L5.96565 9.47891L5.96565 2.50033C5.96565 2.37435 5.9156 2.25353 5.82652 2.16445C5.73744 2.07537 5.61662 2.02533 5.49065 2.02533C5.36467 2.02533 5.24385 2.07537 5.15477 2.16445C5.06569 2.25353 5.01565 2.37435 5.01565 2.50033L5.01565 9.47891L2.70136 7.16462L2.70131 7.16458C2.61225 7.07562 2.49152 7.02566 2.36565 7.02566C2.23977 7.02566 2.11904 7.07562 2.02998 7.16458L2.10065 7.23533L2.02989 7.16466C1.94094 7.25373 1.89098 7.37446 1.89098 7.50033C1.89098 7.62621 1.94094 7.74693 2.02989 7.836Z" fill="#CF3E3E" stroke="#CF3E3E" stroke-width="0.5"/>
            </svg>'''
    
    # 格式化变化值
    issue_chg_str = f"{data['issue_change']:+.2f} ({data['issue_change_pct']:+.2f}%)"
    pr_chg_str = f"+{data['pr_change']} ({data['pr_change_pct']}%)" if data['pr_change'] >= 0 else f"{data['pr_change']} ({data['pr_change_pct']}%)"
    commit_chg_str = f"{data['commits_change']} ({data['commits_change_pct']}%)"
    
    def get_trend_color(change):
        if change == 0:
            return COLORS["muted"]
        return COLORS["trend_up"] if change >= 0 else COLORS["trend_down"]

    issue_trend_color = get_trend_color(data["issue_change"])
    pr_trend_color = get_trend_color(data["pr_change"])
    commit_trend_color = get_trend_color(data["commits_change"])
    
    svg = f'''<svg width="814" height="318" viewBox="0 0 814 318" fill="none" xmlns="http://www.w3.org/2000/svg">
    <style>
        .sans {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif; }}
        .mono {{ font-family: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace; font-size: 12px; letter-spacing: -0.5px; }}
        .bold {{ font-weight: 500; }}
        .medium {{ font-size: 16px; }}
        .small {{ font-size: 14px; }}
        .smaller {{ font-size: 12px; }}
    </style>

    <rect x="0.5" y="0.5" width="813" height="320" fill="rgba(0, 0, 0, 0)"/>

    <!-- Header Section -->
    <g>
        <rect x="0.5" y="0.5" width="813" height="47" rx="4.5" stroke="rgba(0,0,0,0.15)" />
        <rect x="0.5" y="0.5" width="813" height="47" rx="4.5" stroke="rgba(255,255,255,0.3)" />
        
        <g transform="translate(10,16)">
            <svg width="20" height="16" fill="none" xmlns="http://www.w3.org/2000/svg">
                <path d="M0 .842C0 .377.373 0 .833 0h18.334c.46 0 .833.377.833.842v.421a.838.838 0 0 1-.833.842H.833A.838.838 0 0 1 0 1.263v-.42ZM0 14.737c0-.465.373-.842.833-.842h18.334c.46 0 .833.377.833.842v.42a.838.838 0 0 1-.833.843H.833A.838.838 0 0 1 0 15.158v-.421ZM0 4.632c0-.465.373-.843.833-.843H5c.46 0 .833.377.833.843v.42A.838.838 0 0 1 5 5.896H.833A.838.838 0 0 1 0 5.053v-.421ZM0 8.421c0-.465.373-.842.833-.842H5c.46 0 .833.377.833.842v2.947A.838.838 0 0 1 5 12.21H.833A.838.838 0 0 1 0 11.368V8.421ZM7.083 4.632c0-.465.373-.843.834-.843h4.166c.46 0 .834.377.834.843v.42a.838.838 0 0 1-.834.843H7.917a.838.838 0 0 1-.834-.842v-.421ZM7.083 8.421c0-.465.373-.842.834-.842h4.166c.46 0 .834.377.834.842v2.947a.838.838 0 0 1-.834.842H7.917a.838.838 0 0 1-.834-.842V8.421ZM14.167 4.632c0-.465.373-.843.833-.843h4.167c.46 0 .833.377.833.843v.42a.838.838 0 0 1-.833.843H15a.838.838 0 0 1-.833-.842v-.421ZM14.167 8.421c0-.465.373-.842.833-.842h4.167c.46 0 .833.377.833.842v2.947a.838.838 0 0 1-.833.842H15a.838.838 0 0 1-.833-.842V8.421Z" fill="{COLORS['header']}"/>
            </svg>
        </g>
        <text x="38" y="29" class="sans small bold" fill="{COLORS['header']}" stroke-width="0.5">{data['total_contributions']} Contributions in the Last 30 Days</text>
        
        {heatmap_rects}
    </g>

    <!-- KPI Card 1: Issues -->
    <g transform="translate(0, 58)">
        <rect x="0.5" y="0.5" width="264" height="70" rx="4.5" stroke="rgba(0,0,0,0.15)" />
        <rect x="0.5" y="0.5" width="264" height="70" rx="4.5" stroke="rgba(255,255,255,0.3)" />
        
        <text x="10" y="24" class="sans small bold" fill="{COLORS['issue_secondary']}">{data['issue_count']} Issues Created</text>
        <text x="10" y="56" text-anchor="start" class="mono smaller bold" fill="{COLORS['muted']}">{issue_chg_str}</text>
        <text x="254" y="56" text-anchor="end" class="mono smaller bold" fill="{issue_trend_color}">past month</text>
        
        <g transform="translate(170, 46)">
            {trend_arrow(data['issue_change'])}
        </g>
    </g>

    <!-- KPI Card 2: Pull Requests -->
    <g transform="translate(274, 58)">
        <rect x="0.5" y="0.5" width="264" height="70" rx="4.5" stroke="rgba(0,0,0,0.15)" />
        <rect x="0.5" y="0.5" width="264" height="70" rx="4.5" stroke="rgba(255,255,255,0.3)" />
        
        <text x="10" y="24" class="sans small bold" fill="{COLORS['pr_secondary']}">{data['prs']} Pull Requests Created</text>
        <text x="10" y="56" text-anchor="start" class="mono smaller bold" fill="{COLORS['muted']}">{pr_chg_str}</text>
        <text x="254" y="56" text-anchor="end" class="mono smaller bold" fill="{pr_trend_color}">past month</text>
        
        <g transform="translate(170, 46)">
            {trend_arrow(data['pr_change'])}
        </g>
    </g>

    <!-- KPI Card 3: Commits -->
    <g transform="translate(548, 58)">
        <rect x="0.5" y="0.5" width="264" height="70" rx="4.5" stroke="rgba(0,0,0,0.15)" />
        <rect x="0.5" y="0.5" width="264" height="70" rx="4.5" stroke="rgba(255,255,255,0.3)" />
        
        <text x="10" y="24" class="sans small bold" fill="{COLORS['commit_secondary']}">{data['commits']} Commits Created</text>
        <text x="10" y="56" text-anchor="start" class="mono smaller bold" fill="{COLORS['muted']}">{commit_chg_str}</text>
        <text x="254" y="56" text-anchor="end" class="mono smaller bold" fill="{commit_trend_color}">past month</text>
        
        <g transform="translate(170, 46)">
            {trend_arrow(data['commits_change'])}
        </g>
    </g>

    <!-- Bar Chart 1: Issues -->
    <g transform="translate(0, 138)">
        <rect x="0.5" y="0.5" width="264" height="120" rx="4.5" stroke="rgba(0,0,0,0.15)" />
        <rect x="0.5" y="0.5" width="264" height="120" rx="4.5" fill="rgba(255,255,255, 0.0)" stroke="rgba(255,255,255,0.3)" />
        
        <g transform="translate(10, 20)">
            <svg width="17" height="16" fill="none" xmlns="http://www.w3.org/2000/svg">
                <path d="M8 9.5a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3Z" fill="url(#a)" />
                <path fill-rule="evenodd" clip-rule="evenodd" d="M8 0a8 8 0 1 0 0 16A8 8 0 0 0 8 0ZM1.5 8a6.5 6.5 0 1 1 13 0 6.5 6.5 0 0 1-13 0Z" fill="url(#b)" />
                <defs>
                    <linearGradient id="a" x1="8" y1="6.5" x2="8" y2="9.5" gradientUnits="userSpaceOnUse">
                        <stop stop-color="#00BCF7" /><stop offset=".729" stop-color="#326CE5" />
                    </linearGradient>
                    <linearGradient id="b" x1="8" y1="0" x2="8" y2="16" gradientUnits="userSpaceOnUse">
                        <stop stop-color="#00BCF7" /><stop offset=".729" stop-color="#326CE5" />
                    </linearGradient>
                </defs>
            </svg>
        </g>
        <text x="34" y="33" class="sans small bold" fill="{COLORS['issue_secondary']}">Issues</text>
        
        {issue_bars}
    </g>

    <!-- Bar Chart 2: Pull Requests -->
    <g transform="translate(274, 138)">
        <rect x="0.5" y="0.5" width="264" height="120" rx="4.5" stroke="rgba(0,0,0,0.15)" />
        <rect x="0.5" y="0.5" width="264" height="120" rx="4.5" fill="rgba(255,255,255, 0.0)" stroke="rgba(255,255,255,0.3)" />
        
        <g transform="translate(10, 20)">
            <svg width="14" height="15" fill="none" xmlns="http://www.w3.org/2000/svg">
                <path fill-rule="evenodd" clip-rule="evenodd" d="M6.176 3.073 8.572.677A.25.25 0 0 1 9 .854v4.792a.25.25 0 0 1-.427.177L6.176 3.427a.25.25 0 0 1 0-.354ZM2.749 2.5a.75.75 0 1 0 0 1.5.75.75 0 0 0 0-1.5Zm-2.25.75a2.25 2.25 0 1 1 3 2.122v5.256a2.25 2.25 0 1 1-1.5 0V5.372a2.25 2.25 0 0 1-1.5-2.122ZM10 2.5H9V4h1a1 1 0 0 1 1 1v5.628a2.25 2.25 0 1 0 1.5 0V5A2.5 2.5 0 0 0 10 2.5Zm1 10.25a.75.75 0 1 1 1.5 0 .75.75 0 0 1-1.5 0ZM2.75 12a.75.75 0 1 0 0 1.5.75.75 0 0 0 0-1.5Z" fill="url(#pra)" />
                <defs>
                    <linearGradient id="pra" x1="0" y1="0" x2="0" y2="16" gradientUnits="userSpaceOnUse">
                        <stop stop-color="#CE5AFF" /><stop offset="1" stop-color="#7C64BD" />
                    </linearGradient>
                </defs>
            </svg>
        </g>
        <text x="34" y="33" class="sans small bold" fill="{COLORS['pr_secondary']}">Pull Requests</text>
        
        {pr_bars}
    </g>

    <!-- Bar Chart 3: Pushes & Commits -->
    <g transform="translate(548, 138)">
        <rect x="0.5" y="0.5" width="264" height="120" rx="4.5" stroke="rgba(0,0,0,0.15)" />
        <rect x="0.5" y="0.5" width="264" height="120" rx="4.5" fill="rgba(255,255,255, 0.0)" stroke="rgba(255,255,255,0.3)" />
        
        <g transform="translate(10, 20)">
            <svg width="14" height="15" fill="none" xmlns="http://www.w3.org/2000/svg">
                <path fill-rule="evenodd" clip-rule="evenodd" d="M1 2.5A2.5 2.5 0 013.5 0h8.75a.75.75 0 01.75.75v3.5a.75.75 0 01-1.5 0V1.5h-8a1 1 0 00-1 1v6.708A2.492 2.492 0 013.5 9h3.25a.75.75 0 010 1.5H3.5a1 1 0 100 2h5.75a.75.75 0 010 1.5H3.5A2.5 2.5 0 011 11.5v-9zm13.23 7.79a.75.75 0 001.06-1.06l-2.505-2.505a.75.75 0 00-1.06 0L9.22 9.229a.75.75 0 001.06 1.061l1.225-1.224v6.184a.75.75 0 001.5 0V9.066l1.224 1.224z" fill="url(#paa)" />
                <defs>
                    <linearGradient id="paa" x1="0" y1="0" x2="0" y2="16" gradientUnits="userSpaceOnUse">
                        <stop stop-color="#ff553a" /><stop offset="1" stop-color="#cd2e31" />
                    </linearGradient>
                </defs>
            </svg>
        </g>
        <text x="34" y="33" class="sans small bold" fill="{COLORS['commit_secondary']}">Commits</text>
        
        {commit_bars}
    </g>

    <!-- Top Contributors / Repos Section -->
    <g transform="translate(0, 270)">
        <rect x="0.5" y="0.5" width="813" height="47" rx="4.5" stroke="rgba(0,0,0,0.15)" />
        <rect x="0.5" y="0.5" width="813" height="47" rx="4.5" stroke="rgba(255,255,255,0.4)" />
        
        <g transform="translate(10,16)">
            <svg width="18" height="16" viewBox="0 0 18 16" fill="none" xmlns="http://www.w3.org/2000/svg">
                <path d="M9.79536 12.9717L9.79524 12.9718C9.46851 13.1766 9.19498 13.3364 9.00063 13.4464C7.83951 12.7896 6.74227 12.0258 5.72321 11.1649C3.88319 9.59824 2.24091 7.56228 2.24091 5.37382C2.24091 3.541 3.7425 2.24091 5.17164 2.24091C6.62529 2.24091 7.80981 3.19682 8.34062 4.78784L8.34071 4.7881C8.38708 4.92624 8.47567 5.04631 8.59397 5.13138C8.71226 5.21645 8.85429 5.26222 9 5.26222C9.14571 5.26222 9.28774 5.21645 9.40603 5.13138C9.52433 5.04631 9.61292 4.92624 9.65929 4.7881L9.65938 4.78784C10.1902 3.1968 11.374 2.24091 12.8284 2.24091C14.2575 2.24091 15.7591 3.541 15.7591 5.37382C15.7591 7.56237 14.1167 9.5984 12.2766 11.1651L12.2766 11.1651C11.3775 11.9307 10.4748 12.5468 9.79536 12.9717ZM9.34495 14.8432L9.45145 14.7884L9.45007 14.7858C10.7743 14.0577 12.0229 13.1997 13.1775 12.2244L13.1779 12.2241C15.0651 10.6183 17.15 8.22165 17.15 5.37382C17.15 2.77316 15.0247 0.85 12.8284 0.85C11.1862 0.85 9.84811 1.68593 9.00005 2.97557C8.15253 1.68589 6.81376 0.85 5.17164 0.85C2.9746 0.85 0.85 2.7739 0.85 5.37309V5.37382C0.85 8.22165 2.93415 10.6176 4.82206 12.2241L4.82245 12.2244C5.65637 12.9291 6.53984 13.5731 7.46602 14.1512C7.82102 14.3734 8.18244 14.585 8.5498 14.786L8.54855 14.7884L8.65382 14.8426L8.65589 14.8436L8.65658 14.844L8.67407 14.8531L8.67388 14.8535L8.6766 14.8546L8.80709 14.9417L8.82283 14.9111C8.88045 14.9263 8.93999 14.934 9 14.934C9.06043 14.934 9.12038 14.9261 9.17838 14.9108L9.18484 14.9233L9.29065 14.8704C9.29915 14.8665 9.30758 14.8624 9.31593 14.8581L9.31598 14.8583L9.32593 14.8531L9.34341 14.844L9.34411 14.8436L9.34412 14.8436L9.34495 14.8432Z" fill="url(#paint0_linear)" stroke="url(#paint1_linear)" stroke-width="0.5"/>
                <defs>
                    <linearGradient id="paint0_linear" x1="9" y1="1" x2="9" y2="14.784" gradientUnits="userSpaceOnUse">
                        <stop stop-color="#36C5F0"/><stop offset="0.729167" stop-color="#55BA3C"/>
                    </linearGradient>
                    <linearGradient id="paint1_linear" x1="9" y1="1" x2="9" y2="14.784" gradientUnits="userSpaceOnUse">
                        <stop stop-color="#36C5F0"/><stop offset="0.729167" stop-color="#55BA3C"/>
                    </linearGradient>
                </defs>
            </svg>
        </g>
        <text x="36" y="29" class="sans small bold" fill="{COLORS['contributor']}">Top Repositories</text>
        
        {repos_grids}
    </g>
</svg>'''
    
    return svg


# SVG Dashboard 文件路径常量
SVG_DASHBOARD_PATH = "assets/github_dashboard.svg"


async def generate_and_save_dashboard(username: str, token: str, timezone_str: str = "UTC") -> str:
    """
    生成并保存 SVG Dashboard
    
    :param username: GitHub 用户名
    :param token: GitHub Token
    :param timezone_str: 用户时区
    :returns: SVG 文件相对路径
    """
    DBM.i("🚀 开始生成 SVG Dashboard...")
    DBM.i(f"👤 目标用户: {username} | 🌏 时区: {timezone_str}")
    
    try:
        DBM.i("📡 正在获取 GitHub 数据...")
        data = await fetch_dashboard_data(username, token, timezone_str)
        DBM.g("✅ GitHub 数据获取成功!")
    except Exception as e:
        DBM.p(f"❌ SVG Dashboard 数据获取失败: {e}")
        raise
    
    # 生成 SVG
    svg_content = generate_dashboard_svg(data)
    
    # 确保目录存在
    os.makedirs(os.path.dirname(SVG_DASHBOARD_PATH), exist_ok=True)
    
    # 保存 SVG 文件
    with open(SVG_DASHBOARD_PATH, "w", encoding="utf-8") as f:
        f.write(svg_content)
    
    DBM.g(f"✅ SVG Dashboard 已保存: {SVG_DASHBOARD_PATH}")
    
    return SVG_DASHBOARD_PATH
