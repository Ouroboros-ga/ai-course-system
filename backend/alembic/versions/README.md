# Alembic 迁移版本目录
#
# 每个 revision 文件代表一次数据库结构变更或数据迁移。
# 命名规范：YYYYMMDD_HHMM_<revision_id>_<slug>.py
#
# 版本链（按时间顺序）：
#   0001_legacy_schema_baseline       - 基线：当前所有表的完整结构
#   0002_access_control_backfill     - Course Access v1 历史数据回填
#   0003_agent_log_redaction          - Agent 日志脱敏（不可逆）
#   0004_avatar_upload_security_v1   - 教师数字人素材上传与预处理安全链路
#   0008_coding_diagnosis_timezone - CodingDiagnosis 时间字段改为带时区 UTC（旧基线表分批迁移）
