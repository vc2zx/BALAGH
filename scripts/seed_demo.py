"""Add one clearly synthetic, idempotent report for the duplicate demo."""
import hashlib

from balagh import database, store
from balagh.triage import ReportInput


TITLE = "[تجريبي] حفرة في الرصيف قرب المكتبة"
DESCRIPTION = "حفرة كبيرة في الرصيف تعيق مرور المشاة منذ يومين قرب المكتبة."
REPORT = ReportInput(TITLE, DESCRIPTION, "الرياض", "الروابي", "بجوار المكتبة")


def main() -> None:
    database.init_db()
    tracking_hash = hashlib.sha256(b"BALAGH synthetic demo seed v3").hexdigest()
    report_id, created = store.submit_report(REPORT, tracking_hash)
    print(f"{'Created' if created else 'Existing'} synthetic demo report: BLG-{report_id:05d}")


if __name__ == "__main__":
    main()
