# 样式规范

## 1. CSS 命名规范

### 1.1 BEM 命名法

项目采用 BEM（Block-Element-Modifier）命名规范：

```css
.block {}
.block__element {}
.block--modifier {}
```

**示例：**
```css
.navbar {}
.navbar__logo {}
.navbar__nav-item {}
.navbar__nav-item--active {}
```

### 1.2 命名规则

- **块名**: 描述组件的功能，使用小写字母和短横线
- **元素**: 块的一部分，使用双下划线连接
- **修饰符**: 改变块或元素的状态或外观，使用双连字符连接

### 1.3 避免嵌套过深

```css
/* ❌ 不推荐：嵌套过深 */
.navbar .nav-links .nav-item {}

/* ✅ 推荐：使用BEM */
.navbar__nav-item {}
```

## 2. CSS 编写规范

### 2.1 注释规范

使用清晰的注释说明样式的用途：

```css
/* 🔷 导航栏样式 - 保持原有增强设计 */
.navbar {}

/* 💎 底部边框高光 */
.navbar::after {}
```

### 2.2 属性排序

按照逻辑顺序排序 CSS 属性：

1. 定位属性（position, top, right, bottom, left）
2. 盒模型属性（display, flex, grid, width, height, margin, padding）
3. 背景属性（background, color）
4. 文本属性（font, text-align, line-height）
5. 其他属性（transition, transform, box-shadow）

**示例：**
```css
.element {
  position: relative;
  top: 0;
  display: flex;
  justify-content: center;
  align-items: center;
  width: 100%;
  height: 50px;
  margin: 0 auto;
  padding: 10px;
  background-color: #fff;
  color: #333;
  font-size: 16px;
  font-weight: 500;
  transition: all 0.3s ease;
}
```

### 2.3 避免使用 !important

尽量通过提高选择器特异性来覆盖样式，避免使用 `!important`。

```css
/* ❌ 不推荐 */
.element {
  color: red !important;
}

/* ✅ 推荐 */
.parent .element {
  color: red;
}
```

### 2.4 使用 CSS 变量

项目建议使用 CSS 变量管理主题颜色和间距：

```css
:root {
  --primary-color: #0ea5e9;
  --secondary-color: #0284c7;
  --text-color: #0f172a;
  --border-color: #e2e8f0;
  --spacing-sm: 0.5rem;
  --spacing-md: 1rem;
  --spacing-lg: 2rem;
}

.element {
  color: var(--text-color);
  padding: var(--spacing-md);
  border: 1px solid var(--border-color);
}
```

## 3. Vue 样式特性

### 3.1 Scoped CSS

项目使用 scoped CSS 避免样式冲突：

```vue
<style scoped>
/* 只作用于当前组件 */
.element {}
</style>
```

### 3.2 深度选择器

使用深度选择器修改子组件样式：

```css
:deep(.child-component) {
  color: red;
}
```

### 3.3 全局样式

全局样式应放置在 `App.vue` 或专门的样式文件中：

```vue
/* App.vue */
<style>
/* 全局样式 */
* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  line-height: 1.6;
  color: #333;
}
</style>
```

## 4. 响应式设计

### 4.1 媒体查询

使用媒体查询实现响应式布局：

```css
/* 移动端 */
@media (max-width: 768px) {
  .navbar {
    flex-direction: column;
    gap: 1rem;
    padding: 1rem;
  }
}

/* 平板 */
@media (min-width: 769px) and (max-width: 1024px) {
  .main-content {
    padding: 0 1.5rem;
  }
}

/* 桌面 */
@media (min-width: 1025px) {
  .main-content {
    max-width: 1200px;
    margin: 0 auto;
  }
}
```

### 4.2 弹性布局

优先使用 Flexbox 和 Grid 布局：

```css
.container {
  display: flex;
  justify-content: center;
  align-items: center;
  flex-wrap: wrap;
  gap: 1rem;
}

.grid-container {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
  gap: 1rem;
}
```

## 5. 动画与过渡

### 5.1 过渡效果

使用 CSS transition 实现平滑过渡：

```css
.button {
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
}

.button:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 8px rgba(0, 0, 0, 0.1);
}
```

### 5.2 动画效果

使用 CSS animation 实现复杂动画：

```css
@keyframes fadeIn {
  from {
    opacity: 0;
    transform: translateY(10px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.element {
  animation: fadeIn 0.5s ease forwards;
}
```

## 6. 样式优化

### 6.1 减少重绘和回流

- 使用 `transform` 和 `opacity` 进行动画
- 避免频繁修改布局属性
- 使用 `contain: layout` 限制影响范围

### 6.2 使用 CSS 硬件加速

```css
.element {
  transform: translateZ(0); /* 触发硬件加速 */
}
```

### 6.3 避免 CSS 表达式

避免使用 CSS 表达式，它们会频繁计算：

```css
/* ❌ 不推荐 */
.element {
  width: expression(document.body.clientWidth + 'px');
}
```

## 7. 颜色系统

### 7.1 主色调

项目使用蓝色系作为主色调：

