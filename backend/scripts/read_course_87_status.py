"""Read-only acceptance snapshot for the local course 87 Demo."""
from __future__ import annotations

import json
import sqlite3


def main() -> None:
    db = sqlite3.connect("file:database/smart_class.db?mode=ro", uri=True)

    def one(sql: str, params: tuple = ()):
        return db.execute(sql, params).fetchone()

    def scalar(sql: str, params: tuple = ()):
        return one(sql, params)[0]

    student_id = scalar("select id from users where username='demo87_student'")
    result = {
        "alembic": scalar("select version_num from alembic_version"),
        "capabilities": one("select knowledge_graph,evidence from course_capabilities where course_id=87"),
        "nodes": scalar("select count(1) from course_knowledge_nodes where course_id=87"),
        "reviews": db.execute("select decision,count(1) from graph_node_reviews where course_id=87 group by decision").fetchall(),
        "evidence_active": scalar("select count(1) from course_evidence_records where course_id=87 and status='ACTIVE'"),
        "citations_student": scalar("select count(1) from evidence_citations where course_id=87 and student_visible=1 and status in ('EXACT','APPROXIMATE')"),
        "spans": db.execute("select status,count(1) from evidence_spans where course_id=87 group by status").fetchall(),
        "snapshots": db.execute("select snapshot_id,version,status,is_active,node_count,relation_count from graph_snapshot_records where course_id=87 order by version").fetchall(),
        "demo_student": one("select id,username from users where username='demo87_student'"),
        "membership": one("select user_id,role,status from course_memberships where course_id=87 and user_id=?", (student_id,)),
        "questions": db.execute("select id,status,knowledge_node_ids from question_bank_items where course_id=87 and category='demo_course_87'").fetchall(),
        "attempts": scalar("select count(1) from question_attempts where course_id=87 and student_id=?", (student_id,)),
        "learning_evidence": scalar("select count(1) from learning_evidence_records where course_id=87 and student_id=?", (student_id,)),
        "cognitive_states": scalar("select count(1) from cognitive_states where course_id=87 and student_id=?", (student_id,)),
        "recommendations": db.execute("select graph_snapshot_id,knowledge_node_id,recommendation_type from recommendation_records where course_id=87 and student_id=? order by id desc limit 3", (student_id,)).fetchall(),
    }
    print(json.dumps(result, ensure_ascii=False, default=str, indent=2))
    db.close()


if __name__ == "__main__":
    main()
