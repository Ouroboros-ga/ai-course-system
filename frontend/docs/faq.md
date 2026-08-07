# 常见问题解决方案

## 1. 开发环境问题

### 1.1 依赖安装失败

**问题描述**: 运行 `npm install` 时出现依赖安装失败。

**解决方案**:
1. 清理 npm 缓存: `npm cache clean --force`
2. 删除 `node_modules` 和 `package-lock.json`
3. 重新安装: `npm install`
4. 如果仍失败，检查网络连接或使用淘宝镜像:
   ```bash
   npm config set registry https://registry.npmmirror.com
   npm install
   ```

### 1.2 开发服务器启动失败

**问题描述**: 运行 `npm run dev` 时开发服务器无法启动。

**解决方案**:
1. 检查端口是否被占用: `netstat -ano | findstr :5173`
2. 若报 `listen EACCES: permission denied` 且端口无进程占用,通常是端口落在 Windows
   端口排除范围内(Hyper-V/WinNAT 动态保留,可用
   `netsh interface ipv4 show excludedportrange protocol=tcp` 查看)。
   本项目已默认改用 5300(不在排除范围内),无需再使用 5173。
3. 更换端口: 在 `vite.config.js` 中配置端口
   ```javascript
   export default {
     server: {
       port: 3000
     }
   }
   ```
4. 检查防火墙设置，确保端口允许访问

### 1.3 模块导入错误

**问题描述**: 组件中导入模块时出现 `Module not found` 错误。

**解决方案**:
1. 检查文件路径是否正确
2. 确保文件扩展名正确（`.vue`, `.js` 等）
3. 检查是否忘记导出模块
4. 重新启动开发服务器

## 2. 编译和构建问题

### 2.1 ESLint 报错

**问题描述**: 运行 `npm run lint` 时出现代码规范错误。

**解决方案**:
1. 自动修复: `npm run lint:oxlint` 或 `npm run lint:eslint`
2. 手动修复报错的代码
3. 如果某些规则不需要，可以在 `.eslintrc.json` 中禁用

### 2.2 构建失败

**问题描述**: 运行 `npm run build` 时构建失败。

**解决方案**:
1. 检查是否有语法错误
2. 检查 TypeScript 类型错误
3. 查看构建日志，定位具体错误
4. 确保所有依赖都已正确安装

### 2.3 构建产物过大

**问题描述**: 构建后的文件体积过大。

**解决方案**:
1. 使用路由懒加载
2. 优化图片资源（压缩、使用 WebP 格式）
3. 配置 Vite 构建选项，启用代码分割
4. 使用 Tree Shaking 移除未使用的代码

## 3. 运行时问题

### 3.1 路由跳转问题

**问题描述**: 路由跳转时出现错误或页面不显示。

**解决方案**:
1. 检查路由配置是否正确
2. 确认组件文件路径正确
3. 检查路由守卫是否正确配置
4. 使用 Vue DevTools 查看路由状态

### 3.2 API 请求失败

**问题描述**: API 请求返回错误或无法连接。

**解决方案**:
1. 检查后端服务是否启动
2. 检查 API 地址是否正确
3. 查看浏览器控制台的网络请求日志
4. 检查请求参数和签名是否正确
5. 检查 Token 是否过期

### 3.3 状态管理问题

**问题描述**: Pinia 状态不更新或组件无法获取状态。

**解决方案**:
1. 确保正确导入 store
2. 使用 `storeToRefs` 获取响应式状态
3. 检查状态更新方法是否正确调用
4. 使用 Vue DevTools 查看状态变化

### 3.4 组件渲染问题

**问题描述**: 组件无法正确渲染或样式错误。

**解决方案**:
1. 检查组件模板语法是否正确
2. 检查 props 传递是否正确
3. 查看浏览器控制台的错误信息
4. 检查 CSS 样式是否冲突

## 4. 样式问题

### 4.1 CSS 样式不生效

**问题描述**: 添加的 CSS 样式没有生效。