- **主色**: `#0ea5e9`
- **主色深**: `#0284c7`
- **主色浅**: `#7dd3fc`

### 7.2 辅助色

- **成功**: `#10b981`
- **警告**: `#f59e0b`
- **错误**: `#ef4444`
- **信息**: `#3b82f6`

### 7.3 中性色

- **文本**: `#0f172a`
- **次要文本**: `#64748b`
- **边框**: `#e2e8f0`
- **背景**: `#f8fafc`

## 8. 字体系统

### 8.1 字体家族

```css
font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
```

### 8.2 字体大小

```css
:root {
  --font-size-xs: 0.75rem;   /* 12px */
  --font-size-sm: 0.875rem;  /* 14px */
  --font-size-base: 1rem;     /* 16px */
  --font-size-lg: 1.125rem;  /* 18px */
  --font-size-xl: 1.25rem;   /* 20px */
  --font-size-2xl: 1.5rem;   /* 24px */
}
```

### 8.3 字体权重

```css
font-weight: 400; /* 常规 */
font-weight: 500; /* 中等 */
font-weight: 600; /* 半粗体 */
font-weight: 700; /* 粗体 */
font-weight: 800; /* 特粗体 */
```

## 9. 间距系统

```css
:root {
  --spacing-0: 0;
  --spacing-1: 0.25rem;  /* 4px */
  --spacing-2: 0.5rem;   /* 8px */
  --spacing-3: 0.75rem;  /* 12px */
  --spacing-4: 1rem;     /* 16px */
  --spacing-5: 1.25rem;  /* 20px */
  --spacing-6: 1.5rem;   /* 24px */
  --spacing-8: 2rem;     /* 32px */
  --spacing-10: 2.5rem;  /* 40px */
  --spacing-12: 3rem;    /* 48px */
}
```

## 10. 组件样式示例

### 10.1 按钮样式

```css
.btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: var(--spacing-3) var(--spacing-6);
  border-radius: 8px;
  font-weight: 500;
  font-size: var(--font-size-sm);
  transition: all 0.2s ease;
  cursor: pointer;
  border: none;
}

.btn-primary {
  background-color: var(--primary-color);
  color: white;
}

.btn-primary:hover {
  background-color: var(--secondary-color);
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(14, 165, 233, 0.3);
}

.btn-secondary {
  background-color: white;
  color: var(--text-color);
  border: 1px solid var(--border-color);
}

.btn-secondary:hover {
  background-color: #f8fafc;
  border-color: var(--primary-color);
}
```

### 10.2 卡片样式

```css
.card {
  background: white;
  border-radius: 12px;
  padding: var(--spacing-6);
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
  border: 1px solid var(--border-color);
  transition: all 0.3s ease;
}

.card:hover {
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
  transform: translateY(-2px);
}

.card-header {
  margin-bottom: var(--spacing-4);
  padding-bottom: var(--spacing-4);
  border-bottom: 1px solid var(--border-color);
}

.card-title {
  font-size: var(--font-size-lg);
  font-weight: 600;
  color: var(--text-color);
}

.card-body {
  color: var(--secondary-text);
  line-height: 1.6;
}
```

## 11. 代码格式化

### 11.1 缩进

使用 2 个空格作为缩进：

```css
.element {
  display: flex;
  justify-content: center;
  align-items: center;
}
```

### 11.2 换行

每个属性单独一行：

```css
.element {
  width: 100%;
  height: 100%;
  margin: 0;
  padding: 0;
}
```

### 11.3 分号

每个属性末尾添加分号：

```css
.element {
  color: red;
  font-size: 16px;
}
```

## 12. 浏览器兼容性

### 12.1 前缀处理

使用 Autoprefixer 自动添加浏览器前缀。

### 12.2 降级方案

为不支持新特性的浏览器提供降级方案：

```css
.element {
  /* 现代浏览器 */
  display: grid;
  /* 降级方案 */
  display: -ms-grid;
}
```

### 12.3 特性检测

使用 CSS @supports 进行特性检测：

```css
@supports (display: grid) {
  .grid-container {
    display: grid;
  }
}

@supports not (display: grid) {
  .grid-container {
    display: flex;
    flex-wrap: wrap;
  }
}
```

## 13. 性能优化建议

1. **减少 CSS 文件大小**
   - 移除未使用的 CSS
   - 使用 CSS 压缩工具
   - 合并 CSS 文件

2. **使用 CSS Sprites**
   - 将小图标合并为一张图片
   - 使用 background-position 定位

3. **避免使用 CSS 滤镜**
   - 滤镜会影响性能
   - 尽量使用图片处理工具预处理

4. **使用 will-change**
   - 提示浏览器优化动画元素

```css
.element {
  will-change: transform;
}
```

## 14. 样式调试技巧

1. **使用浏览器开发者工具**
   - 检查元素样式
   - 修改样式实时预览
   - 查看样式继承关系

2. **添加调试类**
   - 临时添加边框或背景色
   - 帮助定位布局问题

```css
.debug {
  border: 1px solid red !important;
}
```

3. **使用 CSS 变量调试**
   - 修改 CSS 变量值观察效果
   - 快速测试不同主题
