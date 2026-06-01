"""
AI课程系统 - 测试数据生成脚本
功能：为现有课程批量创建学生账号、选课记录和学习进度数据

使用方法：
    cd backend
    python scripts/generate_test_data.py

生成的数据：
    - 学生账号：student_001 ~ student_600（密码统一123456）
    - 每门课程50-100人选课
    - 不同的学习进度（0%-100%）
    - 真实的学习时长和节点完成情况
"""

import sys
import os
import random
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlmodel import Session, select
from app.models.database import get_session, engine
from app.models.user_model import User, UserRole
from app.models.course_model import Course, CourseStatus, StudentEnrollment, ScriptNode, CourseScript
from app.models.progress_model import LearningProgress, NodeProgress, LearningStatus, UnderstandingLevel
from app.core.security import get_password_hash


# ==================== 配置参数 ====================
STUDENT_PASSWORD = "123456"
MIN_STUDENTS_PER_COURSE = 50
MAX_STUDENTS_PER_COURSE = 100
BASE_STUDENT_ID = 1  # 起始学生编号

# 常见中文姓名库（用于生成真实感的学生名字）
SURNAMES = ["张", "王", "李", "刘", "陈", "杨", "赵", "黄", "周", "吴",
            "徐", "孙", "胡", "朱", "高", "林", "何", "郭", "马", "罗",
            "梁", "宋", "郑", "谢", "韩", "唐", "冯", "于", "董", "萧",
            "程", "曹", "袁", "邓", "许", "傅", "沈", "曾", "彭", "吕"]
GIVEN_NAMES = ["伟", "芳", "娜", "秀英", "敏", "静", "丽", "强", "磊", "军",
               "洋", "勇", "艳", "杰", "娟", "涛", "明", "超", "秀兰", "霞",
               "平", "刚", "桂英", "华", "玲", "飞", "玉兰", "萍", "红", "建华",
               "文", "辉", "丹", "建国", "建军", "婷", "志强", "慧", "建平"]


def generate_chinese_name():
    """随机生成中文姓名"""
    surname = random.choice(SURNAMES)
    if random.random() > 0.5:
        given = random.choice(GIVEN_NAMES)
    else:
        given = random.choice(GIVEN_NAMES[:20]) + random.choice(GIVEN_NAMES[20:])
    return f"{surname}{given}"


def generate_student_username(student_num):
    """生成学生用户名"""
    return f"student_{student_num:03d}"


def create_student_user(session: Session, student_num: int) -> User:
    """
    创建一个学生用户

    Args:
        session: 数据库会话
        student_num: 学生编号（从1开始）

    Returns:
        创建的User对象
    """
    username = generate_student_username(student_num)
    
    # 检查是否已存在
    existing = session.exec(
        select(User).where(User.username == username)
    ).first()
    
    if existing:
        print(f"  [跳过] 用户 {username} 已存在")
        return existing
    
    # 密码哈希
    hashed_pwd = get_password_hash(STUDENT_PASSWORD)
    
    user = User(
        username=username,
        real_name=generate_chinese_name(),
        email=f"{username}@test.edu.cn",
        hashed_password=hashed_pwd,
        role=UserRole.STUDENT,
        is_active=True,
    )
    
    session.add(user)
    session.commit()
    session.refresh(user)
    
    return user


def get_course_nodes(session: Session, course_id: int) -> list:
    """获取课程的所有节点"""
    script = session.exec(
        select(CourseScript).where(
            CourseScript.course_id == course_id,
            CourseScript.is_active == True
        )
    ).first()
    
    if not script:
        return []
    
    nodes = session.exec(
        select(ScriptNode).where(
            ScriptNode.script_id == script.id
        ).order_by(ScriptNode.node_index)
    ).all()
    
    return list(nodes)