**解决方案**:
1. 检查选择器是否正确
2. 检查 CSS 优先级问题
3. 检查是否使用了 `scoped` CSS
4. 查看浏览器开发者工具的样式面板

### 4.2 响应式布局问题

**问题描述**: 在不同屏幕尺寸下布局错乱。

**解决方案**:
1. 检查媒体查询是否正确
2. 使用弹性布局（Flexbox）和网格布局（Grid）
3. 确保设置了正确的盒模型: `box-sizing: border-box`
4. 测试不同屏幕尺寸的布局效果

### 4.3 动画效果问题

**问题描述**: CSS 动画不流畅或无法正常工作。

**解决方案**:
1. 使用 `transform` 和 `opacity` 进行动画
2. 避免频繁修改布局属性
3. 使用 `will-change` 属性优化动画
4. 检查动画属性是否正确设置

## 5. 性能问题

### 5.1 页面加载缓慢

**问题描述**: 页面加载时间过长。

**解决方案**:
1. 使用路由懒加载
2. 优化图片资源
3. 启用浏览器缓存
4. 使用 CDN 加速资源加载
5. 减少 HTTP 请求数量

### 5.2 组件渲染性能差

**问题描述**: 组件渲染缓慢或卡顿。

**解决方案**:
1. 使用 `v-memo` 优化列表渲染
2. 使用 `keep-alive` 缓存组件
3. 减少不必要的响应式数据
4. 使用 `shallowRef` 和 `shallowReactive`
5. 避免在模板中使用复杂计算

### 5.3 内存泄漏

**问题描述**: 应用运行一段时间后内存占用不断增加。

**解决方案**:
1. 清理定时器和事件监听器
2. 正确使用组件生命周期钩子
3. 避免循环引用
4. 使用 Vue DevTools 检测内存泄漏

## 6. 安全问题

### 6.1 Token 安全

**问题描述**: Token 存储和使用存在安全隐患。

**解决方案**:
1. 使用 HTTPS 传输
2. 设置合理的 Token 过期时间
3. 避免在 localStorage 中存储敏感信息
4. 实现 Token 刷新机制

### 6.2 XSS 攻击

**问题描述**: 存在跨站脚本攻击风险。

**解决方案**:
1. 使用 Vue 的自动转义功能
2. 避免使用 `v-html`
3. 对用户输入进行验证和过滤
4. 设置适当的 Content Security Policy

### 6.3 CSRF 攻击

**问题描述**: 存在跨站请求伪造风险。

**解决方案**:
1. 实现 CSRF Token 验证
2. 设置 SameSite Cookie 属性
3. 验证请求来源
4. 使用双重提交 Cookie 模式

## 7. 调试技巧

### 7.1 使用浏览器开发者工具

1. **Elements 面板**: 查看和修改 DOM 结构
2. **Console 面板**: 查看日志和错误信息
3. **Network 面板**: 监控网络请求
4. **Performance 面板**: 分析页面性能
5. **Memory 面板**: 检测内存泄漏

### 7.2 使用 Vue DevTools

1. **Components 面板**: 查看组件树和状态
2. **Pinia 面板**: 查看状态管理
3. **Router 面板**: 查看路由状态
4. **Performance 面板**: 分析组件性能

### 7.3 添加调试日志

```javascript
// 添加详细的调试日志
console.log('调试信息:', data)
console.error('错误信息:', error)
console.warn('警告信息:', warning)

// 使用断点调试
debugger
```

## 8. 部署问题

### 8.1 生产环境部署

**问题描述**: 部署到生产环境后出现问题。

**解决方案**:
1. 确保使用正确的构建命令: `npm run build`
2. 检查环境变量配置
3. 确保后端 API 地址正确
4. 配置正确的路由模式（history 模式需要服务器支持）

### 8.2 Nginx 配置

**问题描述**: 使用 Nginx 部署时出现 404 错误。

**解决方案**:
```nginx
server {
  listen 80;
  server_name example.com;
  root /path/to/dist;
  
  location / {
    try_files $uri $uri/ /index.html;
  }
  
  location /api {
    proxy_pass http://localhost:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
  }
}
```

