"""Add one clearly synthetic, idempotent report for the duplicate demo."""
from balagh import database
from balagh.triage import ReportInput, triage_report


TITLE = "[تجريبي] حفرة في الرصيف قرب المكتبة"
DESCRIPTION = "حفرة كبيرة في الرصيف تعيق مرور المشاة منذ يومين قرب المكتبة."
REPORT = ReportInput(TITLE, DESCRIPTION, "الرياض", "الروابي", "بجوار المكتبة")


def main() -> None:
    database.init_db()
    matches = database.get_reports(limit=500)
    existing = matches[matches["title"] == TITLE]
    if not existing.empty:
        print(f"Synthetic demo report already exists: BLG-{int(existing.iloc[0]['id']):05d}")
        return
    result = triage_report(REPORT, database.get_open_reports(), "Arabic")
    report_id = database.create_report(REPORT, result, "Arabic")
    print(f"Created synthetic demo report: BLG-{report_id:05d}")


if __name__ == "__main__":
    main()
