"""Create an organisation (if it doesn't already exist) and a user in it.

Usage:
    python -m scripts.seed_admin

Entering an organisation name that already exists adds a new user to that
organisation instead of creating a second one -- this is also how you add
more users today, since there's no full user-creation API yet (only
role-change and team-membership are RBAC-gated so far; see
docs/modules/roles_rbac.md). The same applies to team names: an existing
team is reused, a new name creates one, and you can enter several
(comma-separated) since team membership is many-to-many
(docs/modules/roles_rbac.md #1).

The first user created for a brand-new organisation is made 'admin' of
it automatically -- otherwise nobody could ever manage that organisation's
teams or users afterward. Every other user defaults to 'team_member',
overridable at the prompt.

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

from sqlalchemy.exc import IntegrityError

from app.core.database import SessionLocal
from app.core.roles import ADMIN, TEAM_MEMBER, VALID_ROLES
from app.core.security import hash_password
from app.core.validation import validate_password_complexity
from app.models.organisation import Organisation
from app.models.team import Team
from app.models.user import User
from app.models.user_team import UserTeam


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
        is_new_organisation = organisation is None
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

        if is_new_organisation:
            role = ADMIN
            print(f"Role: {role} (first user of a new organisation)")
        else:
            while True:
                role = input(f"Role {sorted(VALID_ROLES)} [{TEAM_MEMBER}]: ").strip() or TEAM_MEMBER
                if role in VALID_ROLES:
                    break
                print(f"Role must be one of {sorted(VALID_ROLES)}.")

        team_names = [
            name.strip()
            for name in input("Team name(s), comma-separated (optional, press Enter to skip): ").split(",")
            if name.strip()
        ]
        teams = []
        for team_name in team_names:
            team = db.query(Team).filter(Team.organisation_id == organisation.id, Team.name == team_name).first()
            if team is None:
                team = Team(organisation_id=organisation.id, name=team_name, is_active=True)
                db.add(team)
                db.flush()
            teams.append(team)

        user = User(
            organisation_id=organisation.id,
            role=role,
            full_name=full_name,
            email=email,
            username=username,
            password_hash=hash_password(password),
            is_active=True,
        )
        db.add(user)
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            print(f"A user with email '{email}' or username '{username}' already exists.")
            return

        for team in teams:
            db.add(UserTeam(user_id=user.id, team_id=team.id))

        db.commit()
        team_summary = ", ".join(t.name for t in teams) or "no team"
        print(f"Created user '{username}' ({role}) in organisation '{organisation.name}' -- {team_summary}.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