def create_enrollment_and_progress(
    session: Session,
    student: User,
    course: Course,
    nodes: list
):
    """
    为学生创建选课记录和学习进度
    
    生成策略：
    - 随机决定完成度（偏向正态分布，集中在30%-80%）
    - 根据完成度计算已完成节点数
    - 生成合理的学习时长
    - 随机分配理解度等级
    """
    total_nodes = len(nodes)
    
    if total_nodes == 0:
        total_nodes = random.randint(8, 15)  # 默认假设有这么多节点
    
    # 生成完成度（正态分布，均值60%，标准差20%）
    completion_rate = min(1.0, max(0.0, random.gauss(0.6, 0.2)))
    
    # 计算已完成节点数
    completed_nodes = int(total_nodes * completion_rate)
    
    # 当前学习的节点索引（在已完成节点附近）
    if completed_nodes < total_nodes:
        current_node_index = completed_nodes + random.randint(0, min(3, total_nodes - completed_nodes - 1))
    else:
        current_node_index = total_nodes - 1
    
    # 学习状态判断
    if completion_rate >= 1.0:
        status = LearningStatus.COMPLETED
    elif completion_rate > 0:
        status = LearningStatus.IN_PROGRESS
    else:
        status = random.choice([LearningStatus.NOT_STARTED, LearningStatus.IN_PROGRESS])
    
    # 计算学习时长（每节点平均3-8分钟）
    avg_time_per_node = random.randint(180, 480)  # 秒
    total_learning_time = completed_nodes * avg_time_per_node + random.randint(0, 300)
    
    # 学习次数（每3-5次学习完成一个节点）
    session_count = max(1, completed_nodes // random.randint(2, 4) + 1)
    
    # 时间偏移（模拟不同时间选课和学习）
    days_ago_enroll = random.randint(1, 30)
    hours_ago_study = random.randint(0, 23)
    minutes_ago = random.randint(0, 59)
    
    enrolled_at = datetime.utcnow() - timedelta(days=days_ago_enroll)
    last_accessed_at = datetime.utcnow() - timedelta(
        days=random.randint(0, days_ago_enroll),
        hours=hours_ago_study,
        minutes=minutes_ago
    )
    started_at = enrolled_at + timedelta(hours=random.randint(1, 24))
    
    # 创建选课记录
    enrollment = StudentEnrollment(
        student_id=student.id,
        course_id=course.id,
        enrolled_at=enrolled_at,
        total_nodes_completed=completed_nodes,
        total_nodes_count=total_nodes,
        overall_progress=completion_rate * 100,
        total_study_minutes=int(total_learning_time / 60),
        last_study_time=last_accessed_at,
        is_active=True,
    )
    
    session.add(enrollment)
    session.commit()
    session.refresh(enrollment)
    
    # 创建学习进度主记录
    progress = LearningProgress(
        user_id=student.id,
        course_id=course.id,
        current_node_index=current_node_index,
        current_node_id=nodes[current_node_index].id if current_node_index < len(nodes) else None,
        total_nodes=total_nodes,
        completed_nodes=completed_nodes,
        completion_rate=completion_rate,
        status=status,
        total_learning_time=total_learning_time,
        session_count=session_count,
        last_accessed_at=last_accessed_at,
        started_at=started_at,
        completed_at=datetime.utcnow() - timedelta(days=random.randint(0, 7)) if status == LearningStatus.COMPLETED else None,
    )
    
    session.add(progress)
    session.commit()
    session.refresh(progress)
    
    # 创建每个节点的进度记录
    for idx, node in enumerate(nodes):
        node_is_completed = idx < completed_nodes
        
        # 理解度分布（已完成节点理解度较高）
        if node_is_completed:
            understanding_score = random.uniform(0.6, 1.0)
            if understanding_score >= 0.9:
                level = UnderstandingLevel.EXCELLENT
            elif understanding_score >= 0.75:
                level = UnderstandingLevel.HIGH
            elif understanding_score >= 0.5:
                level = UnderstandingLevel.MEDIUM
            else:
                level = UnderstandingLevel.LOW
            
            time_spent = random.randint(120, 600)  # 2-10分钟
            question_count = random.randint(0, 5)
            completion_count = 1
        else:
            # 未完成的节点可能有部分学习
            if idx <= current_node_index and idx >= max(0, current_node_index - 2):
                understanding_score = random.uniform(0.2, 0.6)
                level = random.choice([UnderstandingLevel.LOW, UnderstandingLevel.MEDIUM])
                time_spent = random.randint(30, 180)
                question_count = random.randint(0, 3)
            else:
                understanding_score = None
                level = None
                time_spent = 0
                question_count = 0
            
            completion_count = 0
        
        node_progress = NodeProgress(
            progress_id=progress.id,
            node_id=node.id,
            node_index=node.node_index,
            is_completed=node_is_completed,
            completion_count=completion_count,
            time_spent=time_spent,
            understanding_level=level,
            understanding_score=understanding_score,
            question_count=question_count,
            first_accessed_at=enrolled_at + timedelta(minutes=random.randint(1, 1440)) if time_spent > 0 else None,
            last_accessed_at=last_accessed_at - timedelta(minutes=random.randint(0, 1440)) if time_spent > 0 else None,
            completed_at=started_at + timedelta(days=random.randint(0, days_ago_enroll)) if node_is_completed else None,
        )
        
        session.add(node_progress)
    
    session.commit()


def main():
    """主函数：生成所有测试数据"""
    print("=" * 70)
    print("[AI课程系统] 测试数据生成器")
    print("=" * 70)
    
    # 创建数据库会话
    with Session(engine) as session:
        # 1. 查询所有已发布的课程
        print("\n[步骤1] 查询已发布课程...")
        courses = session.exec(
            select(Course).where(Course.status == CourseStatus.PUBLISHED).order_by(Course.id)
        ).all()
        
        if not courses:
            print("[错误] 没有找到已发布的课程！")
            print("   请先确保数据库中存在已发布的课程。")
            return
        
        print(f"[成功] 找到 {len(courses)} 门已发布的课程:")
        for course in courses:
            print(f"   - [{course.id}] {course.title}")
        
        # 2. 统计需要的学生总数
        print("\n[步骤2] 规划学生数量...")
        course_student_counts = {}
        total_students_needed = 0
        
        for course in courses:
            count = random.randint(MIN_STUDENTS_PER_COURSE, MAX_STUDENTS_PER_COURSE)
            course_student_counts[course.id] = count
            total_students_needed += count
            print(f"   课程 [{course.title}]: 需要 {count} 名学生")
        
        print(f"\n   总共需要创建/复用约 {total_students_needed} 个学生账号")
        
        # 3. 创建学生用户
        print("\n[步骤3] 创建学生账号...")
        students_map = {}  # student_num -> User对象
        student_counter = BASE_STUDENT_ID
        
        for course_id, needed_count in course_student_counts.items():
            course_students = []
            
            for _ in range(needed_count):
                # 复用已有学生或创建新学生
                if student_counter in students_map:
                    student = students_map[student_counter]
                else:
                    student = create_student_user(session, student_counter)
                    students_map[student_counter] = student
                    
                    if student_counter % 50 == 0:
                        print(f"   [OK] 已创建 {student_counter - BASE_STUDENT_ID + 1} 个学生账号...")
                
                course_students.append(student)
                
                # 循环使用学生ID，让不同课程共享学生
                student_counter += 1
                if student_counter > BASE_STUDENT_ID + 200:  # 最多200个不重复学生
                    student_counter = BASE_STUDENT_ID
        
        total_unique_students = len(students_map)
        print(f"\n[OK] 共创建了 {total_unique_students} 个唯一学生账号")
        print(f"   用户名格式: student_001 ~ student_{BASE_STUDENT_ID + total_unique_students - 1:03d}")
        print(f"   统一密码: {STUDENT_PASSWORD}")
        
        # 4. 为每门课程创建选课记录和学习进度
        print("\n[步骤4] 生成选课记录和学习进度...")
        
        for course in courses:
            course_id = course.id
            needed_count = course_student_counts[course_id]
            
            print(f"\n   [处理] 课程: [{course.title}] (目标{needed_count}人)")
            
            # 获取课程的节点信息
            nodes = get_course_nodes(session, course_id)
            print(f"      找到 {len(nodes)} 个学习节点")
            
            # 选择学生并创建记录
            selected_students = random.sample(
                list(students_map.values()),
                min(needed_count, len(students_map))
            )
            
            for i, student in enumerate(selected_students):
                create_enrollment_and_progress(session, student, course, nodes)
                
                if (i + 1) % 20 == 0:
                    print(f"      [进度] 已处理 {i + 1}/{needed_count} 名学生的选课和进度...")
            
            print(f"      [完成] 本课程共有 {len(selected_students)} 名学生选课")
        
        # 5. 统计汇总
        print("\n" + "=" * 70)
        print("[统计] 数据生成完成！汇总信息：")
        print("=" * 70)
        
        total_enrollments = session.exec(
            select(StudentEnrollment).where(StudentEnrollment.is_active == True)
        ).all()
        
        total_progress = session.exec(select(LearningProgress)).all()
        total_node_progress = session.exec(select(NodeProgress)).all()
        
        print(f"\n[数据统计]:")
        print(f"   - 学生账号数: {total_unique_students}")
        print(f"   - 选课记录数: {len(total_enrollments)}")
        print(f"   - 学习进度记录: {len(total_progress)}")
        print(f"   - 节点进度记录: {len(total_node_progress)}")
        
        print(f"\n[各课程选课人数]:")
        for course in courses:
            enrollment_count = session.exec(
                select(func.count()).select_from(StudentEnrollment).where(
                    StudentEnrollment.course_id == course.id,
                    StudentEnrollment.is_active == True
                )
            ).one()
            
            avg_progress = session.exec(
                select(func.avg(StudentEnrollment.overall_progress)).where(
                    StudentEnrollment.course_id == course.id,
                    StudentEnrollment.is_active == True
                )
            ).one()
            
            print(f"   - {course.title}: {enrollment_count}人 (平均进度: {avg_progress:.1f}%)")
        
        print("\n" + "=" * 70)
        print("[成功] 测试数据生成成功！")
        print("=" * 70)
        print(f"\n[测试账号信息]:")
        print(f"   用户名: student_001 ~ student_{BASE_STUDENT_ID + total_unique_students - 1:03d}")
        print(f"   密码: {STUDENT_PASSWORD}")
        print(f"\n[访问地址]:")
        print(f"   前端: http://localhost:5174/")
        print(f"   教师端可查看各课程的学生状态和学习统计")


if __name__ == "__main__":
    from sqlmodel import func
    main()
