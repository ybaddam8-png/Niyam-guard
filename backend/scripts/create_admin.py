"""
Usage: python3 -m scripts.create_admin <username> <password>
Creates (or promotes) a user with role=admin. This is the only way to get the first
account into a fresh deployment — there is no public /auth/register endpoint on purpose.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db import SessionLocal
from app.models import User
from app.security import hash_password


def main():
    if len(sys.argv) != 3:
        print("Usage: python3 -m scripts.create_admin <username> <password>")
        sys.exit(1)
    username, password = sys.argv[1], sys.argv[2]

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == username).first()
        if user:
            user.role = "admin"
            user.hashed_password = hash_password(password)
            db.commit()
            print(f"Promoted existing user '{username}' to admin and reset password.")
        else:
            user = User(username=username, hashed_password=hash_password(password), role="admin")
            db.add(user)
            db.commit()
            print(f"Created admin user '{username}'.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
