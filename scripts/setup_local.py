"""Create a private local .env; individual staff accounts are provisioned separately."""
from pathlib import Path
from secrets import token_urlsafe


root = Path(__file__).resolve().parents[1]
destination = root / ".env"
if destination.exists():
    raise SystemExit(".env already exists; edit it locally if needed. Nothing was overwritten.")
secret = token_urlsafe(48)
template = (root / ".env.example").read_text(encoding="utf-8")
template = template.replace("FLASK_SECRET_KEY=\n", f"FLASK_SECRET_KEY={secret}\n")
destination.write_text(template, encoding="utf-8")
print("Created .env for local use.")
print("Next: uv run python -m balagh.staff_admin create-user --username admin --role admin")
