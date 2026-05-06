from __future__ import annotations

import sqlite3


class AnalyticsService:
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path

    async def summary(self) -> dict[str, object]:
        with sqlite3.connect(self.db_path) as db:
            db.row_factory = sqlite3.Row
            totals = db.execute(
                "SELECT COUNT(*) AS attempts, SUM(status='success') AS successes, SUM(status='failed') AS failures, "
                "SUM(manual_interventions) AS manual_count, MAX(started_at) AS last_attempt, AVG(duration_seconds) AS avg_duration FROM registration_attempts"
            ).fetchone()
            most_used = db.execute("SELECT site_key, COUNT(*) AS count FROM registration_attempts GROUP BY site_key ORDER BY count DESC LIMIT 1").fetchone()
            reasons_rows = db.execute(
                "SELECT COALESCE(failure_category, 'unknown') AS category, COUNT(*) AS count "
                "FROM registration_attempts WHERE status='failed' GROUP BY COALESCE(failure_category, 'unknown') ORDER BY count DESC"
            ).fetchall()
        return {
            "total_registration_attempts": totals["attempts"] or 0,
            "successful_registrations": totals["successes"] or 0,
            "failed_registrations": totals["failures"] or 0,
            "manual_intervention_count": totals["manual_count"] or 0,
            "most_used_site": most_used["site_key"] if most_used else None,
            "last_registration_attempt": totals["last_attempt"],
            "average_completion_time": totals["avg_duration"] or 0,
            "failure_reasons_by_category": {row["category"]: row["count"] for row in reasons_rows},
        }


def format_analytics(summary: dict[str, object]) -> str:
    reasons = summary.get("failure_reasons_by_category") or {}
    reason_lines = "\n".join(f"  • {category}: {count}" for category, count in dict(reasons).items()) or "  • None"
    avg = float(summary.get("average_completion_time") or 0)
    return (
        "📊 Analytics\n"
        f"Total registration attempts: {summary.get('total_registration_attempts', 0)}\n"
        f"Successful registrations: {summary.get('successful_registrations', 0)}\n"
        f"Failed registrations: {summary.get('failed_registrations', 0)}\n"
        f"CAPTCHA/manual intervention count: {summary.get('manual_intervention_count', 0)}\n"
        f"Most used site: {summary.get('most_used_site') or 'N/A'}\n"
        f"Last registration attempt: {summary.get('last_registration_attempt') or 'N/A'}\n"
        f"Average completion time: {avg:.1f}s\n"
        "Failure reasons by category:\n"
        f"{reason_lines}"
    )
