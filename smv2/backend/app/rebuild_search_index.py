from __future__ import annotations

import argparse

from app.db.init import init_db
from app.services.search_service import rebuild_course_index


def main() -> None:
    parser = argparse.ArgumentParser(description="Rebuild the local search index")
    parser.add_argument("--course-id", default=None, help="optional course id to rebuild")
    args = parser.parse_args()
    init_db()
    count = rebuild_course_index(args.course_id)
    print(f"rebuilt {count} search documents")


if __name__ == "__main__":
    main()
