"""Create one private, local .env with random prototype credentials."""
from pathlib import Path
from secrets import token_urlsafe


root = Path(__file__).resolve().parents[1]
destination = root / ".env"
if destination.exists():
    raise SystemExit(".env already exists; edit it locally if needed. Nothing was overwritten.")
staff_code = token_urlsafe(12)
secret = token_urlsafe(48)
template = (root / ".env.example").read_text(encoding="utf-8")
template = template.replace("STAFF_ACCESS_CODE=\n", f"STAFF_ACCESS_CODE={staff_code}\n")
template = template.replace("FLASK_SECRET_KEY=\n", f"FLASK_SECRET_KEY={secret}\n")
destination.write_text(template, encoding="utf-8")
print("Created .env for local use. Staff access code:", staff_code)
