<template>
  <div class="profile-page">
    <div class="profile-container">

      <!-- 用户信息卡片 -->
      <div class="user-card">
        <div class="avatar">A</div>
        <div class="user-info">
          <h2>Admin User</h2>
          <p>系统管理员 | 技术部</p>
          <span class="email">admin@company.com</span>
        </div>
      </div>

      <!-- 功能菜单 -->
      <div class="menu-grid">
        <div class="menu-card">
          <h3>账户设置</h3>
          <p>管理个人资料、邮箱与头像</p>
        </div>
        <div class="menu-card">
          <h3>安全中心</h3>
          <p>修改密码、双因素认证、登录日志</p>
        </div>
        <div class="menu-card">
          <h3>偏好设置</h3>
          <p>主题、布局、消息通知配置</p>
        </div>
        <div class="menu-card">
          <h3>API 密钥</h3>
          <p>管理开发者 API 访问令牌</p>
        </div>
      </div>

      <!-- 底部版权 -->
      <div class="footer">
        <p>泛雅智能教学平台 · 企业版 v2.4.1</p>
        <p>© 2026 泛雅科技 保留所有权利</p>
      </div>

    </div>
  </div>
</template>

<style scoped>
/* 基础页面 */
.profile-page {
  width: 100%;
  min-height: 100vh;
  background: #f8fafc;
  padding: 100px 20px 60px;
  display: flex;
  justify-content: center;
}

.profile-container {
  max-width: 1000px;
  width: 100%;
  display: flex;
  flex-direction: column;
  gap: 40px; /* 整体更宽松 */
}

/* 用户卡片 */
.user-card {
  background: #ffffff;
  border-radius: 20px;
  padding: 36px;
  border: 1px solid #e2e8f0;
  display: flex;
  align-items: center;
  gap: 24px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
}

.avatar {
  width: 80px;
  height: 80px;
  border-radius: 50%;
  background: linear-gradient(135deg, #3b82f6, #8b5cf6);
  color: white;
  font-size: 32px;
  display: grid;
  place-items: center;
  flex-shrink: 0;
}

.user-info h2 {
  font-size: 26px;
  font-weight: 700;
  color: #0f172a;
  margin: 0 0 8px;
}

.user-info p {
  color: #64748b;
  margin: 0 0 6px;
  font-size: 15px;
}

.email {
  color: #3b82f6;
  font-size: 14px;
}

/* 菜单卡片 —— 电脑版：更舒展、间距更大 */
.menu-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 28px; /* 卡片之间更宽松 */
}

.menu-card {
  background: white;
  border: 1px solid #e2e8f0;
  border-radius: 20px;
  padding: 32px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
  min-height: 140px; /* 让卡片更高，不挤 */
  display: flex;
  flex-direction: column;
  justify-content: center;
}

.menu-card h3 {
  font-size: 18px;
  color: #1e293b;
  margin: 0 0 10px;
}

.menu-card p {
  font-size: 14px;
  color: #94a3b8;
  margin: 0;
}

/* 底部 */
.footer {
  text-align: center;
  color: #94a3b8;
  font-size: 13px;
  line-height: 1.6;
  margin-top: 20px;
}

/* ====================================== */
/* 手机端：自动单列 + 居中 + 美观 */
/* ====================================== */
@media (max-width: 768px) {
  .menu-grid {
    grid-template-columns: 1fr;
    gap: 20px;
  }

  .user-card {
    flex-direction: column;
    text-align: center;
    padding: 32px 20px;
  }

  .avatar {
    width: 75px;
    height: 75px;
  }

  .user-info h2 {
    font-size: 22px;
  }
}
</style>
