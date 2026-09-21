"""Create the first organisation and its first user.

Usage:
    python -m scripts.seed_admin

The password is always prompted interactively -- never accepted as a CLI
argument -- so it never lands in shell history or a process listing.
jdk_clean's seed script took --password as an argument while its two
sibling scripts correctly used getpass; see
docs/audit/AUTHENTICATION_AUDIT.md #4/#9. This script has no such
inconsistency to fix because there's only one script.
"""
import getpass
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.core.database import SessionLocal
from app.core.security import hash_password
from app.core.validation import validate_password_complexity
from app.models.organisation import Organisation
from app.models.user import User


def main() -> None:
    db = SessionLocal()
    try:
        org_name = input("Organisation name: ").strip()
        full_name = input("Full name: ").strip()
        email = input("Email: ").strip()
        username = input("Username: ").strip()

        while True:
            password = getpass.getpass("Password: ")
            confirm = getpass.getpass("Confirm password: ")
            if password != confirm:
                print("Passwords do not match, try again.")
                continue
            try:
                validate_password_complexity(password)
            except ValueError as exc:
                print(str(exc))
                continue
            break

        organisation = db.query(Organisation).filter(Organisation.name == org_name).first()
        if organisation is None:
            code = input("Organisation code (short identifier, e.g. JDK): ").strip()
            currency = input("Currency code (e.g. INR, USD): ").strip().upper()
            timezone = input("Timezone [UTC]: ").strip() or "UTC"
            contact_email = input("Contact email (optional): ").strip() or None
            contact_phone = input("Contact phone (optional): ").strip() or None
            address = input("Address (optional): ").strip() or None
            organisation = Organisation(
                name=org_name,
                code=code,
                currency=currency,
                timezone=timezone,
                contact_email=contact_email,
                contact_phone=contact_phone,
                address=address,
                is_active=True,
            )
            db.add(organisation)
            db.flush()

        user = User(
            organisation_id=organisation.id,
            full_name=full_name,
            email=email,
            username=username,
            password_hash=hash_password(password),
            is_active=True,
        )
        db.add(user)
        db.commit()
        print(f"Created user '{username}' in organisation '{organisation.name}'.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
