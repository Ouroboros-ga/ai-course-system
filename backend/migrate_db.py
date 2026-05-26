"""数据库迁移脚本：添加缺失的列和表"""
from sqlmodel import Session
from app.models.database import engine

def migrate():
    with Session(engine) as session:
        # 1. teacher_assets 添加 clone 字段
        for col, col_type in [
            ("clone_voice_id", "VARCHAR"),
            ("clone_status", "VARCHAR"),
        ]:
            try:
                session.exec(__import__("sqlmodel").text(
                    f"ALTER TABLE teacher_assets ADD COLUMN {col} {col_type} DEFAULT NULL"
                ))
                print(f"Added teacher_assets.{col}")
            except Exception as e:
                if "duplicate column" in str(e).lower():
                    print(f"teacher_assets.{col} already exists")
                else:
                    print(f"teacher_assets.{col}: {e}")

        # 2. 确保 video_generation_tasks 表存在
        from app.models.video_generation_model import VideoGenerationTask
        from sqlmodel import SQLModel
        SQLModel.metadata.create_all(engine)
        print("Ensured video_generation_tasks table exists")

        session.commit()
        print("Migration complete!")

if __name__ == "__main__":
    migrate()