### 8.3 CDN 配置

**问题描述**: 使用 CDN 时资源加载问题。

**解决方案**:
1. 配置正确的 CDN 域名
2. 设置合理的缓存策略
3. 确保资源路径正确
4. 处理跨域问题

## 9. 跨域问题

### 9.1 CORS 错误

**问题描述**: 浏览器报 CORS 错误。

**解决方案**:
1. 后端配置 CORS 头
   ```python
   # Flask 示例
   from flask_cors import CORS
   CORS(app)
   ```
2. 使用代理服务器
3. 配置 Vite 开发服务器代理
   ```javascript
   // vite.config.js
   export default {
     server: {
       proxy: {
         '/api': {
           target: 'http://localhost:8000',
           changeOrigin: true
         }
       }
     }
   }
   ```

### 9.2 跨域资源访问

**问题描述**: 无法访问跨域资源。

**解决方案**:
1. 使用 JSONP（仅支持 GET 请求）
2. 使用 CORS（需要后端支持）
3. 使用代理服务器
4. 使用 WebSocket

## 10. 其他常见问题

### 10.1 字体加载问题

**问题描述**: 字体无法正常加载。

**解决方案**:
1. 检查字体文件路径
2. 确保字体格式正确（.woff2, .woff, .ttf）
3. 添加字体预加载
4. 处理字体加载失败的回退方案

### 10.2 图片加载问题

**问题描述**: 图片无法加载或显示错误。

**解决方案**:
1. 检查图片路径
2. 确保图片格式正确
3. 检查图片权限
4. 使用占位符图片
5. 实现图片懒加载

### 10.3 表单验证问题

**问题描述**: 表单验证不生效或验证逻辑错误。

**解决方案**:
1. 检查验证规则是否正确
2. 确保验证时机正确
3. 检查错误提示是否正确显示
4. 使用表单验证库（如 Vuelidate）

### 10.4 第三方库集成问题

**问题描述**: 集成第三方库时出现问题。

**解决方案**:
1. 检查库的版本兼容性
2. 查看官方文档和示例
3. 检查导入方式是否正确
4. 处理库的初始化和销毁

## 11. 性能监控和优化

### 11.1 使用 Lighthouse 分析

```bash
# 安装 Lighthouse
npm install -g lighthouse

# 运行分析
lighthouse https://example.com --view
```

### 11.2 性能优化建议

1. **减少 HTTP 请求**: 合并资源，使用 CSS Sprites
2. **优化图片**: 压缩图片，使用 WebP 格式
3. **使用缓存**: 设置合理的缓存策略
4. **代码分割**: 使用路由懒加载
5. **优化渲染**: 使用虚拟滚动，减少重绘和回流

## 12. 最佳实践

### 12.1 代码组织

1. 遵循单一职责原则
2. 使用清晰的命名规范
3. 添加适当的注释
4. 保持代码简洁和可读性

### 12.2 开发流程

1. 使用版本控制（Git）
2. 遵循代码审查流程
3. 编写单元测试和集成测试
4. 使用自动化构建和部署

### 12.3 团队协作

1. 统一代码规范
2. 使用一致的开发环境
3. 建立清晰的沟通渠道
4. 文档化开发流程和规范

## 13. 资源推荐

### 13.1 学习资源

- Vue 官方文档: https://vuejs.org/
- Vite 官方文档: https://vitejs.dev/
- Vue Router 文档: https://router.vuejs.org/
- Pinia 文档: https://pinia.vuejs.org/

### 13.2 工具推荐

- Vue DevTools: 浏览器扩展，用于调试 Vue 应用
- ESLint: 代码规范检查工具
- Prettier: 代码格式化工具
- Lighthouse: 性能分析工具
- Chrome DevTools: 浏览器开发者工具

### 13.3 社区支持

- Vue 官方论坛: https://forum.vuejs.org/
- GitHub Issues: 报告和解决问题
- Stack Overflow: 查找和解答问题
- Discord/Slack 社区: 实时交流和讨论
